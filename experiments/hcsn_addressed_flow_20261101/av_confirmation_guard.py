"""Verify frozen AV identities and prepared data before confirmation.

Both modes validate and write evidence only. Neither calls an encoder, reads
confirmation outcomes, downloads media, or changes the frozen frontend.
The caller runs av_frontend.confirm exactly once after a successful receipt.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from experiments.hcsn_four_stage_flow_20261031 import av_data
from . import av_frontend


HERE = Path(__file__).resolve().parent
BASELINE_EXTRACTOR_SHA256 = "465f1d2bf296dc5df4b25cd5cdc781551740a16766bb631b937a80fb3ef7767f"
BASELINE_COHORT_SHA256 = "b65adcd877528b7cb5b81962ff3662c59ee1e144c26034b8a4e1d5e6426cf37a"
CORE_KEYS = ("actor", "sentence", "emotion", "clip", "sha256", "bytes")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text())


def checked(path, inputs, expected=None):
    path = Path(path)
    require(path.is_file(), "Missing required input: " + str(path))
    value = av_frontend.digest(path)
    require(expected is None or value == expected, "Hash mismatch: " + str(path))
    key = str(path.resolve())
    require(key not in inputs or inputs[key] == value, "Input changed during guard: " + key)
    inputs[key] = value
    return value


def json_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def verify_candidate(candidate_freeze, expected_candidate_sha256, cohort_path, independent_metadata,
                     historical_proof, expected_history_sha256, required_scope):
    """Metadata-only preflight: no raw or prepared confirmation content access."""
    inputs = {}
    candidate_freeze, cohort_path = Path(candidate_freeze), Path(cohort_path)
    require(len(expected_candidate_sha256) == 64, "An exact published candidate SHA256 is required")
    checked(candidate_freeze, inputs, expected_candidate_sha256)
    candidate = av_frontend.load_freeze(candidate_freeze)
    root = candidate_freeze.parent
    checked(av_frontend.__file__, inputs, candidate["source_sha256"])
    checked(HERE / "av_frontend_protocol.json", inputs, candidate["protocol_sha256"])
    checked(av_data.__file__, inputs, BASELINE_EXTRACTOR_SHA256)
    checked(__file__, inputs)
    for row in candidate["checkpoints"]:
        checked(root / row["file"], inputs, row["sha256"])
    for name, key in (("DEVELOPMENT.json", "development_sha256"),
                      ("TRAINING_SOURCE.py", "training_source_snapshot_sha256"),
                      ("SUBSET_CONTROLS.json", "subset_control_evidence_sha256")):
        checked(root / name, inputs, candidate[key])
    if "prospective_cohort_handoff" in candidate:
        handoff = candidate["prospective_cohort_handoff"]
        origin_path = HERE / "results/av_development/fit003/CANDIDATES.json"
        checked(origin_path, inputs, handoff["origin_candidate_sha256"])
        origin = read(origin_path)
        require(set(candidate) == set(origin) | {"prospective_cohort_handoff"},
                "Prospective handoff unexpectedly changes candidate fields")
        require(all(candidate[key] == value for key, value in origin.items() if key != "independent_cohort"),
                "Prospective handoff changes frozen models or development identities")
        require(handoff["checkpoints_changed"] is False and handoff["encoder_selection_changed"] is False
                and handoff["population_confirmation_claim_allowed"] is False,
                "One-actor handoff must preserve models and forbid population qualification")
        checked(root / "BLIND_PROTOCOL.json", inputs, handoff["blind_protocol_sha256"])
        blind = read(root / "BLIND_PROTOCOL.json")
        require(blind["base_protocol_sha256"] == candidate["protocol_sha256"]
                and blind["cohort_metadata_sha256"] == candidate["independent_cohort"]["sha256"]
                and blind["origin_candidate_sha256"] == handoff["origin_candidate_sha256"]
                and blind["same_models_and_weights"] is True
                and blind["selection_or_retuning_after_media"] is False,
                "One-actor blind protocol changes frozen scientific choices")
    old_path = av_frontend.BASE / "data/COHORT.json"
    checked(old_path, inputs, BASELINE_COHORT_SHA256)
    previous = read(old_path)
    checked(independent_metadata, inputs, candidate["independent_cohort"]["sha256"])
    metadata = read(independent_metadata)
    require(metadata["source_commit"] == av_data.UPSTREAM_COMMIT, "Wrong prospective media source")
    require(metadata["actors"] == candidate["independent_cohort"]["actors"], "Prospective actor identity changed")
    require(not (set(metadata["actors"]) & set(sum(previous["splits"].values(), []))),
            "Prospective actors overlap previous cohort")
    require(json_hash(metadata["records"]) == candidate["independent_cohort"]["records_sha256"],
            "Prospective metadata records changed")
    checked(cohort_path, inputs)
    splits, records = av_data.read_cohort(cohort_path)
    selected = [row for row in records if row["split"] == "test"]
    core = sorted([{key: row[key] for key in CORE_KEYS} for row in selected], key=lambda row: row["clip"])
    require(json_hash(core) == candidate["independent_cohort"]["core_records_sha256"],
            "Confirmation source records differ from frozen prospective cohort")
    require(set(splits["test"]) == set(metadata["actors"]), "Fresh actor split differs from frozen metadata")
    require(len(selected) == len(metadata["actors"]) * 12, "Fresh cohort does not contain all twelve clips per actor")
    # Disjointness from one immediate cohort does not establish an unseen
    # research cohort. Preserve the separately audited prior-history union.
    require(len(expected_history_sha256) == 64, "An exact published historical-proof SHA256 is required")
    checked(historical_proof, inputs, expected_history_sha256)
    history = read(historical_proof)
    require(history["source_commit"] == av_data.UPSTREAM_COMMIT, "Historical proof names another dataset")
    historical = set(history["source_evidence"]["historical"])
    current = set(sum(previous["splits"].values(), []))
    require(set(history["source_evidence"]["current"]) == current,
            "Historical proof's current cohort differs from pinned prior cohort")
    require(set(history["unused_actors"]) == set(history["all_dataset_actors"]) - historical - current,
            "Historical actor union arithmetic inconsistent")
    require(historical == set(previous["previously_observed_actors"]),
            "Historical proof differs from prior cohort's explicitly recorded exposures")
    overlap = sorted(set(metadata["actors"]) & (historical | current))
    require(required_scope in ("locked_cross_cohort_reevaluation", "globally_unseen"),
            "Unknown requested scientific cohort scope")
    require(required_scope != "globally_unseen" or not overlap,
            "Requested unseen-actor scope fails: these actors occur in audited research history")
    scope = ("locked cross-cohort reevaluation; prior research exposure exists" if overlap else
             "unseen in the explicitly audited historical cohorts; broader global absence is not established")
    qualification_path = root / "QUALIFICATION.json"
    checked(qualification_path, inputs)
    qualification = read(qualification_path)
    require(qualification["candidate_freeze_sha256"] == expected_candidate_sha256
            and qualification["history_proof_sha256"] == expected_history_sha256
            and set(qualification["actors"]) == set(metadata["actors"]),
            "Scientific qualification does not identify this candidate/cohort/history")
    if overlap:
        require(qualification["scientific_status"] == "locked_cross_cohort_reevaluation"
                and qualification["globally_fresh_claim_allowed"] is False,
                "Historical actors must be explicitly qualified as reevaluation")
    if len(metadata["actors"]) == 1:
        require(qualification["scientific_status"] == "one_documented_unseen_actor_blind_probe"
                and qualification["population_CI_claim_allowed"] is False
                and qualification["adoption_claim_allowed"] is False,
                "One actor cannot establish population uncertainty or adoption")
    return dict(candidate=candidate, splits=splits, records=records, selected=selected,
                inputs_sha256=inputs, cohort_sha256=inputs[str(cohort_path.resolve())],
                candidate_sha256=expected_candidate_sha256,
                scientific_cohort_scope=scope, prior_exposure_actors=overlap,
                historical_proof_sha256=expected_history_sha256,
                scientific_status=qualification["scientific_status"],
                population_adoption_claim_established=False)


def load_npz(path):
    with np.load(path, allow_pickle=False) as archive:
        return {key: archive[key] for key in archive.files}


def verify_prepared(preflight, media_root, data_root, temporal_root, mouth_root, cohort_path):
    """Check all receipt edges, then reconstruct every split array independently."""
    inputs = preflight["inputs_sha256"]
    candidate, rows = preflight["candidate"], preflight["selected"]
    media_root, data_root = Path(media_root), Path(data_root)
    temporal_root, mouth_root = Path(temporal_root), Path(mouth_root)
    frontend_sha = candidate["source_sha256"]
    plan_path = data_root / "PLAN.json"
    plan_sha = checked(plan_path, inputs)
    expected_contract = av_data.protocol_contract(cohort_path, preflight["splits"], preflight["records"])
    require(read(plan_path)["contract"] == json.loads(json.dumps(expected_contract)),
            "Prepared baseline PLAN differs from the pinned extractor/cohort contract")
    split_meta_path = data_root / "test.json"
    checked(split_meta_path, inputs)
    split_meta = read(split_meta_path)
    require(split_meta["schema"] == av_data.SCHEMA and split_meta["split"] == "test", "Wrong baseline split metadata")
    require(split_meta["plan_sha256"] == plan_sha, "Baseline split names a different PLAN")
    require(split_meta["candidate_freeze_sha256"] == preflight["candidate_sha256"],
            "Baseline split was not prepared under this candidate freeze")
    require(split_meta["model_arrays"] == list(av_data.MODEL_ARRAYS), "Unexpected baseline model inputs")
    require(split_meta["modality_slices"] == av_data.MODALITY_SLICES, "Baseline modality layout changed")
    expected_raw = [dict(clip=row["clip"], sha256=row["sha256"], bytes=row["bytes"]) for row in rows]
    require(split_meta["raw_sources"] == expected_raw, "Split raw-source list differs from frozen cohort")
    require(split_meta["actors"] == sorted(preflight["splits"]["test"]), "Split actor metadata changed")
    expected_episodes = len(preflight["splits"]["test"]) * len(av_data.EMOTIONS) * 8
    require(split_meta["episodes"] == expected_episodes, "Unexpected episode count")
    require(split_meta["total_sample_weight"] == expected_episodes * 1.5, "Unexpected label-balancing weights")
    cache_receipts = {}
    for receipt in split_meta["clip_receipts"]:
        require(receipt["clip"] not in cache_receipts, "Duplicate clip receipt in split metadata")
        cache_receipts[receipt["clip"]] = receipt
    require(set(cache_receipts) == {row["clip"] for row in rows}, "Incomplete split clip receipt set")

    features = {}
    for row in rows:
        clip = row["clip"]
        raw = media_root / (clip + ".flv")
        checked(raw, inputs, row["sha256"])
        require(raw.stat().st_size == row["bytes"], "Raw media size differs from frozen record: " + clip)
        path = data_root / "clip_features" / (clip + ".npz")
        receipt_path = path.with_suffix(".json")
        checked(receipt_path, inputs)
        receipt = read(receipt_path)
        require(receipt == cache_receipts[clip], "Split embeds a different extraction receipt: " + clip)
        require(receipt["clip"] == clip and receipt["raw_sha256"] == row["sha256"],
                "Baseline raw-to-feature edge changed: " + clip)
        require(receipt["source_sha256"] == BASELINE_EXTRACTOR_SHA256,
                "Baseline feature extractor identity changed: " + clip)
        checked(path, inputs, receipt["sha256"])
        values = load_npz(path)
        require(set(values) == {"audio", "video", "dt"}, "Unexpected baseline feature fields: " + clip)
        for mod in ("audio", "video"):
            require(values[mod].shape == (2, 64) and values[mod].dtype == np.float32
                    and np.isfinite(values[mod]).all(), "Invalid baseline feature shape/content: " + clip)
        require(np.array_equal(values["dt"], np.array([.5, .5], np.float32)), "Baseline feature clock changed")
        extraction = receipt["extraction"]
        selected_times = np.asarray(extraction["selected_video_times"])
        require(selected_times.shape == (2,) and np.isfinite(selected_times).all()
                and (selected_times >= 0).all() and (selected_times <= np.array([.5, 1.]) + 1e-12).all(),
                "Baseline video prefix receipt exceeds observation cutoff")
        require(extraction["audio_samples_used_per_window"] == 8000
                and extraction["native_audio_samples_used_per_window"] * 2 == extraction["native_audio_sample_rate"],
                "Baseline native audio-window receipt changed")
        features[clip] = {mod: values[mod] for mod in ("audio", "video")}

        for kind, directory, dimensions in (
                ("temporal", temporal_root, {"audio": 640, "video": 1280}),
                ("mouth", mouth_root, {"video": 684})):
            path = directory / (clip + ".npz")
            receipt_path = path.with_suffix(".json")
            checked(receipt_path, inputs)
            receipt = read(receipt_path)
            require(receipt["raw_sha256"] == row["sha256"], kind + " raw-to-feature edge changed: " + clip)
            require(receipt["source_sha256"] == frontend_sha, kind + " extractor identity changed: " + clip)
            checked(path, inputs, receipt["sha256"])
            values = load_npz(path)
            require(set(values) == set(dimensions), kind + " feature fields changed: " + clip)
            for mod, dimension in dimensions.items():
                require(values[mod].shape == (dimension,) and values[mod].dtype == np.float32
                        and np.isfinite(values[mod]).all(), kind + " feature shape/content invalid: " + clip)
            if kind == "temporal":
                require(receipt["feature_dimensions"] == dimensions, "Temporal dimension receipt mismatch")
                detail = receipt["detail"]
                require(np.isfinite([detail["origin"], detail["accepted_end"], detail["last_selected_frame"]]).all()
                        and abs(detail["accepted_end"] - detail["origin"] - 1.) < 1e-12
                        and detail["origin"] <= detail["last_selected_frame"] <= detail["accepted_end"]
                        and detail["native_audio_samples"] > 0,
                        "Temporal accepted-prefix receipt invalid")

    for kind, directory in (("temporal", temporal_root), ("mouth", mouth_root)):
        path = directory / "PREPARE_test.json"
        checked(path, inputs)
        receipt = read(path)
        require(receipt["splits"] == ["test"] and receipt["clips"] == len(rows)
                and receipt["source_sha256"] == frontend_sha, kind + " preparation receipt identity/count mismatch")
        if kind == "mouth":
            require(receipt["observation_seconds"] == 1., "Mouth observation budget changed")

    split_path, alias_path = data_root / "test.npz", data_root / "independent_test.npz"
    split_sha = checked(split_path, inputs, split_meta["sha256"])
    checked(alias_path, inputs, split_sha)
    alias_meta_path = data_root / "INDEPENDENT_SPLIT_ALIAS.json"
    checked(alias_meta_path, inputs)
    alias = read(alias_meta_path)
    require(alias["source"] == "test.npz" and alias["alias"] == "independent_test.npz"
            and alias["sha256"] == split_sha
            and alias["candidate_freeze_sha256"] == preflight["candidate_sha256"]
            and set(alias["actors"]) == set(preflight["splits"]["test"]), "Independent split alias identity mismatch")
    expected_arrays = av_data.assemble_episodes(rows, features)
    actual_arrays = load_npz(split_path)
    require(set(actual_arrays) == set(expected_arrays), "Split array fields differ from pinned assembler")
    for key, expected in expected_arrays.items():
        actual = actual_arrays[key]
        require(actual.dtype == expected.dtype and np.array_equal(actual, expected),
                "Split array differs from verified-clip reconstruction: " + key)
    require(len(actual_arrays["y"]) == expected_episodes, "Reconstructed count mismatch")
    return dict(raw_files=len(rows), derived_feature_archives=3 * len(rows), episodes=expected_episodes,
                actors=sorted(preflight["splits"]["test"]), split_sha256=split_sha,
                reconstructed_arrays=sorted(expected_arrays), all_reconstructed_arrays_equal=True,
                confirmation_split="independent_test",
                split_name_is_storage_alias_not_independence_claim=True,
                scientific_cohort_scope=preflight["scientific_cohort_scope"],
                prior_exposure_actors=preflight["prior_exposure_actors"],
                encoder_evaluation_performed=False)


def verify_unchanged(inputs):
    for path, expected in inputs.items():
        require(av_frontend.digest(path) == expected, "Guarded input changed during validation: " + path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preflight", "confirm"))
    for argument in ("candidate-freeze", "cohort-path", "independent-metadata", "historical-proof", "out"):
        parser.add_argument("--" + argument, type=Path, required=True)
    parser.add_argument("--expected-candidate-sha256", required=True)
    parser.add_argument("--expected-history-sha256", required=True)
    parser.add_argument("--required-scope", choices=("locked_cross_cohort_reevaluation", "globally_unseen"),
                        required=True)
    for argument in ("media-root", "data-root", "temporal-root", "mouth-root"):
        parser.add_argument("--" + argument, type=Path)
    args = parser.parse_args()
    require(not args.out.exists(), "Guard receipt already exists")
    start_wall, start_cpu = time.perf_counter(), time.process_time()
    result = dict(schema="hcsn.av.confirmation.guard.v1", mode=args.mode,
                  encoder_evaluation_performed=False, passed=False)
    try:
        preflight = verify_candidate(args.candidate_freeze, args.expected_candidate_sha256,
                                     args.cohort_path, args.independent_metadata, args.historical_proof,
                                     args.expected_history_sha256, args.required_scope)
        result.update(candidate_freeze_sha256=preflight["candidate_sha256"],
                      cohort_sha256=preflight["cohort_sha256"],
                      prospective_actors=sorted(preflight["splits"]["test"]),
                      scientific_cohort_scope=preflight["scientific_cohort_scope"],
                      scientific_status=preflight["scientific_status"],
                      population_adoption_claim_established=False,
                      prior_exposure_actors=preflight["prior_exposure_actors"],
                      historical_proof_sha256=preflight["historical_proof_sha256"])
        if args.mode == "confirm":
            require(all((args.media_root, args.data_root, args.temporal_root, args.mouth_root)),
                    "confirm validation requires all four prepared/media roots")
            result["prepared"] = verify_prepared(preflight, args.media_root, args.data_root,
                                                 args.temporal_root, args.mouth_root, args.cohort_path)
        verify_unchanged(preflight["inputs_sha256"])
        result.update(passed=True, inputs_sha256=preflight["inputs_sha256"],
                      next_action="Caller may invoke frozen av_frontend.confirm exactly once")
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
    result.update(cpu_seconds=time.process_time() - start_cpu, wall_seconds=time.perf_counter() - start_wall)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: value for key, value in result.items() if key != "inputs_sha256"}, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
