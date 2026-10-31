"""Prepare an owner fixture from a completed, SHA-bound real rollout.

This is a post-experiment engineering replay, never a new quality sample.
The native test executes the recorded neural actions through the real owners;
it does not rerun the Python controller inside the native owner.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def request_wire_digest(request):
    # Exact V1 serde struct field order; this is not sorted-object JSON.
    fields = ("schema", "request_id", "objective_sha256", "input_source_sha256", "model",
              "required_modalities", "pixels_f32", "mask_f32", "text_tokens", "noise_seed",
              "content_control", "actions")
    pins = ("checkpoint_sha256", "snapshot_sha256", "parameters_sha256", "config_sha256",
            "source_sha256", "python_sha256", "device_sha256", "runtime_versions", "hidden")
    require(set(request) == set(fields) and set(request["model"]) == set(pins), "V1 request fields")
    ordered = {k: ({p: request[k][p] for p in pins} if k == "model" else request[k]) for k in fields}
    return sha(json.dumps(ordered, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode())


def verify_completed_replay(directory, expected_rows_sha256):
    directory = Path(directory).resolve()
    provenance = json.loads((directory / "provenance.json").read_text())
    fixture = json.loads((directory / "controlled/fixture.json").read_text())
    run = Path(provenance["source_run"])
    status = json.loads((run / "status.json").read_text())
    summary = json.loads((run / "summary.json").read_text())
    protocol = json.loads((run / "protocol.json").read_text())
    require(status["state"] == "completed", 'Integrity binding at original verifier line 49')
    require(sha(canonical(summary).encode()) == status["summary_sha256"] == provenance["summary_sha256"], 'Integrity binding at original verifier line 50')
    require(sha(canonical(protocol).encode()) == summary["protocol_sha256"] == provenance["protocol_sha256"], 'Integrity binding at original verifier line 51')
    row = dict(provenance["source_row"])
    receipt = row.pop("receipt_sha256")
    require(sha(canonical(row).encode()) == receipt == provenance["row_receipt_sha256"], 'Integrity binding at original verifier line 54')
    raw_rows = (run / "rows.jsonl").read_bytes()
    require(sha(raw_rows) == expected_rows_sha256, "Independent completed rows pin")
    if "source_rows_sha256" in provenance:
        require(provenance["source_rows_sha256"] == expected_rows_sha256, "Retained export rows pin")
    rows = [json.loads(line) for line in raw_rows.splitlines()]
    require(len(rows) == status["rows"] == summary["rows"], "Completed row count")
    matching = [r for r in rows if r["receipt_sha256"] == receipt]
    require(matching == [provenance["source_row"]], "Unique original row membership")
    label = f"seed-{row['seed']}-{row['training']}"
    require(summary["checkpoint_files"][label]["snapshot_file_sha256"] == row["snapshot_file_sha256"],
            "Summary-bound model checkpoint")
    paths = sorted((directory / "controlled").glob("owner-evidence-*/execution.json"))
    if len(paths) != 1:
        raise ValueError("Require exactly one retained native owner execution")
    process = json.loads(paths[0].read_text())
    execution = process["execution"]
    require(process["request_sha256"] == execution["request_sha256"] == request_wire_digest(fixture["request"]),
            "Complete request wire binding")
    require(process["exit_code"] == 0 and not process["timed_out"], 'Integrity binding at original verifier line 73')
    require(not process["stdout_truncated"] and not process["stderr_truncated"], 'Integrity binding at original verifier line 74')
    require(process["authority"] == execution["authority"] == "deny_all", 'Integrity binding at original verifier line 75')
    require(json.loads(bytes(process["stdout"])) == execution, 'Integrity binding at original verifier line 76')
    require(execution["model"] == process["model"] == fixture["pins"] == fixture["request"]["model"], 'Integrity binding at original verifier line 77')
    require(execution["model"]["checkpoint_sha256"] == row["snapshot_file_sha256"], 'Integrity binding at original verifier line 78')
    require(execution["model"]["snapshot_sha256"] == row["snapshot_sha256"], 'Integrity binding at original verifier line 79')
    require(fixture["request"]["actions"] == row["actions"], 'Integrity binding at original verifier line 80')
    require(len(execution["states"]) == len(row["actions"]) + 1, 'Integrity binding at original verifier line 81')
    require(execution["states"][-1]["backend_state_sha256"] == row["final_state_sha256"], 'Integrity binding at original verifier line 82')
    for kind, raw, field in (("image", bytes(execution["png"]), "png_sha256"),
                             ("text", execution["caption"].encode(), "text_sha256")):
        original = (run / row["output_paths"][kind]).resolve()
        require(original.is_relative_to(run.resolve()), 'Integrity binding at original verifier line 86')
        require(raw == original.read_bytes(), 'Integrity binding at original verifier line 87')
        require(sha(raw) == execution[field] == row["output_hashes"][kind], 'Integrity binding at original verifier line 88')
    report = {"schema": "hepta.ndu.v6.trained-owner-replay-verification.v2",
              "state": "completed", "case_id": row["case_id"], "policy": row["policy"],
              "source_rows_sha256": expected_rows_sha256,
              "unique_original_row_membership_verified": True,
              "request_wire_sha256": execution["request_sha256"],
              "original_row_receipt": receipt, "execution_file": str(paths[0]),
              "execution_file_sha256": sha(paths[0].read_bytes()),
              "model_file_sha256": row["snapshot_file_sha256"],
              "raw_outputs_and_final_backend_state_identical": True,
              "recorded_actions_replayed": row["actions"],
              "host_cold_process_wall_ns": process["host_wall_ns"],
              "worker_execution_wall_ns": execution["wall_ns"],
              "worker_execution_cpu_ns": execution["cpu_ns"],
              "worker_peak_rss_bytes": execution["peak_rss_bytes"],
              "original_resident_complete_row_wall_ns": row["cost"]["wall_ns"],
              "new_scientific_samples": 0, "online_native_control": False,
              "authority": "deny_all"}
    with (directory / "verification.v2.json").open("x") as handle:
        handle.write(canonical(report) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-rows-sha256", required=True,
                        help="Independently retained rows pin from completed-run acceptance")
    parser.add_argument("--verify", action="store_true", help="Verify one completed native replay without running a model")
    args = parser.parse_args()
    if args.verify:
        print(canonical(verify_completed_replay(args.output, args.expected_rows_sha256)))
        return
    if any(value is None for value in (args.repo, args.run, args.cache)):
        parser.error("Preparation requires --repo, --run and --cache")
    run = args.run.resolve()
    status = json.loads((run / "status.json").read_text())
    if status.get("state") != "completed":
        raise ValueError("Only a completed experiment may supply an engineering fixture")
    if args.output.exists():
        raise FileExistsError(args.output)
    protocol = json.loads((run / "protocol.json").read_text())
    summary = json.loads((run / "summary.json").read_text())
    require(sha(canonical(summary).encode()) == status["summary_sha256"], 'Integrity binding at original verifier line 134')
    require(summary["protocol_sha256"] == sha(canonical(protocol).encode()), 'Integrity binding at original verifier line 135')
    raw_rows = (run / "rows.jsonl").read_bytes()
    require(sha(raw_rows) == args.expected_rows_sha256, "Independent completed rows pin")
    rows = [json.loads(line) for line in raw_rows.splitlines()]
    require(len(rows) == status["rows"], 'Integrity binding at original verifier line 139')
    candidates = sorted((r for r in rows if r["seed"] == protocol["seeds"][0]
                         and r["training"] == "terminal_entropic_ndu"
                         and r["split"] == "future" and r["budget"] == max(protocol["budgets"]) ),
                        key=lambda r: (r["case_id"], r["policy"]))
    selected = next((r for r in candidates if r["policy"] == "risk_aware_recursive" and r["actions"]), None)
    if selected is None:
        selected = next(r for r in candidates if r["policy"] == "fixed" and r["actions"])
    row = dict(selected)
    receipt = row.pop("receipt_sha256")
    require(sha(canonical(row).encode()) == receipt, 'Integrity binding at original verifier line 149')
    for kind, relative in row["output_paths"].items():
        path = (run / relative).resolve()
        require(path.is_relative_to(run), 'Integrity binding at original verifier line 152')
        require(sha(path.read_bytes()) == row["output_hashes"][kind], 'Integrity binding at original verifier line 153')

    sys.path.insert(0, str(args.repo.resolve()))
    from experiments.multimodal_output_portfolio.v6.data import load_corpus
    from experiments.multimodal_output_portfolio.v6.owner_worker import (
        SCHEMA, device_digest, parameters_digest, runtime_versions, source_digest,
    )
    from experiments.multimodal_output_portfolio.v6.plan_training import ControlledSnapshot
    from experiments.multimodal_output_portfolio.v6.run import case_batch

    corpus = load_corpus(args.cache, evaluator_sources=protocol["observer_sources"])
    require(corpus.manifest == protocol["dataset_manifest"], 'Integrity binding at original verifier line 164')
    case = next(c for c in protocol["cases"]["future"] if c["case_id"] == row["case_id"])
    batch = case_batch(corpus, "future", case["index"], case["corruption"])
    require(list(batch.source_ids[0]) == row["source_ids"], 'Integrity binding at original verifier line 167')
    observation = batch.observation
    del batch
    source_checkpoint = run / f"seed-{row['seed']}-{row['training']}.pt"
    snapshot = ControlledSnapshot.load(source_checkpoint, expected_file_sha256=row["snapshot_file_sha256"])
    require(snapshot.fingerprint == row["snapshot_sha256"], 'Integrity binding at original verifier line 172')
    directory = args.output.resolve() / "controlled"
    directory.mkdir(parents=True)
    checkpoint = directory / "base.pt"
    shutil.copyfile(source_checkpoint, checkpoint)
    pins = {"checkpoint_sha256": sha(checkpoint.read_bytes()), "snapshot_sha256": snapshot.fingerprint,
            "parameters_sha256": parameters_digest(snapshot),
            "config_sha256": sha(canonical(snapshot.config).encode()), "source_sha256": source_digest(),
            "python_sha256": sha(Path(sys.executable).read_bytes()), "device_sha256": device_digest(),
            "runtime_versions": runtime_versions(), "hidden": snapshot.config["hidden"]}
    pixels = observation.pixels.numpy().astype("<f4").reshape(-1).view("<u4").tolist()
    mask = observation.mask.numpy().astype("<f4").reshape(-1).view("<u4").tolist()
    tokens = observation.text_tokens.reshape(-1).tolist()
    input_identity = sha(canonical({"pixels_f32": pixels, "mask_f32": mask, "text_tokens": tokens}).encode())
    request = {"schema": SCHEMA, "request_id": "generation.trained.completed-run.1",
               "objective_sha256": protocol["metric_sha256"], "input_source_sha256": input_identity,
               "model": pins, "required_modalities": 3, "pixels_f32": pixels, "mask_f32": mask,
               "text_tokens": tokens, "noise_seed": row["seed"] * 10000 + case["index"],
               "content_control": row["policy"] != "allocation_only", "actions": row["actions"]}
    fixture = {"repository": str(args.repo.resolve()), "python": sys.executable,
               "artifact_root": str(directory), "checkpoint_name": checkpoint.name,
               "model_id": "v6.trained.research-fixture", "pins": pins, "request": request}
    (directory / "fixture.json").write_text(canonical(fixture) + "\n")
    (args.output / "fixture.json").write_text(canonical(fixture) + "\n")
    provenance = {"schema": "hepta.ndu.v6.trained-owner-fixture.v1", "source_run": str(run),
                  "source_rows_sha256": args.expected_rows_sha256,
                  "protocol_sha256": summary["protocol_sha256"], "summary_sha256": status["summary_sha256"],
                  "row_receipt_sha256": receipt, "source_row": selected,
                  "selection": "first seed, NDU training, largest budget, first future risk-aware row with an actual action; fixed fallback if all risk-aware rows stop",
                  "scope": "post-experiment replay of recorded actions through native execution owners; no new quality sample, online native controller, or production authority"}
    (args.output / "provenance.json").write_text(canonical(provenance) + "\n")
    print(canonical({"fixture": str(directory / "fixture.json"), "policy": row["policy"],
                     "case_id": row["case_id"], "actions": row["actions"], "checkpoint_sha256": pins["checkpoint_sha256"]}))


if __name__ == "__main__":
    main()
