"""Separately frozen post-run decision replay; no optimizer call or source edit."""

import argparse
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import resource
import shutil
import sys

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE.parent))
from loop_common import canonical, frozen, identity, read, runtime, sha, write
from quality import assess, publication_decision, require
from phase_process import complete_cpu_total, run_phase


def prepare(origin, output):
    old = frozen(origin)
    require(read(origin / "phase_results/evaluate.json")["protocol_sha256"]
            == identity(origin / "PROTOCOL.json")["sha256"], "original evaluation protocol changed")
    trained = read(origin / "phase_results/train.json")["result"]
    sources = {"evaluation.json": origin / "phase_results/evaluate.json",
               "parent-snapshot.json": origin / "inputs/parent-snapshot.json",
               "candidate-snapshot.json": origin / "candidate-source-snapshot.json",
               "parent-training.npz": origin / "inputs/train_features.npz",
               "candidate-training.npz": origin / "candidate-training.npz",
               "encoder.json": origin / "inputs/encoder.json",
               "original-inventory.json": origin.parent.parent / "DELIVERY_INVENTORY.json"}
    sources.update({name: origin / "inputs" / name for name in
                    ("test_rows.json", "oracle.json", "feedback-versions.json")})
    bindings = {"historical_cases": 72}
    for arm, artifact in (("parent", old["parent_artifact"]), ("candidate", trained["artifact"])):
        folder = origin / "owner/artifacts" / artifact
        manifest = read(folder / "manifest.json")
        bindings[arm] = {"artifact": artifact, "checkpoint_sha256": manifest["model_sha256"],
                        "state_sha256": manifest["state_sha256"], "source_version": manifest["source_version"],
                        "encoder_sha256": manifest["encoder_sha256"]}
        sources.update({arm + "/" + name: folder / name for name in ("manifest.json", "model.npz")})
    for name, source in sources.items():
        destination = output / "inputs" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    code = output / "EXECUTED_SOURCE"
    code.mkdir()
    for source in HERE.glob("*.py"):
        shutil.copyfile(source, code / source.name)
    for name in ("loop_common.py", "tasks.py"):
        shutil.copyfile(origin / "EXECUTED_SOURCE" / name, code / name)
    shutil.copytree(origin / "EXECUTED_SOURCE/validator", code / "validator")
    plan = {"schema": "hepta.engineering.post-run-decision.v1", "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
            "original_run": str(origin), "original_protocol": identity(origin / "PROTOCOL.json"),
            "post_run_replay": True, "prior_results_known": True, "prospective_claim": False,
            "owner_kind": "explicit reconstructed SourceOwner fork; original owner remains untouched",
            "scope": old["scope"], "cell": old["cell"], "model_dir": old["model_dir"],
            "feedback_id": old["feedback_id"], "bindings": bindings,
            "data_ids": {"parent": old["parent_data_id"], "candidate": trained["data_id"]},
            "quality_rule": "corrected-task strict improvement AND no aggregate historical loss",
            "authority_rule": "fixed formal/cost HOLD; no caller-provided authorization Boolean",
            "optimizer_updates": 0, "phases": ["decision", "cold_check"],
            "child_wall_seconds": 60, "child_cleanup_seconds": 5}
    write(output / "PROTOCOL.json", plan)
    inventory = {str(p.relative_to(output)): {"identity": identity(p)} for p in sorted(output.rglob("*")) if p.is_file()}
    require(all(x["identity"]["bytes"] <= 512000 for x in inventory.values()), "input exceeds blob bound")
    write(output / "INVENTORY.json", inventory)
    write(output / "LOCK.json", {name: identity(output / name)["sha256"] for name in ("PROTOCOL.json", "INVENTORY.json")})


