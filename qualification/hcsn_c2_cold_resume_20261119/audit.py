"""Review exact archived states independently; perform no forward or optimizer calls."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import random
from zipfile import ZipFile

for variable in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[variable] = "1"

import torch


HERE = Path(__file__).resolve().parent
OLD_ARCHIVE_SHA = "7f2001bcc178e78c5f8de120007110e93534ba5a19e490fff307065e5466d2c3"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def exact(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, torch.Tensor):
        return (left.dtype == right.dtype and left.shape == right.shape
                and left.contiguous().numpy().tobytes() == right.contiguous().numpy().tobytes())
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(exact(value, right[key]) for key, value in left.items())
    if isinstance(left, (list, tuple)):
        return len(left) == len(right) and all(exact(a, b) for a, b in zip(left, right))
    return left == right


def main(archive, receipt, old_archive):
    archive_bytes = archive.read_bytes()
    binding = json.loads(receipt.read_text())
    require(len(archive_bytes) == binding["bytes"]
            and hashlib.sha256(archive_bytes).hexdigest() == binding["sha256"], "new archive identity")
    require(hashlib.sha256(old_archive.read_bytes()).hexdigest() == OLD_ARCHIVE_SHA,
            "unaltered original journal archive")
    with ZipFile(io.BytesIO(archive_bytes)) as source, ZipFile(old_archive) as old:
        manifest = json.loads(source.read("MANIFEST.json"))
        require(len(source.namelist()) == len(set(source.namelist())), "duplicate ZIP members")
        require(set(source.namelist()) == set(manifest["members"]) | {"MANIFEST.json"},
                "complete member manifest")
        for name, expected in manifest["members"].items():
            data = source.read(name)
            require(len(data) == expected["bytes"] and hashlib.sha256(data).hexdigest() == expected["sha256"],
                    "exact archive member " + name)
        request = json.loads(source.read("source/REQUEST.json"))
        freeze = json.loads(source.read("source/FREEZE.json"))
        for name, expected in freeze["files"].items():
            require(hashlib.sha256(source.read("source/" + name)).hexdigest() == expected,
                    "frozen executed source " + name)
        terminal = json.loads(source.read("run/TERMINAL.json"))
        require(terminal["original_controller_terminal"] == "UNKNOWN"
                and terminal["full_six_fit_replay"] is False, "original unresolved scope")
        reviews = []
        states_by_fit = {}
        for fit in request["fits"]:
            original_name = "original/" + fit["name"] + "/CHECKPOINT.pt"
            require(hashlib.sha256(source.read(original_name)).hexdigest() == fit["checkpoint_sha256"],
                    "original input checkpoint")
            original = torch.load(io.BytesIO(source.read(original_name)), weights_only=True, map_location="cpu")
            states_by_fit[fit["name"]] = []
            old_rows = []
            for line in old.read("fits/" + fit["name"] + "/events.jsonl").splitlines():
                try:
                    old_rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass  # Existing truncated tail remains preserved in the original archive.
            target = next(row for row in old_rows if row.get("kind") == "optimizer_completed"
                          and row["number"] == original["main_updates"] + 1)
            for replica in (1, 2):
                name = fit["name"] + "-replica" + str(replica)
                prefix = "run/" + name + "/"
                if prefix + "RESULT.json" not in source.namelist():
                    continue
                result = json.loads(source.read(prefix + "RESULT.json"))
                events = [json.loads(line) for line in source.read(prefix + "events.jsonl").splitlines()]
                require(sum(row["kind"] == "optimizer_started" for row in events) == 1
                        and sum(row["kind"] == "optimizer_completed" for row in events) == 1
                        and not any(row["kind"] == "failed" for row in events), "completed update journal")
                states = []
                for file_name, result_key in (("RESTORED.pt", "restored_checkpoint"),
                                              ("AFTER_UPDATE.pt", "after_update_checkpoint")):
                    data = source.read(prefix + file_name)
                    require(hashlib.sha256(data).hexdigest() == result[result_key]["sha256"],
                            "reported checkpoint bytes")
                    states.append(torch.load(io.BytesIO(data), weights_only=True, map_location="cpu"))
                restored, after = states
                require(exact(original, restored), "entire original/restored model, optimizer and RNG")
                require(after.keys() == original.keys() | {"continuation_cursor"}, "explicit after-state schema")
                require(after["main_updates"] == original["main_updates"] + 1
                        and after["epochs_completed"] == original["epochs_completed"], "mid-epoch update count")
                cursor = after["continuation_cursor"]
                require(cursor["current_epoch"] == original["epochs_completed"] + 1
                        and cursor["complete_epoch"] is False and cursor["completed_effective_batches"] == 1,
                        "mid-epoch cursor semantics")
                generator = random.Random()
                generator.setstate(original["order_rng"])
                indices = list(range(len(cursor["episode_indices"])))
                generator.shuffle(indices)
                require(indices == cursor["episode_indices"] and exact(generator.getstate(), after["order_rng"]),
                        "restored order RNG progression")
                require(cursor["next_episode_offset"] == len(result["episode_ids"])
                        and cursor["episode_ids"][:cursor["next_episode_offset"]] == result["episode_ids"],
                        "continuation batch cursor")
                changed = result["trainable_parameter_max_abs_changes"]
                for key, value in restored["model"].items():
                    new = after["model"][key]
                    require(bool(torch.isfinite(new).all()), "finite saved model tensor")
                    if key in changed:
                        require(float((new - value).abs().max()) == changed[key], "actual parameter delta")
                    else:
                        require(exact(value, new), "saved frozen parameters and buffers")
                require(any(value > 0 for value in changed.values()), "actual nonzero parameter change")
                require(exact(restored["optimizer"]["param_groups"], after["optimizer"]["param_groups"]),
                        "retained optimizer groups")
                for key, value in restored["optimizer"]["state"].items():
                    new = after["optimizer"]["state"][key]
                    require(float(new["step"]) == float(value["step"]) + 1, "actual saved AdamW step")
                    require(all(bool(torch.isfinite(tensor).all()) for tensor in new.values()
                                if isinstance(tensor, torch.Tensor)), "finite saved AdamW tensors")
                differences = {key: abs(value - target[key]) for key, value in result["metrics"].items()}
                require(differences == result["original_metric_absolute_differences"],
                        "independent original-journal metric comparison")
                cost = json.loads(source.read("run/" + name + ".COST.json"))
                require(cost["returncode"] == 0 and cost["timed_out"] is False
                        and cost["wall_seconds"] <= request["budget"]["child_timeout_seconds"]
                        and cost["peak_rss_bytes"] <= request["budget"]["child_peak_rss_stop_bytes"],
                        "recorded per-child resource budget")
                reviews.append({"name": name, "optimizer_completed_events": 1,
                    "micro_forwards_reported": result["counts"]["micro_forwards_started"],
                    "full_original_checkpoint_bytes_equal_after_deserialization": True,
                    "original_metric_absolute_differences": differences, "cost": cost})
                states_by_fit[fit["name"]].append((after, result))
        repeats = []
        for name, values in states_by_fit.items():
            if len(values) == 2:
                require(exact(values[0][0], values[1][0]), "independent actual cold-repeat state equality")
                for key in ("gradient_before_clip_sha256", "gradient_after_clip_sha256", "metrics"):
                    require(values[0][1][key] == values[1][1][key], "instrumented cold-repeat " + key)
                repeats.append({"fit": name, "all_saved_state_tensor_bytes_equal": True,
                                "reported_gradient_hashes_and_metrics_equal": True})
        return {"status": "VERIFIED_BOUNDED_COLD_RESUME" if len(reviews) == 4 and len(repeats) == 2
                else "INCOMPLETE_DIAGNOSTIC", "archive_sha256": binding["sha256"],
            "verified_member_count": len(manifest["members"]), "reviews": reviews, "cold_repeats": repeats,
            "optimizer_completed_events": sum(row["optimizer_completed_events"] for row in reviews),
            "independent_review_forward_calls": 0, "independent_review_optimizer_calls": 0,
            "gradient_evidence_limit": "Hashes of actual backward-produced gradients are instrumented by the executed source; this reader compares those hashes but does not regenerate gradients.",
            "original_controller_terminal": "UNKNOWN", "independent_complete_training_replays": 0,
            "full_six_fit_replay": False, "original_runtime_exact_replay": False, "scientific_admission": "HOLD"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, default=HERE / "evidence/c2-cold-resume-exact-artifact.zip")
    parser.add_argument("--receipt", type=Path, default=HERE / "evidence/ARTIFACT.json")
    parser.add_argument("--old-archive", type=Path,
                        default=HERE.parent / "hcsn_differentiable/evidence/c2-readonly-20261119/original-c2-journals-and-results.zip")
    args = parser.parse_args()
    print(json.dumps(main(args.archive, args.receipt, args.old_archive), indent=2, sort_keys=True))
