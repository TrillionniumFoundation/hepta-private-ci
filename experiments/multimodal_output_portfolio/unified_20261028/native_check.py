"""Run the original owner and real strong-baseline decoder in matched arms.

This is an integration/overhead comparison, not fresh semantic qualification.
Readback bytes, permissions, recurrent state and full physical costs are tested.
The parent experiment performs separate post-codec quality scoring.
"""

import argparse
import json
from pathlib import Path

import torch

from ..closure_v2_20261027.control.adapter import Generator, scalar_feedback
from ..closure_v2_20261027.control.tasks import make_tasks
from ..continuation_20261027.control.client import sha
from ..v6.data import load_corpus
from .control import NativeController
from .profile import NduProfile, digest


def run(*, binary, checkpoint, corpus, profile, output, cases=8, offset=800):
    torch.set_num_threads(1)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    package = Path(__file__).resolve().parent
    development = package.parent / "closure_v2_20261027/control/evidence/development-001"
    frozen = json.loads((development / "FROZEN.json").read_text())
    if sha(binary) != frozen["binary_sha256"] or sha(checkpoint) != frozen["generator_sha256"]:
        raise ValueError("Actual owner/strong baseline differs from the frozen #4070 identity")
    heads = json.loads((development / "READOUT_FIT.json").read_text())
    source = load_corpus(corpus)
    tasks = make_tasks(source, "test", cases, offset=offset)
    generator = Generator(checkpoint)
    records, comparisons = [], []
    actors = {"native_full": None, "native_fast": None,
              "history_fast": lambda context: "swap" if
              heads["history_moment_difference"][str(context["feedback"])] >= 0 else "keep"}
    controllers = {arm: NativeController(binary=binary, readout=development / "MODEL.json",
                    calibration=development / "ENCODER_DOMAIN_PROOF.json", generator_checkpoint=checkpoint,
                    profile=profile, policy_sha256=digest({"arm": arm, "head_sha256": sha(development / "READOUT_FIT.json"),
                        "source_sha256": sha(__file__)}),
                    implementation_paths=(__file__, package.parent / "closure_v2_20261027/control/adapter.py"))
                   for arm in actors}
    for task in tasks:
        def dispatch(action, public_state, directory):
            if public_state != {"source_ids": task["source_ids"], "condition": task["condition"]}:
                raise ValueError("Public task binding changed")
            delivered, _ = generator.deliver(task["public"], int(action == "swap"), directory)
            # Only the arrived scalar crosses back to the controller. Hidden
            # target labels are confined to this external feedback evaluator.
            feedback = scalar_feedback(delivered["caption"], task["private"].labels[0].tolist())
            return {"artifact_refs": delivered["paths"], "artifact_sha256": delivered["sha256"],
                    "public_feedback": feedback, "final_state_digest": digest(delivered["model_identity"]),
                    "terminal_kind": "delivered", "generator_calls": 1, "delivery_units": 1,
                    "caption": delivered["caption"], "generator_receipt": delivered}

        matched = {}
        for arm, actor in actors.items():
            case = f"source-{task['index']:03}-{arm}"
            record = controllers[arm].execute(directory=output / case, case=case,
                public_state={"source_ids": task["source_ids"], "condition": task["condition"]},
                dispatch=dispatch, actor=actor, expires=task["expires"], media_budget=task["budget"],
                forecast="full" if arm == "native_full" else "none", recovery="cold")
            record.update({"arm": arm, "source_ids": task["source_ids"], "condition": task["condition"],
                           "expires": task["expires"], "budget": task["budget"]})
            (output / case / "EPISODE.json").write_text(json.dumps(record, sort_keys=True, indent=2) + "\n")
            matched[arm] = record
            records.append(record)
        reference = matched["native_full"]
        agreement = all(record["final"]["artifact_sha256"] == reference["final"]["artifact_sha256"]
                        and record["selected_action"] == reference["selected_action"]
                        and record["executed_action"] == reference["executed_action"]
                        for record in matched.values())
        if not agreement:
            raise ValueError("Matched original native/history arms differ in actual action or delivered bytes")
        comparisons.append({"source_index": task["index"], "same_action_and_final_bytes": agreement})
    summary = {}
    for arm in actors:
        rows = [r for r in records if r["arm"] == arm]
        summary[arm] = {"episodes": len(rows), "kernel_executions": sum(
            r["measurements"]["actual_original_kernel_executions"] for r in rows),
            "mean_cost": sum(r["total_cost"] for r in rows) / len(rows),
            "mean_wall_seconds": sum(r["measurements"]["wall_seconds"] for r in rows) / len(rows),
            "mean_actor_nanoseconds": sum(r["measurements"]["actor_nanoseconds"] for r in rows) / len(rows),
            "generator_calls": sum(r["measurements"]["actual_generator_calls"] for r in rows),
            "refused_swaps": sum(r["continuation_kind"] == "refused" for r in rows),
            "actual_swaps": sum(r["executed_action"] == "swap" for r in rows)}
    result = {"schema": "hepta.ndu.native-integration-comparison.v1", "profile_sha256": profile.digest,
              "binary_sha256": sha(binary), "generator_sha256": sha(checkpoint),
              "cases": cases, "source_pair_offset": offset, "arms": summary,
              "comparisons": comparisons, "all_final_bytes_and_actions_equal": True,
              "forecast_branches_match_actual_continuation": all(r["forecast_matches_actual"] for r in records),
              "all_owner_authority_deny_all": all(r["final_owner_state"]["owner_authority"] == "DENY_ALL"
                                                   for r in records),
              "new_semantic_quality_claim": False, "native_kernel_gradient_claim": False,
              "historical_calibration_unchanged": True, "profile_binding_level": "host event receipt",
              "scope": "actual original owner, cold recovery, PNG/text neural delivery and selected action parity"}
    (output / "SUMMARY.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "checkpoint", "corpus", "profile", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--cases", type=int, default=8)
    parser.add_argument("--offset", type=int, default=800)
    args = parser.parse_args()
    configuration = NduProfile.from_dict(json.loads(args.profile.read_text()))
    print(json.dumps(run(binary=args.binary, checkpoint=args.checkpoint, corpus=args.corpus,
                         profile=configuration, output=args.output, cases=args.cases, offset=args.offset)))