def worker(output, phase):
    plan, modules, verify = runtime(output)
    native, tasks = modules["lifecycle"], modules["tasks"]
    scope, cell, bindings = plan["scope"], plan["cell"], plan["bindings"]
    owner = native.SourceOwner(output / "fork-owner")
    try:
        if phase == "decision":
            parent_snapshot = read(output / "inputs/parent-snapshot.json")
            candidate_snapshot = read(output / "inputs/candidate-snapshot.json")
            for row in parent_snapshot["records"]:
                owner.put(scope, row["source_id"], row["body"], expected_revision=0)
            for revision, body in enumerate(read(output / "inputs/feedback-versions.json")):
                owner.put(scope, plan["feedback_id"], canonical(body).decode(), expected_revision=revision)
            models, paths, closures = {}, {}, {}
            for arm, snapshot in (("parent", parent_snapshot), ("candidate", candidate_snapshot)):
                cut, records = owner.snapshot(scope, [x["source_id"] for x in snapshot["records"]])
                require({"cut": cut, "records": records} == snapshot, "fork did not reconstruct frozen cut")
                binding = bindings[arm]
                directory = owner.root / "artifacts" / binding["artifact"]
                shutil.copytree(output / "inputs" / arm, directory)
                paths[arm] = directory / "model.npz"
                closures[arm] = verify(paths[arm], source_snapshot=snapshot,
                    encoder_manifest_path=output / "inputs/encoder.json", encoder_root=plan["model_dir"],
                    dataset_npz_path=output / "inputs" / (arm + "-training.npz"),
                    expected_data_id=plan["data_ids"][arm], release_manifest_path=directory / "manifest.json")
                models[arm], _ = owner.load(binding["artifact"], scope, binding["encoder_sha256"])
            encoder = modules["backend"].FrozenEncoder(plan["model_dir"])
            require(encoder.manifest_hash == bindings["parent"]["encoder_sha256"], "encoder identity changed")
            cases = read(output / "inputs/test_rows.json") + read(output / "inputs/oracle.json")["held_correction"]
            features = encoder.encode([row["text"] for row in cases])
            receipt = read(output / "inputs/evaluation.json")
            def quality(value, actual_models):
                return assess(value, cases, features, actual_models, paths, bindings, tasks.score_prediction)
            probes = {}
            for probe in ("forged_metric", "bool_as_integer", "wrong_actual_head", "boolean_exit_code"):
                forged, actual = copy.deepcopy(receipt), dict(models)
                if probe == "forged_metric":
                    forged["result"]["results"]["candidate"]["historical_correct"] += 4
                elif probe == "bool_as_integer":
                    row = forged["result"]["results"]["candidate"]["outputs"][0]
                    row["correct"] = int(row["correct"])
                elif probe == "boolean_exit_code":
                    forged["parent_observed"]["returncode"] = False
                else:
                    actual["candidate"] = models["parent"]
                try:
                    quality(forged, actual)
                    raise AssertionError("Invalid identity/metric probe was accepted")
                except ValueError as error:
                    probes[probe] = str(error)
            parent = bindings["parent"]
            owner.publish(scope, cell, parent["artifact"], parent["encoder_sha256"], expected_epoch=0,
                validator=lambda model, sources: {"passed": model.state_hash() == parent["state_sha256"],
                                                  "kind": "verified historical parent restoration in fork"})
            before = dict(owner.db.execute("SELECT * FROM releases WHERE scope=? AND cell=?", (scope, cell)).fetchone())
            calls = []
            def gate(model, sources):
                decision = publication_decision(quality(receipt, {"parent": models["parent"], "candidate": model}))
                calls.append(decision)
                return decision
            candidate = bindings["candidate"]
            try:
                owner.publish(scope, cell, candidate["artifact"], candidate["encoder_sha256"],
                              expected_epoch=before["epoch"], validator=gate)
                raise AssertionError("Post-run replay granted candidate publication")
            except native.Refused as error:
                refusal = str(error)
            after = dict(owner.db.execute("SELECT * FROM releases WHERE scope=? AND cell=?", (scope, cell)).fetchone())
            require(len(calls) == 1 and before == after, "callback/persistence boundary failed")
            require(refusal == "executable publication validator rejected the model", "wrong publication refusal path")
            require(calls[0]["quality"]["quality_vetoes"] == ["historical_retention_loss"], "actual retention veto missing")
            return {"closures": closures, "encoder": encoder.stats, "gate_calls": calls, "refusal": refusal,
                    "release_before": before, "release_after": after, "negative_probes": probes,
                    "optimizer_updates": 0, "engineering_passed": True}
        parent = bindings["parent"]
        row = read(output / "inputs/oracle.json")["parent_next"]
        encoder = modules["backend"].FrozenEncoder(plan["model_dir"])
        require(encoder.manifest_hash == parent["encoder_sha256"], "cold encoder identity changed")
        receipt = owner.read(scope, cell, encoder.encode([row["text"]]), encoder.manifest_hash)
        result = tasks.score_prediction(row, receipt["predictions"][0])
        require(receipt["artifact"] == parent["artifact"] and receipt["epoch"] == 1 and result["correct"], "cold parent did not persist")
        for arm in ("parent", "candidate"):
            model, _ = owner.load(bindings[arm]["artifact"], scope, bindings[arm]["encoder_sha256"])
            require(model.state_hash() == bindings[arm]["state_sha256"], "replay changed complete model state")
        return {"receipt": receipt, "result": result, "optimizer_updates": 0, "engineering_passed": True}
    finally:
        owner.close()


