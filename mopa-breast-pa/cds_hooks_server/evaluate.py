#!/usr/bin/env python3
"""CDS Hooks judgment for the MOPA oncology-crd service (framework-free).

This module owns the actual decision logic so BOTH the FastAPI shim (main.py) and the in-process
simulated path (step2/step3 when CDS_HOOKS_URL is unset) call the exact same code. It:

  1. resolves the breast-cancer Library (the flattened DataRequirement[]) and the order's resources,
  2. checks each DataRequirement against what is on file,
  3. if a required element is missing or unresolved (HER2 for Jane), returns a Response B DTR card
     and does NOT call the agent (you cannot adjudicate medical acceptance without the data),
  4. otherwise derives the regimen's NCCN-category evidence fact from the resolved receptor status
     and asks the OncoHealth UM-9 agent to apply the rule, returning Response A (pre-approved card +
     Coverage systemAction) on APPROVED or a critical card on DENIED.

PhenoML's role is Layer 1 (provider-side PA readiness). The UM-9 agent stands in for the Layer 2
payer CDS judgment; a future CQL -> natural language -> Workflow path is deferred (see the README).
"""
import json
import sys
from pathlib import Path

# common.py lives one dir up; importing it is side-effect free (it only defines functions).
HERE = Path(__file__).resolve().parent
DEMO_ROOT = HERE.parent
sys.path.insert(0, str(DEMO_ROOT))
from common import as_dict, parse_json, retry  # noqa: E402

LIBRARY_PATH = DEMO_ROOT / "mopa_requirements.json"
POLICY_PATH = DEMO_ROOT / "policy_um9_oncohealth.md"
DTR_LAUNCH_URL = "https://mopa.demo/dtr/launch"  # demo placeholder for the SMART DTR app

# The agent system-prompt preamble, mirroring the TMS reviewer preamble. The policy markdown is
# appended verbatim (UM-9 is OncoHealth's own text and may be loaded as the prompt).
AGENT_PREAMBLE = (
    "You are an OncoHealth utilization-management reviewer for medical oncology. Apply the following "
    "UM-9 review criteria EXACTLY as written. You will be given the ordered regimen and a structured "
    "evidence fact stating its NCCN category for the patient's indication; use that category to apply "
    "the medical-acceptance rule. Cite the UM-9 criteria you rely on, never invent criteria, and "
    "never reproduce NCCN guideline text.\n\n")

# The "structured evidence fact" the demo supplies in place of an NCCN-category lookup: for the
# ordered regimen + resolved indication, what NCCN category applies. TH is Category 1 for adjuvant
# HER2-positive breast cancer; it is NOT a listed Category 1-2A use for HER2-negative disease.
MEDICAL_EVIDENCE = {
    ("TH", "adjuvant HER2+ breast"): "1",
}

# Per-DataRequirement discriminator keyword keyed by the requirement's identifying code, so an ER
# Observation is never mistaken for the HER2 requirement (both share "receptor"/"breast cancer
# specimen" wording). Code match is primary; this keyword is the fuzzy fallback.
DISCRIMINATOR = {
    "254837009": "breast",
    "21908-9": "stage",
    "85337-4": "estrogen",
    "85339-0": "progesterone",
    "85319-2": "her2",
    "89247-1": "ecog",
}
# Value text that means a receptor result is NOT yet definitive (so HER2 IHC 2+ / ISH pending pends
# the request instead of approving it).
INDETERMINATE = ("equivocal", "pending", "indeterminate", "unknown", "awaiting", "2+", "borderline")


def load_library() -> dict:
    return json.loads(LIBRARY_PATH.read_text())


def build_agent_once(client, provider, created: dict):
    """Create the OncoHealth UM-9 agent ONCE (the FastAPI app does this at startup, not per request;
    the in-process path does it once per run). Appends the agent/prompt ids to `created` for cleanup.
    Returns the agent id."""
    policy_text = POLICY_PATH.read_text()
    prompt = client.agent.prompts.create(
        name="oncohealth-um9",
        content=AGENT_PREAMBLE + policy_text,
        description="OncoHealth UM-9 Chemotherapy Review Criteria as an agent.")
    created["prompts"].append(prompt.data.id)
    agent = client.agent.create(name="OncoHealth UM-9 Agent", prompts=[prompt.data.id],
                                provider=provider, tags=["oncohealth", "um-9", "oncology"])
    created["agents"].append(agent.data.id)
    return agent.data.id


