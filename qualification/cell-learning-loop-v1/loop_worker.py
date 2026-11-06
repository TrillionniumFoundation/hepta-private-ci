"""One fresh interpreter per lifecycle phase; never retries candidate training."""

import resource
import time

START = time.perf_counter()
USAGE = resource.getrusage(resource.RUSAGE_SELF)

import json
import os
from pathlib import Path
import shutil
import sys
import traceback
import uuid

sys.dont_write_bytecode = True
from loop_common import canonical, identity, model_summary, read, report, runtime, sha, write


def execute_phase(run, phase):
    import numpy as np

    plan, modules, verify = runtime(run)
    tasks, native = modules["tasks"], modules["lifecycle"]
    owner = native.SourceOwner(run / "owner")
    scope, cell, encoder_hash = plan["scope"], plan["cell"], plan["encoder_sha256"]
    parent = plan["parent_artifact"]

    def load(artifact):
        return owner.load(artifact, scope, encoder_hash)

    def encoder():
        value = modules["backend"].FrozenEncoder(plan["model_dir"])
        if value.manifest_hash != encoder_hash:
            raise ValueError("Executing encoder identity differs from the frozen parent")
        return value

    def closure(artifact, snapshot, dataset, data_id):
        directory = owner.root / "artifacts" / artifact
        return verify(directory / "model.npz", source_snapshot=snapshot,
                      encoder_manifest_path=run / "inputs/encoder.json", encoder_root=plan["model_dir"],
                      dataset_npz_path=dataset, expected_data_id=data_id,
                      release_manifest_path=directory / "manifest.json")

    def candidate():
        return report(run, "train")["artifact"]

    def outputs(model, rows, features):
        # Only public text-derived features enter the private head; labels stay here.
        choices = model.predict(features)
        return [{"id": row["id"], "expected": row["expected"],
                 **tasks.score_prediction(row, int(choice))}
                for row, choice in zip(rows, choices, strict=True)]

    try:
        if phase == "bootstrap":
            snapshot = read(run / "inputs/parent-snapshot.json")
            for source in snapshot["records"]:
                owner.put(scope, source["source_id"], source["body"], expected_revision=0)
            cut, records = owner.snapshot(scope, [x["source_id"] for x in snapshot["records"]])
            if {"cut": cut, "records": records} != snapshot:
                raise ValueError("Native snapshot did not reconstruct the original source")
            shutil.copytree(run / "inputs/parent", owner.root / "artifacts" / parent)
            checked = closure(parent, snapshot, run / "inputs/train_features.npz", plan["parent_data_id"])
            model, manifest = load(parent)
            source_body = json.loads(records[0]["body"])
            rows = read(run / "inputs/train_rows.json")
            if (source_body["rows"] != rows or source_body["indices"] != list(range(120))
                    or source_body["feature_file_sha256"] != identity(run / "inputs/train_features.npz")["sha256"]):
                raise ValueError("Original source does not bind these training inputs")
            shared = encoder()
            fresh = shared.encode([row["text"] for row in rows])
            with np.load(run / "inputs/train_features.npz", allow_pickle=False) as saved:
                maximum = float(np.max(np.abs(fresh - saved["X"])))
                same = np.array_equal(model.predict(fresh), model.predict(saved["X"]))
            if maximum > 1e-6 or not same or model.state_hash() != plan["parent_state_sha256"]:
                raise ValueError("Original full-state restoration or actual encoder replay failed")
            epoch = owner.publish(scope, cell, parent, encoder_hash, expected_epoch=0,
                validator=lambda restored, sources: {
                    "passed": restored.state_hash() == checked["checkpoint"]["legacy_state_sha256"],
                    "kind": "exact archived parent restoration; no efficacy adoption",
                    "closure_checkpoint": checked["checkpoint"]["sha256"]})
            return {"artifact": parent, "state": model_summary(model), "closure": checked,
                    "epoch": epoch, "encoder": shared.stats, "reencoding_max_abs": maximum,
                    "reencoded_choices_equal": bool(same), "engineering_passed": True}

        if phase == "feedback":
            versions = read(run / "inputs/feedback-versions.json")
            snapshots = []
            for previous, body in enumerate(versions):
                owner.put(scope, plan["feedback_id"], canonical(body).decode(), expected_revision=previous)
                cut, records = owner.snapshot(scope, ["skills", plan["feedback_id"]])
                snapshots.append({"cut": cut, "records": records})
            write(run / "candidate-source-snapshot.json", snapshots[-1])
            return {"snapshots": snapshots, "labels_changed": ["unique_stable", "sort_numeric"],
                    "parent_did_not_fit_either_feedback_version": True, "engineering_passed": True}

        if phase == "train":
            model, _ = load(parent)
            inherited = model_summary(model)
            if inherited != report(run, "bootstrap")["state"]:
                raise ValueError("Training did not inherit the complete parent state")
            cut, sources = owner.snapshot(scope, ["skills", plan["feedback_id"]])
            if {"cut": cut, "records": sources} != read(run / "candidate-source-snapshot.json"):
                raise ValueError("Candidate sources changed after freeze")
            feedback = json.loads(next(x["body"] for x in sources if x["source_id"] == plan["feedback_id"]))
            old_rows = read(run / "inputs/train_rows.json")
            new_rows = feedback["training_queries"]
            rows = old_rows + new_rows
            labels = np.asarray([x["label"] for x in old_rows]
                                + [tasks.SKILLS.index(feedback["operation_id"])] * len(new_rows), dtype=np.int64)
            shared = encoder()
            features = shared.encode([row["text"] for row in rows])
            with (run / "candidate-training.npz").open("xb") as stream:
                np.savez_compressed(stream, X=features, y=labels)
            data_id = sha(canonical({"cut": cut, "row_ids": [row["id"] for row in rows]}))
            write(run / "TRAINING_STARTED.json", {"pid": os.getpid(), "schedule": plan["schedule"],
                  "inherited_state": inherited["state_sha256"], "data_id": data_id,
                  "protocol_sha256": identity(run / "PROTOCOL.json")["sha256"]})
            trained = model.train(features, labels, **plan["schedule"], data_id=data_id,
                                  source_version=sha(canonical(cut)), encoder_hash=encoder_hash,
                                  allow_data_change=True)
            if model.step != inherited["step"] + 16:
                raise ValueError("The single frozen training schedule was not completed")
            artifact = owner.stage(scope, cut, model, parent_artifact=parent)
            if any(path.stat().st_size > 512000 for path in (
                    run / "candidate-training.npz", owner.root / "artifacts" / artifact / "model.npz")):
                raise ValueError("Generated binary exceeds the repository blob bound; preserve it for chunking")
            return {"artifact": artifact, "data_id": data_id, "training": trained,
                    "inherited": inherited, "state": model_summary(model), "encoder": shared.stats,
                    "dataset": identity(run / "candidate-training.npz"), "rows": len(rows),
                    "new_authored_queries": len(new_rows), "sampler_reset_for_new_data": True,
                    "engineering_passed": True}

        if phase == "verify":
            checked = closure(candidate(), run / "candidate-source-snapshot.json",
                              run / "candidate-training.npz", report(run, "train")["data_id"])
            return {"closure": checked, "engineering_passed":
                    checked["checkpoint"]["legacy_state_sha256"] == report(run, "train")["state"]["state_sha256"]}

        if phase == "evaluate":
            incumbent, _ = load(parent)
            proposed, _ = load(candidate())
            if proposed.state_hash() != report(run, "verify")["closure"]["checkpoint"]["legacy_state_sha256"]:
                raise ValueError("Evaluation candidate changed after closure verification")
            historical = read(run / "inputs/test_rows.json")
            held = read(run / "inputs/oracle.json")["held_correction"]
            if len(historical) != 72:
                raise ValueError("Historical retention inventory changed")
            shared = encoder()
            features = shared.encode([row["text"] for row in historical + held])
            results = {}
            for label, model in (("parent", incumbent), ("candidate", proposed)):
                before = model.state_hash()
                scored = outputs(model, historical + held, features)
                if model.state_hash() != before:
                    raise ValueError("Independent evaluation mutated learned state")
                results[label] = {"historical_correct": sum(x["correct"] for x in scored[:72]),
                                  "correction_correct": sum(x["correct"] for x in scored[72:]),
                                  "state_sha256": before, "outputs": scored}
            return {"results": results, "encoder": shared.stats, "shared_encoding_calls": 1,
                    "historical_cases": 72, "authored_held_cases": len(held),
                    "future_natural_source_groups": 0, "engineering_passed": True}

        if phase in ("candidate_next", "parent_next"):
            row = read(run / "inputs/oracle.json")[phase]
            shared = encoder()
            started = time.perf_counter()
            features = shared.encode([row["text"]])
            artifact = candidate() if phase == "candidate_next" else parent
            model, manifest = load(artifact)
            before = model.state_hash()
            if phase == "parent_next":
                receipt = owner.read(scope, cell, features, encoder_hash)
                if receipt["artifact"] != parent:
                    raise ValueError("Rejected candidate replaced the active parent")
                choice = receipt["predictions"][0]
            else:
                if owner.cut(scope, [x["source_id"] for x in manifest["source_cut"]["records"]]) != manifest["source_cut"]:
                    raise ValueError("Shadow candidate source is stale")
                receipt = {"artifact": artifact, "mode": "unpublished shadow checkpoint"}
                choice = int(model.predict(features)[0])
            result = tasks.score_prediction(row, choice)
            same = before == model.state_hash()
            if not same or (phase == "parent_next" and not result["correct"]):
                raise ValueError("Parent next-task execution or state preservation failed")
            return {"public_input": tasks.public_input(row), "expected": row["expected"],
                    "result": result, "receipt": receipt, "state_preserved": same,
                    "encoder": shared.stats, "request_wall_seconds": time.perf_counter() - started,
                    "engineering_passed": True}

        if phase == "publish":
            before = dict(owner.db.execute("SELECT * FROM releases WHERE scope=? AND cell=?", (scope, cell)).fetchone())
            gates = []

            def validator(model, sources):
                evaluated = report(run, "evaluate")["results"]
                value = {"passed": False, "kind": "SourceOwner executable engineering validator",
                         "candidate_state_matches_evaluation": model.state_hash() == evaluated["candidate"]["state_sha256"],
                         "historical_correct_delta": evaluated["candidate"]["historical_correct"] - evaluated["parent"]["historical_correct"],
                         "reasons": ["independent_nine_arm_future_round_not_registered", "complete_lifecycle_cost_unknown"],
                         "future_adoption_gate_invoked": False,
                         "formal_gate_policy": "unchanged; this run grants no efficacy adoption"}
                gates.append(value)
                return value

            try:
                owner.publish(scope, cell, candidate(), encoder_hash,
                              expected_epoch=before["epoch"], validator=validator)
                raise AssertionError("Unqualified engineering candidate was adopted")
            except native.Refused as error:
                refusal = str(error)
            after = dict(owner.db.execute("SELECT * FROM releases WHERE scope=? AND cell=?", (scope, cell)).fetchone())
            if not gates or before != after or refusal != "executable publication validator rejected the model":
                raise ValueError("The publication gate did not preserve the parent")
            return {"refusal": refusal, "gate_calls": gates, "release_before": before,
                    "release_after": after, "engineering_passed": True}

        if phase == "revise_dependency":
            source = owner.source(scope, "skills")
            body = json.loads(source["body"])
            body["engineering_revision_notice"] = {
                "supersedes_body_sha256": source["body_sha256"], "labels_changed": False,
                "reason": "Explicit source revision tests stale dependency fencing; no knowledge gain claimed."}
            revision = owner.put(scope, "skills", canonical(body).decode(), expected_revision=1)
            return {"before": source, "after": owner.source(scope, "skills"), "revision": revision,
                    "labels_changed": False, "engineering_passed": True}

        if phase == "fence":
            model, manifest = load(parent)
            try:
                owner.read(scope, cell, np.zeros((1, model.config["input_dim"])), encoder_hash)
                raise AssertionError("Stale parent was allowed to infer")
            except native.Refused as error:
                refusal = str(error)
            checked = closure(parent, run / "inputs/parent-snapshot.json",
                              run / "inputs/train_features.npz", plan["parent_data_id"])
            files_preserved = all(identity(owner.root / "artifacts" / parent / name)
                                  == identity(run / "inputs/parent" / name)
                                  for name in ("model.npz", "manifest.json"))
            same = model_summary(model) == report(run, "bootstrap")["state"]
            if refusal != "source correction invalidated this release" or not files_preserved or not same:
                raise ValueError("Cold stale-source fence or retained full state failed")
            return {"refusal": refusal, "state_preserved": same, "artifact_bytes_preserved": files_preserved,
                    "historical_content_closure": checked, "live_source_frontier_valid": False,
                    "inference_after_fence": False, "engineering_passed": True}
        raise ValueError("Unknown lifecycle phase")
    finally:
        owner.close()


if __name__ == "__main__":
    run, phase = Path(sys.argv[1]).resolve(), sys.argv[2]
    try:
        result = execute_phase(run, phase)
        outcome = {"status": "completed", "result": result}
    except BaseException as error:
        outcome = {"status": "failed", "error": type(error).__name__, "message": str(error),
                   "traceback": traceback.format_exc()}
    usage = resource.getrusage(resource.RUSAGE_SELF)
    outcome.update({"phase": phase, "pid": os.getpid(), "python_optimize": sys.flags.optimize,
                    "process_instance_id": uuid.uuid4().hex,
                    "worker_metrics": {"wall_seconds": time.perf_counter() - START,
                        "cpu_user_seconds": usage.ru_utime - USAGE.ru_utime,
                        "cpu_system_seconds": usage.ru_stime - USAGE.ru_stime,
                        "peak_rss_bytes": usage.ru_maxrss * 1024}})
    print(json.dumps(outcome, sort_keys=True, allow_nan=False))
    sys.exit(0 if outcome["status"] == "completed" else 1)
