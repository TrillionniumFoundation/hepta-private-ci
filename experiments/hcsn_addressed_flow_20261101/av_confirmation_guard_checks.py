"""Focused metadata/receipt tamper checks; uses synthetic media bytes only."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

import numpy as np

from . import av_confirmation_guard as guard


HERE = Path(__file__).resolve().parent


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True))


def fixture(root):
    """One synthetic actor, 12 clips and 48 episodes; no real media decode."""
    roots = {key: root / key for key in ("media", "data", "temporal", "mouth")}
    for directory in roots.values():
        directory.mkdir()
    (roots["data"] / "clip_features").mkdir()
    selected, features, receipts = [], {}, []
    source = guard.av_frontend.digest(guard.av_frontend.__file__)
    for index, (sentence, emotion) in enumerate(
            (s, e) for s in guard.av_data.SENTENCES for e in guard.av_data.EMOTIONS):
        clip = f"9999_{sentence}_{emotion}_XX"
        raw = roots["media"] / (clip + ".flv")
        raw.write_bytes(b"SYNTHETIC_GUARD_FIXTURE:" + clip.encode())
        row = dict(actor="9999", sentence=sentence, emotion=emotion, split="test",
                   clip=clip, sha256=guard.av_frontend.digest(raw), bytes=raw.stat().st_size)
        selected.append(row)
        values = dict(audio=np.full((2, 64), index / 100, np.float32),
                      video=np.full((2, 64), index / 200, np.float32),
                      dt=np.full(2, .5, np.float32))
        path = roots["data"] / "clip_features" / (clip + ".npz")
        np.savez_compressed(path, **values)
        receipt = dict(clip=clip, raw_sha256=row["sha256"], sha256=guard.av_frontend.digest(path),
                       source_sha256=guard.BASELINE_EXTRACTOR_SHA256,
                       extraction=dict(selected_video_times=[.48, .98], audio_samples_used_per_window=8000,
                                       native_audio_samples_used_per_window=16000, native_audio_sample_rate=32000))
        save(path.with_suffix(".json"), receipt)
        receipts.append(receipt)
        features[clip] = values
        for kind, dimensions in (("temporal", dict(audio=640, video=1280)), ("mouth", dict(video=684))):
            path = roots[kind] / (clip + ".npz")
            np.savez_compressed(path, **{key: np.full(size, .1, np.float32) for key, size in dimensions.items()})
            receipt = dict(raw_sha256=row["sha256"], sha256=guard.av_frontend.digest(path), source_sha256=source)
            if kind == "temporal":
                receipt.update(feature_dimensions=dimensions,
                               detail=dict(origin=.0, accepted_end=1., last_selected_frame=.98, native_audio_samples=16000))
            save(path.with_suffix(".json"), receipt)
    selected.sort(key=lambda row: row["clip"])
    receipts.sort(key=lambda row: row["clip"])
    splits = dict(train=["9997"], validation=["9998"], test=["9999"])
    cohort = root / "COHORT.json"
    save(cohort, dict(splits=splits, records=selected, upstream_sha=guard.av_data.UPSTREAM_COMMIT))
    expected = guard.av_data.assemble_episodes(selected, features)
    path = roots["data"] / "test.npz"
    np.savez_compressed(path, **expected)
    split_sha = guard.av_frontend.digest(path)
    shutil.copyfile(path, roots["data"] / "independent_test.npz")
    plan = roots["data"] / "PLAN.json"
    save(plan, dict(contract=guard.av_data.protocol_contract(cohort, splits, selected)))
    candidate_sha = "f" * 64
    save(roots["data"] / "test.json", dict(
        schema=guard.av_data.SCHEMA, split="test", plan_sha256=guard.av_frontend.digest(plan),
        sha256=split_sha, candidate_freeze_sha256=candidate_sha, model_arrays=list(guard.av_data.MODEL_ARRAYS),
        modality_slices=guard.av_data.MODALITY_SLICES, raw_sources=[
            {key: row[key] for key in ("clip", "sha256", "bytes")} for row in selected],
        actors=["9999"], episodes=48, total_sample_weight=72., clip_receipts=receipts))
    save(roots["data"] / "INDEPENDENT_SPLIT_ALIAS.json", dict(
        source="test.npz", alias="independent_test.npz", sha256=split_sha,
        candidate_freeze_sha256=candidate_sha, actors=["9999"]))
    for kind in ("temporal", "mouth"):
        save(roots[kind] / "PREPARE_test.json", dict(
            splits=["test"], clips=12, source_sha256=source, observation_seconds=1.))
    preflight = dict(candidate={"source_sha256": source}, selected=selected, records=selected, splits=splits,
                     inputs_sha256={}, candidate_sha256=candidate_sha,
                     scientific_cohort_scope="synthetic fixture only", prior_exposure_actors=[])
    return roots, cohort, preflight


def run(out):
    out.mkdir(parents=True, exist_ok=False)
    (out / "sources").mkdir()
    for source in (Path(__file__), Path(guard.__file__)):
        shutil.copyfile(source, out / "sources" / source.name)
    rows = []

    def record(name, passed, detail=None):
        row = dict(name=name, passed=bool(passed), detail=detail)
        rows.append(row)
        with (out / "cases.jsonl").open("a") as stream:
            stream.write(json.dumps(row) + "\n")

    development = HERE / "results/av_development"
    candidate = development / "fit003/CANDIDATES.json"
    cohort = development / "INDEPENDENT_COHORT.json"
    metadata = development / "INDEPENDENT_COHORT_FROZEN_METADATA.json"
    history = development / "HISTORICAL_ACTOR_UNION_PROOF.json"
    candidate_sha = "18cf5752c049656156a1b87c05be95fa463f37c885cbc2188901f8fd0b46a495"
    history_sha = guard.av_frontend.digest(history)
    verified = guard.verify_candidate(candidate, candidate_sha, cohort, metadata, history, history_sha,
                                      "locked_cross_cohort_reevaluation")
    record("actual_frozen_metadata/qualified_reevaluation", len(verified["prior_exposure_actors"]) == 8)
    try:
        guard.verify_candidate(candidate, candidate_sha, cohort, metadata, history, history_sha, "globally_unseen")
        rejected = False
    except ValueError as error:
        rejected = "audited research history" in str(error)
    record("actual_frozen_metadata/reject_false_globally_unseen", rejected)
    blind = HERE / "results/av_blind1019_candidates/CANDIDATES.json"
    verified_blind = guard.verify_candidate(
        blind, "e15355f634395a67fd30e90aec3919b37d41be41a63e88055da400150a27b68e",
        development / "BLIND_ACTOR1019_COHORT.json",
        development / "BLIND_ACTOR1019_COHORT_METADATA.json",
        history, history_sha, "globally_unseen")
    record("actual_blind_metadata/one_unseen_actor_same_models",
           verified_blind["prior_exposure_actors"] == []
           and verified_blind["splits"]["test"] == ["1019"]
           and not verified_blind["population_adoption_claim_established"])

    with tempfile.TemporaryDirectory(dir=out) as temporary:
        tmp = Path(temporary)
        copied = tmp / "candidate"
        copied.mkdir()
        frozen = guard.read(candidate)
        for name in ["CANDIDATES.json", "DEVELOPMENT.json", "TRAINING_SOURCE.py",
                     "SUBSET_CONTROLS.json", "QUALIFICATION.json"]:
            shutil.copyfile(candidate.parent / name, copied / name)
        for row in frozen["checkpoints"]:
            shutil.copyfile(candidate.parent / row["file"], copied / row["file"])
        for name in ("TRAINING_SOURCE.py", "SUBSET_CONTROLS.json"):
            path = copied / name
            original = path.read_bytes()
            path.write_bytes(b"CHANGED_GUARD_TEST")
            try:
                guard.verify_candidate(copied / "CANDIDATES.json", candidate_sha, cohort, metadata,
                                       history, history_sha, "locked_cross_cohort_reevaluation")
                rejected = False
            except ValueError as error:
                rejected = "Hash mismatch" in str(error)
            record("frozen_historical_artifact_rejection/" + name, rejected)
            path.write_bytes(original)

        synthetic = tmp / "synthetic"
        synthetic.mkdir()
        roots, synthetic_cohort, preflight = fixture(synthetic)
        snapshots = {p: p.read_bytes() for p in synthetic.rglob("*") if p.is_file()}

        def validate():
            return guard.verify_prepared(copy.deepcopy(preflight), roots["media"], roots["data"],
                                         roots["temporal"], roots["mouth"], synthetic_cohort)

        initial = validate()
        record("synthetic_positive/complete_48_episode_chain", initial["all_reconstructed_arrays_equal"]
               and initial["raw_files"] == 12 and initial["derived_feature_archives"] == 36)
        clip = preflight["selected"][0]["clip"]

        def edit_json(path, updater):
            value = guard.read(path)
            updater(value)
            save(path, value)

        def baseline_receipt_source():
            path = roots["data"] / "clip_features" / (clip + ".json")
            edit_json(path, lambda row: row.update(source_sha256="0" * 64))
            altered = guard.read(path)
            edit_json(roots["data"] / "test.json", lambda row: row.update(
                clip_receipts=[altered if r["clip"] == clip else r for r in row["clip_receipts"]]))

        def changed_split_labels():
            path = roots["data"] / "test.npz"
            arrays = guard.load_npz(path)
            arrays["y"][0] = 1 - arrays["y"][0]
            np.savez_compressed(path, **arrays)
            checksum = guard.av_frontend.digest(path)
            shutil.copyfile(path, roots["data"] / "independent_test.npz")
            edit_json(roots["data"] / "test.json", lambda row: row.update(sha256=checksum))
            edit_json(roots["data"] / "INDEPENDENT_SPLIT_ALIAS.json", lambda row: row.update(sha256=checksum))

        cases = [
            ("raw_media_bytes", lambda: (roots["media"] / (clip + ".flv")).write_bytes(b"altered"), "Hash mismatch"),
            ("baseline_feature_archive", lambda: (roots["data"] / "clip_features" / (clip + ".npz")).write_bytes(b"altered"), "Hash mismatch"),
            ("baseline_extractor_identity", baseline_receipt_source, "extractor identity"),
            ("temporal_raw_edge", lambda: edit_json(roots["temporal"] / (clip + ".json"),
                 lambda row: row.update(raw_sha256="0" * 64)), "raw-to-feature"),
            ("mouth_extractor_identity", lambda: edit_json(roots["mouth"] / (clip + ".json"),
                 lambda row: row.update(source_sha256="0" * 64)), "extractor identity"),
            ("temporal_future_prefix", lambda: edit_json(roots["temporal"] / (clip + ".json"),
                 lambda row: row["detail"].update(last_selected_frame=1.1)), "prefix receipt"),
            ("prepared_clip_count", lambda: edit_json(roots["mouth"] / "PREPARE_test.json",
                 lambda row: row.update(clips=11)), "count mismatch"),
            ("split_candidate_identity", lambda: edit_json(roots["data"] / "test.json",
                 lambda row: row.update(candidate_freeze_sha256="0" * 64)), "candidate freeze"),
            ("split_episode_count", lambda: edit_json(roots["data"] / "test.json",
                 lambda row: row.update(episodes=47)), "episode count"),
            ("alias_bytes", lambda: (roots["data"] / "independent_test.npz").write_bytes(b"altered"), "Hash mismatch"),
            ("alias_scientific_identity", lambda: edit_json(roots["data"] / "INDEPENDENT_SPLIT_ALIAS.json",
                 lambda row: row.update(actors=["9998"])), "alias identity"),
            ("split_labels_with_consistent_hashes", changed_split_labels, "reconstruction: y"),
        ]
        for name, mutate, expected_error in cases:
            mutate()
            try:
                validate()
                passed, detail = False, "Unexpectedly accepted modified chain"
            except ValueError as error:
                detail = str(error)
                passed = expected_error in detail
            record("tamper_rejected/" + name, passed, detail)
            for path, contents in snapshots.items():
                path.write_bytes(contents)
        last = validate()
        record("synthetic_positive/chain_restored", last["all_reconstructed_arrays_equal"])

    summary = dict(checks=len(rows), passed=sum(row["passed"] for row in rows),
                   failed=sum(not row["passed"] for row in rows), historical_proof_sha256=history_sha,
                   source_sha256=guard.av_frontend.digest(guard.__file__),
                   confirmation_media_features_results_read=False,
                   scope="Actual frozen metadata only, plus synthetic raw bytes/features and targeted tampering")
    save(out / "SUMMARY.json", summary)
    save(out / "FAILURES.json", [row for row in rows if not row["passed"]])
    print(json.dumps(summary, indent=2))
    return int(summary["failed"] > 0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    raise SystemExit(run(parser.parse_args().out))