# ---------- resource + requirement helpers --------------------------------
def collect_resources(request: dict) -> list:
    """Flatten every FHIR resource the request carries: each prefetch value (a single resource or a
    Bundle) plus the draftOrders Bundle in context."""
    out = []

    def add(v):
        if isinstance(v, dict) and v.get("resourceType"):
            if v["resourceType"] == "Bundle":
                for e in v.get("entry", []) or []:
                    add(e.get("resource"))
            else:
                out.append(v)

    for v in (request.get("prefetch") or {}).values():
        add(v)
    add(((request.get("context") or {}).get("draftOrders")) or {})
    return out


def _codings(resource: dict) -> list:
    return ((resource.get("code") or {}).get("coding")) or []


def _searchable_text(resource: dict) -> str:
    parts = [(resource.get("code") or {}).get("text", "")]
    parts += [c.get("display", "") for c in _codings(resource)]
    for cat in resource.get("category") or []:
        parts.append((cat or {}).get("text", ""))
        parts += [c.get("display", "") for c in (cat or {}).get("coding", [])]
    return " ".join(p for p in parts if p).lower()


def _value_text(resource: dict) -> str:
    vcc = resource.get("valueCodeableConcept") or {}
    parts = [vcc.get("text", "")] + [c.get("display", "") for c in vcc.get("coding", [])]
    if resource.get("valueString"):
        parts.append(resource["valueString"])
    vq = resource.get("valueQuantity") or {}
    if vq:
        parts.append(f"{vq.get('value', '')} {vq.get('unit', '')}")
    parts.append(_searchable_text(resource))  # fall back to the code text if no explicit value
    return " ".join(str(p) for p in parts if p).strip().lower()


def _matches(resource: dict, rtype: str, codes: list, keyword: str) -> bool:
    if resource.get("resourceType") != rtype:
        return False
    if not codes and not keyword:
        return True  # presence-only requirement (e.g. the RequestGroup): the right type is enough
    want = {(c.get("system"), c.get("code")) for c in codes}
    if want and any((c.get("system"), c.get("code")) in want for c in _codings(resource)):
        return True
    return bool(keyword) and keyword in _searchable_text(resource)


def check_data_requirements(resources: list, library: dict) -> dict:
    """For each DataRequirement, decide whether a satisfying resource is on file. Observations also
    need a DEFINITIVE value (HER2 IHC 2+ / pending does not count), which is what makes Jane's HER2
    come back missing. Returns {"satisfied": [...], "missing": [...]} with friendly labels."""
    satisfied, missing = [], []
    for dr in library.get("dataRequirement", []):
        rtype = dr["type"]
        codes = [c for cf in dr.get("codeFilter", []) for c in cf.get("code", [])]
        keyword = next((DISCRIMINATOR[c["code"]] for c in codes if c.get("code") in DISCRIMINATOR), "")
        label = (codes[0].get("display") if codes else None) or rtype
        candidates = [r for r in resources if _matches(r, rtype, codes, keyword)]
        if rtype == "Observation":
            ok = any(v and not any(w in v for w in INDETERMINATE)
                     for v in (_value_text(r) for r in candidates))
        else:
            ok = bool(candidates)
        (satisfied if ok else missing).append({"label": label, "type": rtype,
                                               "code": (codes[0].get("code") if codes else None)})
    return {"satisfied": satisfied, "missing": missing}


# ---------- card builders -------------------------------------------------
def _source():
    return {"label": "OncoHealth UM-9 Chemotherapy Review Criteria",
            "url": "https://oncohealth.us/criteria/"}


def _dtr_card(missing: list) -> dict:
    labels = ", ".join(m["label"] for m in missing) or "required documentation"
    return {
        "summary": "Additional information required before prior authorization",
        "indicator": "warning",
        "detail": ("The ordered regimen TH (paclitaxel + trastuzumab) cannot be evaluated for "
                   f"medical acceptance until these data elements are resolved: {labels}. HER2 "
                   "receptor status determines whether TH is the accepted adjuvant regimen."),
        "source": _source(),
        "links": [{
            "label": "Complete the missing oncology documentation (DTR)",
            "url": DTR_LAUNCH_URL,
            "type": "smart",
            "appContext": json.dumps({"missing": [m["label"] for m in missing],
                                      "questionnaire": "mopa-her2-status"}),
            "autolaunchable": False,
        }],
    }


