"""Reopen emitted media, replay original neuron, and independently score returns."""
import argparse
import json
from pathlib import Path

import numpy as np

from ...risk_feedback.media import file_sha, readback
from ...risk_feedback.model import digest
from .model import Native, decide


def audit(output):
    registration = json.loads((output / "FROZEN_REGISTRATION.json").read_text())
    result = json.loads((output / "RESULT.json").read_text())
    task = registration["inherited_task"]
    rows = json.loads((output / "ROWS.json").read_text())
    weights = np.array(json.loads((output / "HEAD_PARAMETERS.json").read_text()))
    build = json.loads((output / "BUILD_RECEIPT.json").read_text())
    binary = output / "feedback_probe"
    if file_sha(binary) != build["binary_sha256"]:
        raise ValueError("Archived original native executable changed")
    binary.chmod(binary.stat().st_mode | 0o100)
    native = Native(binary)
    replayed, reopened, scores = 0, 0, 0
    try:
        for row in rows:
            directory = output / "evaluation" / f"case-{row['case']:04d}" / row["arm"]
            for phase, expected in (("first", row["first_observation"]), ("repair", row["final_observation"])):
                if phase == "repair" and row["continuation"] != "repair":
                    continue
                paths = {key: str(directory / phase / filename) for key, filename in
                    (("text", "report.txt"), ("image", "image.png"), ("audio", "audio.wav"), ("video", "video.avi"))}
                if readback(paths) != expected:
                    raise ValueError("Persisted media no longer matches committed readback")
                reopened += 4
            if row["observed_feedback"] != task["numeric_feedback_by_fault"][row["first_observation"]["fault_class"]]:
                raise ValueError("Scalar did not follow actual readback")
            first_receipt = json.loads((directory / "FIRST_DELIVERY.json").read_text())
            if first_receipt["first_observation"] != row["first_observation"]:
                raise ValueError("Feedback chronology receipt mismatch")
            saved_native = json.loads((directory / "NATIVE_STATE.json").read_text())
            if saved_native != row["native"]:
                raise ValueError("Native receipt mismatch")
            request = saved_native["request"]
            replay = native.tick_pair(request["case"], request["feedback_q24"] / (1 << 24),
                request["readback_digest"], reset=request["reset_before_readout"])
            for actual, expected in zip(replay["ticks"], saved_native["ticks"]):
                if {k: v for k, v in actual.items() if k != "native_ns"} != {k: v for k, v in expected.items() if k != "native_ns"}:
                    raise ValueError("Original native replay diverged")
            replayed += 2
            decision = json.loads((directory / "DECISION.json").read_text())
            predicted, logit = decide(saved_native, weights)
            if row["arm"] != "history" and predicted != row["continuation"]:
                raise ValueError("Continuation bypassed declared original-neuron features")
            if logit != row["native_feature_logit"] or decision["continuation"] != row["continuation"]:
                raise ValueError("Committed decision changed")
            final_code = row["final_observation"]["codes"]["text"]
            first_fault, final_fault = row["first_observation"]["fault_class"], row["final_observation"]["fault_class"]
            expected = (task["semantic_utility_action_by_target"][final_code][row["private_target"]]
                - task["initial_action_cost"][row["initial_action"]] - task["channel_cost_by_fault"][first_fault]
                - task["irreversible_first_delivery_damage"][first_fault]
                - task["repair_cost"] * (row["continuation"] == "repair")
                - task["terminal_mismatch_penalty"][final_fault])
            if abs(expected - row["net_return"]) > 1e-12:
                raise ValueError("Private payoff differs from independent terminal calculation")
            if file_sha(directory / "EPISODE.json") != row["episode_sha256"]:
                raise ValueError("Private score did not bind final episode")
            scores += 1
    finally:
        native.close()
    shuffle = json.loads((output / "SHUFFLE_COMMITTED.json").read_text())
    actual = [row["observed_feedback"] for row in rows if row["arm"] == "numeric"]
    shuffled = [row["effective_scalar"] for row in rows if row["arm"] == "shuffled"]
    if actual != shuffle["actual_readback_scalars"] or shuffled != [actual[index] for index in shuffle["permutation"]]:
        raise ValueError("Actual shuffled marginal or donor identity mismatch")
    if file_sha(output / "ROWS.json") != result["rows_sha256"]:
        raise ValueError("Result rows changed")
    report = {"status": "passed", "actual_media_files_reopened": reopened,
        "original_native_ticks_independently_replayed": replayed, "private_payoffs_recomputed": scores,
        "rows_sha256": result["rows_sha256"], "result_sha256": file_sha(output / "RESULT.json"),
        "original_sparse_sha256": build["original_sparse_sha256"],
        "no_model_or_protocol_changes": True, "native_owner_integration": False,
        "scope": "Recorded file integrity, exact original-kernel replay and declared utility accounting; no host isolation claim"}
    with (output / "INTEGRITY_AUDIT.json").open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    audit(parser.parse_args().output)
