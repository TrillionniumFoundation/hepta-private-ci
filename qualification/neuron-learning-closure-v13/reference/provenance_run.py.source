"""Actual pretrained-feature training through SourceOwner publication and reads.

Independent lifecycle integration run, not relabelled checkpoints or an extra
independent language dataset. Calibration controls publication; held outputs
never affect the fixed training schedule or later source observations.
"""

import argparse
import json
import math
from pathlib import Path
import time

import numpy as np

from adapter import Adapter
from lifecycle import Refused, SourceOwner, canonical, sha
import tasks


ROOT = Path(__file__).resolve().parent
SCOPE, CELL = "v13-provenance-independent-run", "semantic-memory"
SCHEDULE = {"seed": 713, "rank": 8, "steps": 240, "batch_size": 20, "lr": 0.01}


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                                   allow_nan=False) + "\n", encoding="utf-8")


def dataset(inputs, name):
    rows = read(inputs / f"{name}_rows.json")
    with np.load(inputs / f"{name}_features.npz", allow_pickle=False) as saved:
        X = saved["X"].copy()
        if len(X) != len(rows) or not np.isfinite(X).all():
            raise ValueError("Invalid frozen feature rows")
        if "y" in saved and not np.array_equal(saved["y"], [row["label"] for row in rows]):
            raise ValueError("Frozen feature labels differ from row identities")
    return X, rows


def source_body(inputs, name, rows, indices, event=None):
    return canonical({"dataset": name, "rows": rows, "indices": indices, "event": event,
                      "feature_file_sha256": sha((inputs / f"{name}_features.npz").read_bytes())}).decode()


def training_snapshot(owner, inputs, source_ids):
    cut, records = owner.snapshot(SCOPE, source_ids)
    matrices, labels, row_ids = [], [], []
    for source in sorted(records, key=lambda item: (item["source_id"] != "skills", item["source_id"])):
        body = json.loads(source["body"])
        name = body["dataset"]
        if sha((inputs / f"{name}_features.npz").read_bytes()) != body["feature_file_sha256"]:
            raise Refused("Source-bound feature file changed")
        X, actual_rows = dataset(inputs, name)
        selected = [actual_rows[i] for i in body["indices"]]
        if selected != body["rows"] or any(row["split"] != "train" for row in selected):
            raise Refused("Training rows differ from current source body")
        event = body["event"]
        if event is not None and any(row["label"] != tasks.SKILLS.index(event["operation_id"])
                                    or row["source_digest"] != event["digest"] for row in selected):
            raise Refused("Project labels do not follow their admitted source event")
        matrices.append(X[body["indices"]])
        labels.extend(row["label"] for row in selected)
        row_ids.extend(row["id"] for row in selected)
    return cut, np.vstack(matrices), np.asarray(labels, dtype=np.int64), row_ids


def param_hash(model):
    return sha(b"".join(name.encode() + np.ascontiguousarray(value).tobytes()
                        for name, value in sorted(model.params.items())))


def probe_read(owner, features, encoder_hash):
    try:
        receipt = owner.read(SCOPE, CELL, features[:1], encoder_hash)
        return {"status": "readable", "receipt": receipt}
    except Refused as error:
        return {"status": "unavailable", "reason": str(error)}


