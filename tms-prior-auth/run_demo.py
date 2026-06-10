#!/usr/bin/env python3
"""End-to-end runner for the TMS prior-auth demo (PhenoML SDK v15).

Runs all three phases in one process. To follow along one phase at a time instead, run the step
scripts in order:  step1_intake.py -> step2_evaluate.py -> step3_adjudicate.py.

Reads credentials from tms-prior-auth/.env (preferred) or the repo-root ../.env.
Auth: PHENOML_CLIENT_ID + PHENOML_CLIENT_SECRET (OAuth client credentials, v15-native).

Run:  .venv/bin/python run_demo.py
"""
import step1_intake, step2_evaluate, step3_adjudicate
from common import load_env, make_client, resolve_provider, cleanup, reset_state, fresh_requested


def main():
    env = load_env()
    client = make_client(env)
    provider = resolve_provider(client, env)

    # One process: state is passed step->step in memory (run fresh every time — the standalone step
    # scripts persist it to .state/ instead). `created` accumulates every agent/prompt across the
    # three phases for a single cleanup at the end, even if a phase raises.
    if fresh_requested():
        reset_state()
    state, created = {}, {"agents": [], "prompts": []}
    try:
        step1_intake.run(client, env, provider, state, created)
        step2_evaluate.run(client, env, provider, state, created)
        step3_adjudicate.run(client, env, provider, state, created)
    finally:
        cleanup(client, created)

    print("\nDONE.")


if __name__ == "__main__":
    main()