def _coverage_systemaction(patient_ref: str) -> dict:
    return {"type": "update", "description": "Pre-approval recorded for the regimen.",
            "resource": {
                "resourceType": "Coverage", "status": "active",
                "beneficiary": {"reference": patient_ref},
                "extension": [{"url": "https://mopa.demo/StructureDefinition/auth-status",
                               "valueString": "pre-approved"}]}}


# ---------- receptor / evidence helpers -----------------------------------
def _her2_status(resources: list) -> str:
    """positive / negative / unresolved, read from a HER2 Observation in the resources."""
    for r in resources:
        if r.get("resourceType") == "Observation" and _matches(r, "Observation", [], "her2"):
            v = _value_text(r)
            if any(w in v for w in INDETERMINATE):
                return "unresolved"
            # Check negative first so "not amplified" is not caught by the "amplified" test below.
            if "negative" in v or "not amplified" in v:
                return "negative"
            if "positive" in v or "3+" in v or "amplified" in v:
                return "positive"
    return "unresolved"


def _evidence_fact(resources: list) -> dict:
    her2 = _her2_status(resources)
    indication = f"adjuvant {'HER2+' if her2 == 'positive' else 'HER2-negative'} breast"
    category = MEDICAL_EVIDENCE.get(("TH", indication))
    return {"regimen": "TH", "indication": indication,
            "nccn_category": category or "not a listed Category 1-2A use"}


def _patient_ref(request: dict, resources: list) -> str:
    pid = (request.get("context") or {}).get("patientId")
    if pid:
        return f"Patient/{pid}"
    pat = next((r for r in resources if r.get("resourceType") == "Patient"), None)
    return f"Patient/{pat['id']}" if pat and pat.get("id") else "Patient/example"


# ---------- the service ---------------------------------------------------
def evaluate(client, agent_id, request: dict, library: dict) -> dict:
    """Return a CDS Hooks response {"cards": [...], "systemActions": [...]}."""
    resources = collect_resources(request)
    gap = check_data_requirements(resources, library)

    # Response B: a required element is missing/unresolved -> DTR card, no agent call.
    if gap["missing"]:
        return {"cards": [_dtr_card(gap["missing"])], "systemActions": []}

    # All data present: derive the NCCN-category evidence fact and ask the UM-9 agent to apply it.
    fact = _evidence_fact(resources)
    her2 = _her2_status(resources)
    message = (
        "Adjudicate this oncology regimen prior authorization under UM-9. Respond ONLY as JSON: "
        '{"decision":"APPROVED"|"DENIED","rationale":"...","policy_citations":[...],'
        '"conditions_or_limits":"..."}\n\n'
        "Ordered regimen: TH (paclitaxel + trastuzumab), adjuvant intent, breast, first line.\n"
        f"Resolved receptor status: ER negative, PR negative, HER2 {her2}.\n"
        "Structured NCCN-category evidence fact:\n" + json.dumps(fact, indent=2))
    resp = retry(client.agent.chat.send, label="um9.adjudicate",
                 agent_id=agent_id, message=message, enhanced_reasoning=True)
    decision = parse_json(resp.response)
    verdict = str(decision.get("decision", "")).upper()
    patient_ref = _patient_ref(request, resources)

    if "APPROV" in verdict and "NOT" not in verdict:
        # Response A: medically accepted (NCCN Category 1) -> pre-approved card + Coverage.
        card = {
            "summary": "Prior authorization not required: regimen is medically accepted",
            "indicator": "info",
            "detail": ("TH (paclitaxel + trastuzumab) for adjuvant HER2-positive breast cancer is "
                       "NCCN Category 1. Under OncoHealth UM-9 a Category 1 regimen is medically "
                       "accepted. " + str(decision.get("rationale", ""))),
            "source": _source(),
        }
        return {"cards": [card], "systemActions": [_coverage_systemaction(patient_ref)]}

    # DENIED: not a medically accepted use for the resolved indication.
    card = {
        "summary": "Prior authorization denied: regimen not medically accepted",
        "indicator": "critical",
        "detail": (f"TH is not medically accepted for {fact['indication']} (NCCN category: "
                   f"{fact['nccn_category']}). " + str(decision.get("rationale", ""))),
        "source": _source(),
    }
    if decision.get("policy_citations"):
        card["detail"] += "\n\nCitations: " + "; ".join(map(str, decision["policy_citations"]))
    return {"cards": [card], "systemActions": []}
