#!/usr/bin/env python3
"""End-to-end runner for the MOPA breast-cancer prior-auth demo (PhenoML SDK v15).

Runs all four phases in one process. To follow along one phase at a time instead, run the step
scripts in order:  step1_intake.py -> step1_5_readiness.py -> step2_cdshooks.py -> step3_ordersign.py.

Reads credentials from mopa-breast-pa/.env (preferred) or the repo-root ../.env.
Auth: PHENOML_CLIENT_ID + PHENOML_CLIENT_SECRET (OAuth client credentials, v15-native).
By default the CDS Hooks exchange runs simulated (in-process); set CDS_HOOKS_URL to use a live shim.

Run:  .venv/bin/python run_demo.py
"""
import step1_intake, step1_5_readiness, step2_cdshooks, step3_ordersign
from common import load_env, make_client, resolve_provider, cleanup, reset_state, fresh_requested


def main():
    env = load_env()
    client = make_client(env)
    provider = resolve_provider(client, env)

    # One process: state is passed step->step in memory (run fresh every time - the standalone step
    # scripts persist it to .state/ instead). `created` accumulates every agent/prompt across the
    # four phases (the readiness agent and the UM-9 agent) for a single cleanup at the end, even if
    # a phase raises.
    if fresh_requested():
        reset_state()
    state, created = {}, {"agents": [], "prompts": []}
    try:
        step1_intake.run(client, env, provider, state, created)
        step1_5_readiness.run(client, env, provider, state, created)
        step2_cdshooks.run(client, env, provider, state, created)
        step3_ordersign.run(client, env, provider, state, created)
    finally:
        cleanup(client, created)

    print("\nDONE.")


if __name__ == "__main__":
    main()