def evaluate_release(owner, inputs, name, encoder_hash):
    X, rows = dataset(inputs, name)
    started, cpu = time.perf_counter(), time.process_time()
    try:
        receipt = owner.read(SCOPE, CELL, X, encoder_hash)
    except Refused as error:
        return {"available": False, "eligible": len(rows), "evaluated": 0,
                "reason": str(error), "predictions": []}
    results = [{"id": row["id"], "query": row["text"], "expected_skill": row["skill"],
                "expected_output": row["expected"], **tasks.score_prediction(row, int(label))}
               for row, label in zip(rows, receipt["predictions"])]
    return {"available": True, "eligible": len(rows), "evaluated": len(results),
            "correct": sum(row["correct"] for row in results), "release_receipt": receipt,
            "cpu_seconds": time.process_time() - cpu, "wall_seconds": time.perf_counter() - started,
            "predictions": results, "encoder_preparation_cost_separate": True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, default=ROOT / "evidence/inputs")
    parser.add_argument("--output", type=Path, default=ROOT / "evidence/provenance")
    args = parser.parse_args()
    frozen, inventory = read(args.inputs / "FREEZE.json"), read(args.inputs / "INVENTORY.json")
    for name, expected in frozen["source_hashes"].items():
        if sha((ROOT / name).read_bytes()) != expected:
            raise Refused(f"Original frozen source changed: {name}")
    for name, identity in inventory.items():
        if sha((args.inputs / name).read_bytes()) != identity["sha256"]:
            raise Refused(f"Frozen input changed: {name}")
    args.output.mkdir(parents=True, exist_ok=False)
    manifest = read(args.inputs / "encoder_manifest.json")
    encoder_hash = manifest["encoder_hash"]
    plan = {"source_sha256": sha(Path(__file__).read_bytes()), "schedule": SCHEDULE,
            "frontiers": [0, 3, 4, 5, 6], "initialization": "fresh seed-713 parameters and optimizer",
            "skill_gate": "at least ceil(0.8*48), later at least initial correct minus one",
            "profile_gate": "6/6 actual executed calibration outputs whenever profile sources are present",
            "held_results_influence_training_or_publication": False,
            "same_data_not_independent_efficacy_replication": True,
            "owner_kind": "research SQLite SourceOwner; not native Hepta production authority"}
    write(args.output / "FREEZE.json", plan)
    started, cpu = time.perf_counter(), time.process_time()
    owner = SourceOwner(args.output / "owner")
    X0, rows0 = dataset(args.inputs, "train")
    XC, calibration = dataset(args.inputs, "calibration")
    if len(rows0) != 120 or len(calibration) != 48:
        raise Refused("The declared skill train/calibration sizes changed")
    owner.put(SCOPE, "skills", source_body(args.inputs, "train", rows0, list(range(len(rows0)))), expected_revision=0)
    ids, model, parent, published, epoch, initial_correct = ["skills"], None, None, None, 0, None
    reports, last_sequence = [], 0
    try:
        for frontier in plan["frontiers"]:
            phase = args.output / f"frontier-{frontier}"
            phase.mkdir()
            changed, additions = [], []
            if frontier:
                name = f"profile-{frontier}-train"
                _, current_rows = dataset(args.inputs, name)
                for event in tasks.profile_journal():
                    if not last_sequence < event["sequence"] <= frontier:
                        continue
                    source_id = "project:" + event["project"]
                    prior = owner.source(SCOPE, source_id)
                    indices = [i for i, row in enumerate(current_rows) if row["project"] == event["project"]]
                    owner.put(SCOPE, source_id, source_body(args.inputs, name,
                              [current_rows[i] for i in indices], indices, event),
                              expected_revision=prior["revision"] if prior else 0)
                    (changed if prior else additions).append(source_id)
                    if source_id not in ids:
                        ids.append(source_id)
                last_sequence = frontier
            prior_ids = {row["source_id"] for row in published["cut"]["records"]} if published else set()
            before_fit = probe_read(owner, X0, encoder_hash)
            must_block = bool(prior_ids.intersection(changed))
            already_stale = published is not None and any(
                owner.source(SCOPE, row["source_id"])["revision"] != row["revision"]
                for row in published["cut"]["records"])
            fence_ok = before_fit["status"] == ("unavailable" if published is None or must_block or already_stale else "readable")
            if not fence_ok:
                raise Refused("Observed read fencing contradicts the published source dependencies")
            cut, X, y, row_ids = training_snapshot(owner, args.inputs, ids)
            version = sha(canonical(cut))
            if model is None:
                model = Adapter(384, len(tasks.SKILLS), SCHEDULE["rank"], SCHEDULE["seed"],
                                encoder_hash=encoder_hash, source_version=version)
            old_params, old_step = param_hash(model), model.step
            training = model.train(X, y, steps=SCHEDULE["steps"], batch_size=SCHEDULE["batch_size"],
                                   lr=SCHEDULE["lr"], data_id=sha(canonical(row_ids)),
                                   source_version=version, allow_data_change=frontier != 0)
            if model.step - old_step != SCHEDULE["steps"] or old_params == param_hash(model):
                raise Refused("Candidate did not execute the declared real parameter updates")
            predecessor = parent
            artifact = owner.stage(SCOPE, cut, model, parent_artifact=predecessor)
            parent = artifact
            validation = {}
            XP, profile_cal = dataset(args.inputs, f"profile-{frontier}-calibration") if frontier else (None, [])
            if frontier and len(profile_cal) != 6:
                raise Refused("The declared profile calibration requires exactly six cases")
            def validator(candidate, sources):
                skill_correct = sum(tasks.score_prediction(row, int(label))["correct"]
                                    for row, label in zip(calibration, candidate.predict(XC)))
                profile_correct = sum(tasks.score_prediction(row, int(label))["correct"]
                                      for row, label in zip(profile_cal, candidate.predict(XP))) if frontier else 0
                floor = max(math.ceil(0.8 * len(calibration)), (initial_correct - 1) if initial_correct is not None else 0)
                validation.update(passed=skill_correct >= floor and profile_correct == len(profile_cal),
                                  skill_correct=skill_correct, skill_total=len(calibration), skill_floor=floor,
                                  profile_correct=profile_correct, profile_total=len(profile_cal),
                                  source_count=len(sources), calibration_only=True)
                return dict(validation)
            try:
                epoch = owner.publish(SCOPE, CELL, artifact, encoder_hash, expected_epoch=epoch, validator=validator)
                published = {"artifact": artifact, "cut": cut, "epoch": epoch}
                publication = {"status": "published", "epoch": epoch}
            except Refused as error:
                publication = {"status": "candidate_retained_not_published", "reason": str(error), "epoch": epoch}
            if initial_correct is None and frontier == 0:
                initial_correct = validation["skill_correct"]
            report = {"frontier": frontier, "cut": cut, "source_version": version, "training": training,
                      "parameter_hash_before": old_params, "parameter_hash_after": param_hash(model),
                      "state_sha256": model.state_hash(), "candidate_artifact": artifact,
                      "parent_artifact": predecessor,
                      "candidate_path": str(owner.root / "artifacts" / artifact / "model.npz"),
                      "candidate_file_sha256": sha((owner.root / "artifacts" / artifact / "model.npz").read_bytes()),
                      "source_additions": additions, "source_corrections": changed, "old_release_probe": before_fit,
                      "old_release_depends_on_correction": must_block, "read_fencing_passed": fence_ok,
                      "validation": validation, "publication": publication, "active_release": published,
                      "active_release_matches_candidate": published is not None and published["artifact"] == artifact}
            write(phase / "CANDIDATE.json", report)
            held = {"skills": evaluate_release(owner, args.inputs, "test", encoder_hash)}
            if frontier:
                held["profile"] = evaluate_release(owner, args.inputs, f"profile-{frontier}-test", encoder_hash)
            write(phase / "OWNER_READ_RESULTS.json", held)
            reports.append(report)
            write(args.output / "PROGRESS.json", reports)
        before_revoke = probe_read(owner, X0, encoder_hash)
        target = "project:amber"
        prior = owner.source(SCOPE, target)
        owner.put(SCOPE, target, prior["body"], expected_revision=prior["revision"], active=False)
        after_revoke = probe_read(owner, X0, encoder_hash)
        applies = published is not None and target in {r["source_id"] for r in published["cut"]["records"]}
        if applies and after_revoke["status"] != "unavailable":
            raise Refused("Revocation failed to block a dependent published release")
        denied = {}
        for name, scope, base in (("wrong_scope", SCOPE + "-other", encoder_hash), ("wrong_encoder", SCOPE, "0" * 64)):
            try:
                owner.load(parent, scope, base)
                denied[name] = False
            except Refused:
                denied[name] = True
        write(args.output / "RESULTS.json", {**plan, "phases": reports, "wrong_identity_denied": denied,
              "revocation": {"target": target, "dependent_published_release_exists": applies,
                             "before": before_revoke, "after": after_revoke,
                             "isolated_readable_to_blocked": applies and before_revoke["status"] == "readable"
                             and after_revoke["status"] == "unavailable"},
              "wall_seconds": time.perf_counter() - started, "cpu_seconds": time.process_time() - cpu,
              "pretrained_feature_preparation_ledger": {k: manifest[k] for k in ("stats", "wall_seconds", "cpu_seconds")},
              "no_weight_erasure_or_unlearning_claim": True})
    finally:
        owner.close()


if __name__ == "__main__":
    main()
