#!/usr/bin/env python3
"""Shared boilerplate for the MOPA breast-cancer prior-auth demo (PhenoML SDK v15).

Config/auth, small helpers, agent cleanup, and a tiny on-disk artifact store used to pass data
between the step scripts (step1_intake -> step1_5_readiness -> step2_cdshooks -> step3_ordersign).
The *interesting* code, prompts, agent.create, chat.send, lang2fhir, construe, the RequestGroup
assembly, and the CDS Hooks envelope, lives inline in each step script so they read top-to-bottom;
only the boilerplate nobody learns from lives here.

Credentials come from mopa-breast-pa/.env (preferred) or the repo-root ../.env.
Auth: PHENOML_CLIENT_ID + PHENOML_CLIENT_SECRET (OAuth client credentials, v15-native).
"""
import json, os, re, sys, time
from pathlib import Path

import httpx
from dotenv import dotenv_values
from phenoml import PhenomlClient

HERE = Path(__file__).resolve().parent   # anchor file paths to the script dir, not the cwd
STATE_DIR = HERE / ".state"              # gitignored; holds artifacts passed between step scripts
STATE_FILE = STATE_DIR / "state.json"


# ---------- config / auth -------------------------------------------------
def load_env() -> dict:
    env = dict(os.environ)                       # real env vars are the base layer
    for p in (HERE.parent / ".env", HERE / ".env"):   # .env files override env vars; local wins
        if p.exists():
            env.update({k: (v or "").strip().strip('"').strip("'")
                        for k, v in dotenv_values(p).items()})
    return env


def make_client(env: dict) -> PhenomlClient:
    base_url = env.get("PHENOML_BASE_URL") or None
    cid, csec = env.get("PHENOML_CLIENT_ID"), env.get("PHENOML_CLIENT_SECRET")
    # max_retries=0 turns OFF the SDK's *silent* auto-retry; the explicit retry() wrapper below is
    # the single, visible retry layer (so a flaky call never silently double-fires document/multi).
    kw = {"timeout": float(env.get("PHENOML_TIMEOUT", "300")), "max_retries": 0}
    if base_url:
        kw["base_url"] = base_url
    if cid and csec:
        print(f"[auth] OAuth client credentials (base_url={base_url})")
        return PhenomlClient(client_id=cid, client_secret=csec, **kw)
    sys.exit("No credentials found. Set PHENOML_CLIENT_ID and PHENOML_CLIENT_SECRET in .env (see .env.example)")


# ---------- helpers -------------------------------------------------------
def as_dict(obj):
    # by_alias=True is REQUIRED: SDK models use snake_case attrs (resource_type, full_url)
    # but FHIR/the API expect camelCase (resourceType, fullUrl). Without it, summary.create
    # (IPS) rejects the bundle with "resourceType field is missing".
    if hasattr(obj, "model_dump"):
        return obj.model_dump(by_alias=True, exclude_none=True)
    if isinstance(obj, list):
        return [as_dict(x) for x in obj]
    return obj


def parse_json(text: str) -> dict:
    """Best-effort: pull the first JSON object out of an LLM reply. ALWAYS returns a dict
    (empty if none can be recovered) so every caller can safely .get() the result, a stray
    top-level array or scalar must never reach the .get()s in score_case/cite_hits."""
    try:
        v = json.loads(text)
        if isinstance(v, dict):
            return v
    except Exception:
        pass
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if m:
        try:
            v = json.loads(m.group(0))
            if isinstance(v, dict):
                return v
        except Exception:
            pass
    return {}


def banner(title: str):
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78, flush=True)


def retry(fn, *args, attempts=3, base=4, label="", **kwargs):
    """Retry transient transport errors (server disconnects, read timeouts) with backoff."""
    for i in range(1, attempts + 1):
        try:
            return fn(*args, **kwargs)
        except httpx.TransportError as e:
            if i == attempts:
                raise
            wait = base * i
            print(f"  [retry {i}/{attempts}] {label}: {type(e).__name__}; waiting {wait}s", flush=True)
            time.sleep(wait)


def resolve_provider(client, env) -> str:
    """Resolve a FHIR provider id for agent.create / fhir.create. Prefer the .env value;
    otherwise borrow the first provider from fhir_provider.list(). agent.create 500s on an
    empty provider string, so if none can be found we exit with guidance instead."""
    p = env.get("PHENOML_FHIR_PROVIDER_ID") or env.get("FHIR_PROVIDER_ID") or ""
    if p:
        print(f"[fhir provider] {p}")
        return p
    try:
        provs = as_dict(client.fhir_provider.list()).get("fhir_providers") or []
    except Exception as e:
        provs = []
        print(f"[provider] lookup failed: {type(e).__name__}: {str(e)[:120]}")
    pid = next((pr.get("id") for pr in provs if pr.get("id")), None)
    if pid:
        print(f"[fhir provider] none set in .env — borrowing first configured provider {pid}")
        return pid
    sys.exit("agent.create requires a FHIR provider, but none is set and none could be "
             "discovered. Set PHENOML_FHIR_PROVIDER_ID in .env (see .env.example).")


def cleanup(client, created: dict):
    """Delete the agents/prompts a script created. Safe to call from a `finally` so a crash
    mid-pipeline never orphans them. `created` is {"agents": [...], "prompts": [...]}."""
    banner("CLEANUP  delete created agents/prompts")
    for aid in created.get("agents", []):
        try:
            client.agent.delete(aid); print("deleted agent", aid)
        except Exception as e:
            print("skip agent", aid, type(e).__name__)
    for pid in created.get("prompts", []):
        try:
            client.agent.prompts.delete(pid); print("deleted prompt", pid)
        except Exception as e:
            print("skip prompt", pid, type(e).__name__)


# ---------- artifact store (passes data between step scripts) -------------
# The step scripts run as separate processes, so step N reads what step N-1 wrote here. The
# all-in-one run_demo.py never touches disk — it passes the same dict between steps in memory.
def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state: dict):
    STATE_DIR.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))
    print(f"[state] saved {STATE_FILE.relative_to(HERE)} ({', '.join(state) or 'empty'})")


def fresh_requested() -> bool:
    """True if --fresh / --reset was passed on the command line."""
    return any(a in ("--fresh", "--reset") for a in sys.argv[1:])


def reset_state():
    """Delete the on-disk artifact cache so the next run starts from a clean extraction.
    Anchored to STATE_FILE (the script dir), so it works regardless of the caller's cwd —
    which is the whole point: `rm -rf .state` only deletes it from inside mopa-breast-pa/."""
    if STATE_FILE.exists():
        STATE_FILE.unlink()
        print(f"[state] --fresh: deleted {STATE_FILE.relative_to(HERE)}")
    else:
        print(f"[state] --fresh: no cache at {STATE_FILE.relative_to(HERE)} (already clean)")


def require(state: dict, *keys: str):
    """Exit with a friendly pointer if a later step is run before its inputs exist on disk."""
    missing = [k for k in keys if k not in state]
    if missing:
        sys.exit(f"missing {missing} in {STATE_FILE.relative_to(HERE)} — run earlier steps first, "
                 "starting with `python step1_intake.py`.")