def main(args):
    output, origin = args.output.resolve(), args.origin.resolve()
    require(output.is_relative_to(HERE), "replay output must remain in its own directory")
    output.mkdir(parents=True, exist_ok=False)
    records, failure = [], None
    try:
        prepare(origin, output)
        for phase in ("decision", "cold_check"):
            plan = frozen(output)
            command = [sys.executable, "-B", str(output / "EXECUTED_SOURCE/run_replay.py"),
                       "--origin", str(origin), "--output", str(output), "--worker", phase]
            record = {"phase": phase, "result": {"engineering_passed": False},
                      "process_metrics": {"pid": None, "exit_code": None,
                          "direct_child_reaped": False, "cpu_user_seconds": None,
                          "cpu_system_seconds": None, "peak_rss_bytes": None,
                          "dispatch_outcome": "unknown until a complete process observation returns"}}
            records.append(record)
            try:
                metrics = run_phase(command, output / (phase + ".log"),
                    {**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"},
                    wall_seconds=plan["child_wall_seconds"], cleanup_seconds=plan["child_cleanup_seconds"])
                record["process_metrics"] = metrics
            except BaseException as error:
                record["result"]["error"] = {"type": type(error).__name__, "message": str(error)}
                write(output / (phase + ".json"), record)
                raise
            try:
                require(metrics["direct_child_reaped"], "worker completion remains unknown")
                result = read(output / (phase + ".log"))
            except (OSError, ValueError):
                result = {"engineering_passed": False, "error": "incomplete worker receipt"}
            record["result"] = result
            write(output / (phase + ".json"), record)
            require(not metrics["timed_out"] and metrics["direct_child_reaped"]
                    and metrics["wait_error"] is None and metrics["termination_error"] is None and metrics["log_error"] is None
                    and type(metrics["exit_code"]) is int and metrics["exit_code"] == 0
                    and result.get("engineering_passed") is True, "replay phase failed")
    except BaseException as error:
        failure = {"type": type(error).__name__, "message": str(error)}
    original_unchanged = False
    if (output / "inputs/original-inventory.json").exists():
        try:
            expected = read(output / "inputs/original-inventory.json")["files"]
            original_unchanged = all(identity(origin.parent.parent / name) == value for name, value in expected.items())
            require(identity(origin.parent.parent / "DELIVERY_INVENTORY.json")
                    == identity(output / "inputs/original-inventory.json"), "original delivery inventory changed")
        except (OSError, ValueError) as error:
            failure = {"type": type(error).__name__, "message": str(error)}
    summary = {"post_run_replay": True, "engineering_passed": failure is None and original_unchanged,
               "failure": failure, "original_delivery_files_unchanged": original_unchanged, "optimizer_updates": 0,
               "child_process_cpu": {"user_seconds": complete_cpu_total(records, "cpu_user_seconds"),
                                     "system_seconds": complete_cpu_total(records, "cpu_system_seconds")},
               "energy_joules": None, "billed_usd": None, "historical_acquisition": None,
               "retained_byte_seconds": None, "host_network_bytes": None, "p99_seconds": None,
               "full_cost_qualified": False, "positive_candidate_adoption_qualified": False,
               "records": records}
    write(output / "SUMMARY.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "records"}, sort_keys=True))
    require(summary["engineering_passed"], "post-run decision replay did not pass")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", choices=("decision", "cold_check"))
    arguments = parser.parse_args()
    if arguments.worker:
        resource.setrlimit(resource.RLIMIT_CPU, (30, 31))
        print(json.dumps(worker(arguments.output.resolve(), arguments.worker), sort_keys=True, allow_nan=False))
    else:
        main(arguments)
