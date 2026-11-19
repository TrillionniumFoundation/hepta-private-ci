"""Read all archived D tensors and receipts; never construct or run a model."""

import hashlib
import io
import json
from pathlib import Path
import resource
import sys
import time
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
STAGES = ("hcsn_c2_current_D_replay_20261119", "hcsn_c2_D_path_reconciliation_20261119",
          "hcsn_c2_D_configuration_reconciliation_20261119")
sys.path.insert(0, str(ROOT / STAGES[0]))
from audit_io import require
from independent_metrics import compare_metrics, metrics


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def run():
    started, cpu = time.monotonic(), time.process_time()
    import numpy as np
    import torch
    request = json.loads((ROOT / STAGES[0] / "REQUEST.json").read_bytes())
    roster = {r["name"]: r for r in request["fits"]}
    plan = json.loads((ROOT / STAGES[0] / "DATA_PLAN.json").read_bytes())
    ledger = json.loads((ROOT / "hcsn_c2_d_selection_20261119/evidence/LEDGER.json").read_bytes())
    label_sha = ledger["roster"][0]["D_label_array_sha256"]
    archives, success, failures, cost_totals, chains = [], {}, [], {}, {}
    metadata_wall, metadata_cpu = 0., 0.
    for stage in STAGES:
        native = ROOT / stage / "evidence/native"
        raw = (native / "originals.zip").read_bytes()
        receipt = json.loads((native / "ARCHIVE.json").read_bytes())
        require(sha(raw) == receipt["sha256"] and len(raw) == receipt["bytes"], "archive bytes")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            manifest = json.loads(archive.read("MANIFEST.json"))
            require(len(archive.namelist()) == len(manifest) + 1 == receipt["members"], "archive member roster")
            for name, item in manifest.items():
                data = archive.read(name)
                require(len(data) == item["bytes"] and sha(data) == item["sha256"], "original member changed: " + name)
            summary = json.loads(archive.read("RUN_OUTPUT/SUMMARY.json"))
            require(summary["E_access"] is False and summary["original_controller_terminal"] == "UNKNOWN" and
                    summary["original_full_training_replays"] == "0/6", "scientific scope changed")
            for cost in summary["costs"]:
                if cost["name"] in roster:
                    total = cost_totals.setdefault(cost["name"], {"wall_seconds": 0., "cpu_seconds": 0., "peak_rss_kib": 0, "attempts": []})
                    total["wall_seconds"] += cost["wall_seconds"]
                    total["cpu_seconds"] += cost["cpu_seconds"]
                    total["peak_rss_kib"] = max(total["peak_rss_kib"], cost["peak_rss_kib"])
                    total["attempts"].append({"stage": stage, **cost})
                else:
                    metadata_wall += cost["wall_seconds"]
                    metadata_cpu += cost["cpu_seconds"]
            for name in roster:
                filename = "RUN_OUTPUT/" + name + "/RESULT.json"
                if filename not in manifest:
                    continue
                result = json.loads(archive.read(filename))
                if result["status"] != "PASSED_CURRENT_BEST_FULL_D_REPLAY":
                    failures.append({"stage": stage, "name": name, "error": result.get("error"), "receipt_sha256": manifest[filename]["sha256"]})
                    continue
                require(name not in success, "a successful scientific forward was repeated")
                item = roster[name]
                require(result["checkpoint_sha256"] == item["checkpoint"]["sha256"] and result["best_epoch"] == item["strict_history"]["best_epoch"], "changed checkpoint selection")
                require(result["inputs_unchanged"] and result["model_tensor_digest_before"] == result["model_tensor_digest_after"], "input/model mutation")
                require(result["training_updates"] == result["backward_calls"] == result["optimizer_construct_restore_step"] == 0, "unexpected training")
                payload = torch.load(io.BytesIO(archive.read("RUN_OUTPUT/" + name + "/FRESH_D_LOGITS.pt")), weights_only=True, map_location="cpu")
                z, y = payload["logits"].numpy(), payload["labels"].numpy()
                require(z.shape == (31952, 11) and z.dtype == np.float64 and y.shape == (31952,) and sha(y.tobytes()) == label_sha, "complete D tensor/labels")
                ids = [r["id"] for r in plan["dev_entries"]]
                require(payload["episode_ids"] == ids and len(ids) == 128, "D episode order")
                expected_episode = np.concatenate([np.full(r["events"], i, dtype=np.int64) for i, r in enumerate(plan["dev_entries"])])
                expected_position = np.concatenate([np.arange(r["events"], dtype=np.int64) for r in plan["dev_entries"]])
                require(np.array_equal(payload["event_episode_index"].numpy(), expected_episode) and np.array_equal(payload["event_position"].numpy(), expected_position), "D event order")
                actual = metrics(z, y)
                compare_metrics(actual, result["fresh_metrics"], 2e-12)
                differences = compare_metrics(actual, item["D_metrics"], 2e-12)
                require(result["max_abs_logit_difference"] == 0., "original forward did not numerically match saved logits")
                success[name] = {"source_stage": stage, "epoch": result["best_epoch"], "checkpoint_sha256": result["checkpoint_sha256"],
                    "fresh_logit_payload_sha256": result["fresh_logits"]["sha256"], "metrics": actual,
                    "max_metric_error": max(differences.values()), "max_abs_logit_difference": result["max_abs_logit_difference"],
                    "model_state_dict_tensor_bytes": result["model_state_dict_tensor_bytes"],
                    "complete_recurrent_density_content_delay_state_bytes": result["complete_recurrent_density_content_delay_state_bytes"]}
            if "RUN_OUTPUT/partial-chain/RESULT.json" in manifest:
                partial = json.loads(archive.read("RUN_OUTPUT/partial-chain/RESULT.json"))
                for entry in partial["fits"]:
                    if "commit_chain" in entry:
                        require(entry["name"] not in chains, "original chain repeated after successful audit")
                        chains[entry["name"]] = entry
            archives.append({"stage": stage, **receipt})
    diagnostic = json.loads((ROOT / STAGES[-1] / "SEMANTICS_DIAGNOSTIC_NATIVE.json").read_bytes())
    metadata_wall += diagnostic["charged_wall_seconds"]
    require(set(success) == set(roster) == set(chains), "incomplete six-model reproducibility or surviving-chain roster")
    require(all(c["wall_seconds"] <= 210 for c in cost_totals.values()) and metadata_wall <= 360, "cumulative original stage caps")
    require(archives[-1]["global_elapsed_seconds"] <= 1800, "original global deadline")
    require(all(r["checks"].get("resume_witness_full_model_optimizer_RNG") is True for r in chains.values()), "original resume witness mismatch")
    means = {str(lr): sum(success[f"hcsn-s{s}-lr{lr}"]["metrics"]["macro_f1_11_classes"] for s in (101, 211, 307)) / 3 for lr in (.001, .003)}
    output = {"schema": "independent-current-C2-D-archive-readback-v1", "status": "PASS", "complete_current_best_D_replays": "6/6",
              "archives": archives, "successes": success, "retained_failed_receipts": failures, "cumulative_fit_costs": cost_totals,
              "metadata_charged_wall_seconds": metadata_wall, "metadata_wait4_CPU_seconds_excluding_external_diagnostic": metadata_cpu,
              "original_resume_witness_matches": "6/6", "original_complete_epoch_commits_verified": sum(len(r["commit_chain"]["verified"]) for r in chains.values()),
              "original_commit_errors": sum(len(r["commit_chain"]["errors"]) for r in chains.values()),
              "remaining_original_chain_failures": {n: r["failures"] for n, r in chains.items() if r["failures"]},
              "common_LR_D_means": means, "original_controller_terminal": "UNKNOWN", "original_full_training_replays": "0/6",
              "original_full_C2_chain_auditor_completed": False, "E_access": False, "E_admission": "HOLD",
              "saved_logit_match_semantics": "max_abs_logit_difference=0 and torch.equal establish numeric equality; the frozen field named bitwise_saved_logit_match does not check signed-zero byte patterns.",
              "archive_reader_model_construction_forward_backward_optimizer_operations": 0,
              "archive_reader_wall_seconds": time.monotonic() - started, "archive_reader_CPU_seconds": time.process_time() - cpu,
              "archive_reader_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    with (HERE / "FINAL_READBACK.json").open("x") as stream:
        json.dump(output, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: v for k, v in output.items() if k not in ("archives", "successes", "cumulative_fit_costs", "retained_failed_receipts", "remaining_original_chain_failures")}, indent=2))


if __name__ == "__main__":
    run()
