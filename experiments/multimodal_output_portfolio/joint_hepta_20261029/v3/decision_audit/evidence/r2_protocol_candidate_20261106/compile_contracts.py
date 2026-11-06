"""Compile a reviewable study manifest; this program never dispatches work."""

import argparse
import hashlib
import json
from pathlib import Path

from r2_capture import digest, require


ROOT = Path(__file__).resolve().parent
CONTRACT_FILES = {"baselines": "BASELINE_CONTRACT.json", "data": "DATA_CONTRACT.json",
                  "rubric": "UTILITY_AND_POWER.json", "budget": "BUDGET_CONTRACT.json"}


def verify_fixed_schedule(actions):
    require(actions and len(actions) <= 10, "schedule horizon")
    text = image = last_image = False
    for index, action in enumerate(actions):
        require(action in ("perceive", "text", "draft", "revise", "refine", "verify", "stop"), "unknown schedule action")
        if action in ("perceive", "revise"):
            text = image = False
        elif action == "text":
            text = True
        elif action in ("draft", "refine"):
            require(action != "refine" or last_image, "refine before a real draft")
            image = last_image = True
        elif action == "verify":
            require(text and image, "verify requires current pair")
        else:
            require(index == len(actions)-1, "work after STOP")
    require(actions[-1] == "stop", "fixed schedule cannot silently exhaust horizon")


def compile_plan(protocol, contracts):
    require(digest(protocol["inherited"]) == protocol["inherited_frozen_fields_sha256"], "inherited fields changed")
    for key, contract in contracts.items():
        require(digest(contract) == protocol["addendum_contracts"][key], f"changed {key} contract")
    baselines = contracts["baselines"]
    schedules = baselines["fixed"]["candidate_schedules"]
    require([digest(x) for x in schedules] == baselines["fixed"]["candidate_ids"], "schedule identities")
    for actions in schedules:
        verify_fixed_schedule(actions)
    rows = []
    for fit_seed in protocol["analysis"]["fit_seeds"]:
        for arm, intervention in protocol["inherited"]["arms"].items():
            rows.append({"fit_seed": fit_seed, "arm": arm, **intervention,
                         "source_sha": protocol["source_sha"], "execution_state": "NOT_RUN",
                         "base_generator_manifest": protocol["inherited"]["incumbent_generator_pins"],
                         "controller_initialization_pair_id": f"fit-{fit_seed}-10-11" if arm in ("10", "11") else None,
                         "training_callable": None, "checkpoint_sha256": None,
                         "required_receipts": ["before/after named parameter-group hashes", "actual train/failure/no-training outcome", "all search and rejected candidates", "complete resource cost", "new-process exact checkpoint reload"]})
    return {"schema": "hepta.r2.compiled-plan.v1", "protocol_sha256": digest(protocol),
            "status": "PLAN_ONLY_NOT_RUN", "fit_arm_rows": rows,
            "fixed_schedules_legal_under_original_run_state": len(schedules),
            "methods": baselines["method_ids"], "fixed_alias_is_not_double_charged": True,
            "confirmation_episode_counts": contracts["budget"]["episode_counts_by_N"],
            "missing_executable_training_and_baseline_bindings": True,
            "no_update": True, "dispatch_allowed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    protocol = json.loads((ROOT / "PROTOCOL.json").read_bytes())
    contracts = {key: json.loads((ROOT / name).read_bytes()) for key, name in CONTRACT_FILES.items()}
    report = compile_plan(protocol, contracts)
    with Path(args.output).open("x") as out:
        json.dump(report, out, indent=2, allow_nan=False)
        out.write("\n")
    print(json.dumps({"output": args.output, "sha256": hashlib.sha256(Path(args.output).read_bytes()).hexdigest(),
                      "fit_arm_rows": len(report["fit_arm_rows"]), "dispatch_allowed": False}))


if __name__ == "__main__":
    main()
