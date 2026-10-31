"""Independent closed-run audit; never imports the experiment or runs a model/codec."""

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import time
import traceback
import wave

import numpy as np


PROTOCOL_SHA = "6a305d92578da4d6e41ebc104101b7af58ebc02306ea6c54d9e73ae724222f08"
PRIMARY = "consensus_or_single_v3"
MODES = ("image", "text", "audio", "video")
WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
CAPTION = re.compile(r"left ([0-9]) right ([0-9]) relation (less|equal|greater)")


def sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def close(actual, expected, description, tolerance=1e-12):
    if isinstance(expected, dict):
        require(set(actual) == set(expected), description + " keys")
        for key in expected:
            close(actual[key], expected[key], description + "/" + key, tolerance)
    elif isinstance(expected, list):
        require(len(actual) == len(expected), description + " length")
        for index, value in enumerate(expected):
            close(actual[index], value, description + "/" + str(index), tolerance)
    elif isinstance(expected, float):
        require(math.isfinite(actual) and abs(actual - expected) <= tolerance,
                description + f": {actual!r} != {expected!r}")
    else:
        require(actual == expected, description + " differs")


def quantile(values, probability):
    ordered = sorted(values)
    location = (len(ordered) - 1) * probability
    left = math.floor(location)
    right = math.ceil(location)
    return ordered[left] + (ordered[right] - ordered[left]) * (location - left)


def swap_bits(seed, count):
    """First <=227 CPU MT19937 draws, then integer range-two modulo.

    Reconstructed from the installed MT19937RNGEngine/DistributionsHelper
    headers, without importing Torch or executing a source/model loader.
    """
    require(count <= 227, "Only first MT state segment is needed")
    state = [seed & 0xffffffff]
    for index in range(1, 624):
        value = state[-1]
        state.append((1812433253 * (value ^ (value >> 30)) + index) & 0xffffffff)
    result = []
    for index in range(count):
        mix = (state[index] & 0x80000000) | (state[index + 1] & 0x7fffffff)
        value = state[index + 397] ^ (mix >> 1) ^ (0x9908b0df if state[index + 1] & 1 else 0)
        value ^= value >> 11
        value ^= (value << 7) & 0x9d2c5680
        value ^= (value << 15) & 0xefc60000
        value ^= value >> 18
        result.append(value % 2)
    require(result == np.random.RandomState(seed).randint(2, size=count).tolist(), "Independent MT implementations differ")
    return result


def pinned_by_digest(spec, digest):
    values = [Path(path) for path, expected in spec["frozen_candidate_sha256"].items() if expected == digest]
    require(len(values) == 1, "Expected one path-bound input for " + digest)
    return values[0]


def source_census(spec, cache, audio_root):
    allocation_path = pinned_by_digest(spec, spec["source_allocation_sha256"])
    allocation = read(allocation_path)
    role = allocation["roles"]["joint"]
    require(role["role"] == "next_joint" and role["pair_count"] == 128 and role["writer_count"] == 32,
            "Registered source census")
    for name, digest in allocation["archive_sha256"].items():
        require(sha(cache / name) == digest, "Official QMNIST archive identity")
    with gzip.open(cache / "qmnist-test-labels-idx2-int.gz", "rb") as stream:
        raw = stream.read()
    require(struct.unpack(">III", raw[:12]) == (3074, 60000, 8), "QMNIST metadata header")
    metadata = tuple(struct.iter_unpack(">8I", raw[12:]))
    with gzip.open(cache / "qmnist-test-images-idx3-ubyte.gz", "rb") as stream:
        pixels = stream.read()
    require(struct.unpack(">IIII", pixels[:16]) == (2051, 60000, 28, 28), "QMNIST image header")
    require(len(pixels) == 16 + 60000 * 784, "QMNIST image bytes")
    labels, writers = [], []
    for position, index in enumerate(role["indices"]):
        row = metadata[index]
        digest = hashlib.sha256(pixels[16 + index * 784:16 + (index + 1) * 784]).hexdigest()
        identity = f"qmnist:test:{index}:nist:{row[5]}:writer:{row[2]}:{digest}"
        require(index >= 10000 and 0 <= row[0] <= 9 and row[6] == 0, "Valid extended source")
        require(identity == role["source_ids"][position] and digest == role["pixel_sha256"][position]
                and row[5] == role["nist_digit_ids"][position], "Source ID/metadata/pixel mismatch")
        labels.append(row[0]); writers.append(row[2])
    require(len(labels) == 256 and len(set(role["source_ids"])) == 256, "256 unique digits")
    require(writers[::2] == writers[1::2] == role["pair_writer_ids"], "Within-writer pairs")
    require(set(Counter(writers).values()) == {8} and len(set(writers)) == 32, "Four pairs per writer")
    require([writers[index * 8] for index in range(32)] == role["writer_ids"], "Writer ordering")
    swaps = swap_bits(239101, 128)
    expected = [labels[2 * case:2 * case + 2][::(-1 if swaps[case] else 1)] for case in range(128)]
    audio_path = pinned_by_digest(spec, spec["audio_source_allocation_sha256"])
    audio = read(audio_path)
    speakers = audio["joint_speakers"]
    require(len(speakers) == len(set(speakers)) == 24 and len(audio["roles"]["joint"]) == 240, "Speech source census")
    speech = {(row["speaker"], row["label"]): row for row in audio["roles"]["joint"]}
    require(set(speech) == {(speaker, label) for speaker in speakers for label in range(10)}, "Full speaker vocabularies")
    for row in speech.values():
        require(sha(audio_root / row["path"]) == row["sha256"], "Actual public speech bytes")
    # Union-find on actual writer/speaker identities, independently of stored cluster IDs.
    parent = {}
    def find(value):
        parent.setdefault(value, value)
        if parent[value] != value:
            parent[value] = find(parent[value])
        return parent[value]
    for group, writer in enumerate(role["writer_ids"]):
        parent[find(("writer", writer))] = find(("speaker", speakers[group % 24]))
    groups = defaultdict(list)
    for writer in role["writer_ids"]:
        groups[find(("writer", writer))].append(writer)
    require(len(groups) == 24 and Counter(map(len, groups.values())) == {1: 16, 2: 8}, "Connected graph structure")
    for case in range(128):
        writer = role["pair_writer_ids"][case]
        require(find(("writer", writer)) == find(("speaker", speakers[(case // 4) % 24])), "Connected label mapping")
    return role, expected, {"source_pairs": 128, "unique_source_digits": 256, "writers": 32,
            "speech_speakers": 24, "speech_source_files_verified": 240, "connected_clusters": 24,
            "cluster_writer_sizes": {"one_writer": 16, "two_writers": 8},
            "target_swap_bits_sha256": hashlib.sha256(bytes(swaps)).hexdigest()}


def parse_transcript(text):
    digits = []
    for token in re.findall(r"[a-z]+|[0-9]+", text.lower()):
        if token in WORDS:
            digits.append(WORDS.index(token))
        elif len(token) == 1 and token in "0123456789":
            digits.append(int(token))
        elif token not in {"the", "digit", "is"}:
            return None
    return digits[0] if len(digits) == 1 else None


def audit_output(row, expected, file_map, seen_files, event_cache, audit_counts):
    observed, media = row["observation"], row["media"]
    require(observed["target_supplied"] is False and observed["speech"]["target_supplied"] is False,
            "Target-free observation record")
    require(media["all_required_complete"] is True and media["lossless_roundtrip"] is True,
            "Original physical readback completed")
    require(set(media["files"]) == set(MODES), "Four actual output modalities")
    paths = {}
    for name, entry in media["files"].items():
        path = Path(entry["path"])
        require(not path.is_symlink() and path.is_file() and path.stat().st_size == entry["bytes"], "Actual output file shape")
        require(str(path) not in seen_files, "Output path reused")
        require(sha(path) == entry["sha256"] == file_map[str(path)], "Actual output SHA")
        seen_files.add(str(path)); paths[name] = path
    image = paths["image"].read_bytes()
    require(image[:8] == b"\x89PNG\r\n\x1a\n" and image[12:16] == b"IHDR", "PNG actual header")
    require(struct.unpack(">II", image[16:24]) == (56, 28) and tuple(image[24:26]) == (8, 0), "Grayscale PNG shape")
    match = CAPTION.fullmatch(paths["text"].read_text().strip())
    caption_digits = [int(match[1]), int(match[2])] if match else None
    relation = match[3] if match else None
    require(caption_digits == observed["caption_digits"] and relation == observed["caption_relation"], "Actual caption parse")
    with wave.open(str(paths["audio"]), "rb") as stream:
        require((stream.getnchannels(), stream.getsampwidth(), stream.getframerate(), stream.getnframes()) == (1, 2, 8000, 32000), "Actual audio sample clock")
        pcm = stream.readframes(32000)
    rms = []
    events = observed["speech"]["events"]
    require(len(events) == 2 and observed["speech"]["clock_boundaries_samples"] == [0, 16000, 32000], "Two actual event boundaries")
    for index, event in enumerate(events):
        block = pcm[index * 32000:(index + 1) * 32000]
        digest = hashlib.sha256(block).hexdigest()
        samples = [value[0] for value in struct.iter_unpack("<h", block)]
        rms.append(math.sqrt(math.fsum(value * value for value in samples) / len(samples)) / 32768)
        require(event["target_supplied"] is False and event["actual_event_samples"] == 16000
                and event["actual_event_pcm_sha256"] == digest, "Actual event PCM identity")
        predictions = {}
        for name in ("base.en", "small.en"):
            observation = event["observations"][name]
            transcript = " ".join(segment["text"].strip() for segment in observation["segments"]).strip()
            require(transcript == observation["transcript"], "Actual ASR segment transcript")
            predictions[name] = parse_transcript(transcript)
            require(predictions[name] == observation["prediction"] == event["predictions"][name], "Target-free component parser")
        first, second = predictions["base.en"], predictions["small.en"]
        predictions[PRIMARY] = second if first is None else first if second is None or first == second else None
        require(predictions == event["predictions"], "Target-free ensemble rule")
        if digest in event_cache:
            require(event_cache[digest] == predictions, "Same PCM received different observations")
        event_cache[digest] = predictions
        audit_counts["cache_hits" if event["cache_hit"] else "event_calls"] += 1
    for name in ("base.en", "small.en", PRIMARY):
        require(observed["speech"]["predictions"][name] == [event["predictions"][name] for event in events], "Ordered event predictions")
    content = observed["content_checks"]
    close(rms, content["audio_rms"], "Actual PCM RMS")
    require(content["nonempty_audio"] == (min(rms) > 1e-4), "Actual audio energy flag")
    require(content["moving_video"] == (min(content["distinct_frames_per_event"]) >= 6), "Recorded frame census flag")
    wanted_relation = "less" if expected[0] < expected[1] else "greater" if expected[0] > expected[1] else "equal"
    success = {"image": observed["image_digits"] == expected,
               "text": caption_digits == expected and relation == wanted_relation,
               "audio": observed["speech"]["predictions"][PRIMARY] == expected,
               "video": observed["video_digits"] == [digit for digit in expected for _ in range(10)]}
    joint = all(success.values()) and content["moving_video"] and content["nonempty_audio"]
    require(row["score"]["expected_after_observation"] == expected, "Actual source labels and fixed swap")
    require(row["score"]["success"] == success and row["score"]["joint_success"] == joint, "Independent actual-output scores")
    require(row["utility"] == sum(success.values()) / 4, "Independent four-modality utility")
    require(row["score"]["primary_observer"] == PRIMARY, "Named observer")
    secondary = {name: observed["speech"]["predictions"][name] == expected for name in ("base.en", "small.en")}
    require(row["score"]["secondary_audio_by_model"] == secondary
            and row["score"]["secondary_audio_success"] == secondary["base.en"], "Component observer attribution")
    clock = {"duration_ns": 4000000000, "sample_rate": 8000, "audio_samples": 32000,
             "video_fps": 5, "video_frames": 20,
             "events": [{"slot": 0, "audio_sample": 0, "video_frame": 0, "time_ns": 0},
                        {"slot": 1, "audio_sample": 16000, "video_frame": 10, "time_ns": 2000000000}]}
    require(observed["clock"] == media["clock"] == clock, "Recorded physical presentation clock")
    return {**row, "score": {"success": success, "joint_success": joint}, "utility": sum(success.values()) / 4}


def statistics(rows, gamma):
    size = len(rows)
    require(size > 0, "Nonempty statistics cell")
    utility_bins = Counter(round(row["utility"] * 4) for row in rows)
    return {"mean_utility": math.fsum(index * count / 4 for index, count in utility_bins.items()) / size,
            "CE": -math.log(math.fsum(count * math.exp(-gamma * index / 4) for index, count in utility_bins.items()) / size) / gamma,
            "joint_success": sum(row["score"]["joint_success"] for row in rows) / size,
            **{name + "_success": sum(row["score"]["success"][name] for row in rows) / size for name in MODES}}


def independent_primary(rows, spec):
    # Counts, not primary metric calls or primary per-row arrays, drive the bootstrap.
    cells = {}
    keys = ("mean_utility", "CE", "joint_success", *(name + "_success" for name in MODES))
    for profile in spec["profiles"]:
        cells[profile] = []
        for group in range(24):
            selected = [row for row in rows if row["profile"] == profile and row["connected_cluster"] == group]
            cells[profile].append({"n": len(selected), "utility": Counter(round(row["utility"] * 4) for row in selected),
                                  "joint": sum(row["score"]["joint_success"] for row in selected),
                                  "modal": {name: sum(row["score"]["success"][name] for row in selected) for name in MODES}})
    arms = {profile: statistics([row for row in rows if row["profile"] == profile], spec["gamma"]) for profile in spec["profiles"]}
    samples = {key: [] for key in keys}
    rng = np.random.default_rng(spec["bootstrap"]["seed"])
    for _ in range(spec["bootstrap"]["replicates"]):
        groups = [int(group) for group in rng.choice(24, 24, replace=True)]
        values = {}
        for profile in spec["profiles"]:
            chosen = [cells[profile][group] for group in groups]
            count = sum(cell["n"] for cell in chosen)
            histogram = Counter()
            for cell in chosen:
                histogram.update(cell["utility"])
            values[profile] = {"mean_utility": math.fsum(k * v / 4 for k, v in histogram.items()) / count,
                "CE": -math.log(math.fsum(v * math.exp(-spec["gamma"] * k / 4) for k, v in histogram.items()) / count) / spec["gamma"],
                "joint_success": sum(cell["joint"] for cell in chosen) / count,
                **{name + "_success": sum(cell["modal"][name] for cell in chosen) / count for name in MODES}}
        for key in keys:
            samples[key].append(values["entropic"][key] - values["mean"][key])
    alpha = (1 - spec["bootstrap"]["level"]) / 2
    differences = {key: {"estimate": arms["entropic"][key] - arms["mean"][key],
                         "interval": [quantile(samples[key], alpha), quantile(samples[key], 1 - alpha)]} for key in keys}
    return {"groups": 24, "arms": arms, "difference_entropic_minus_mean": differences}


def audit(args):
    process = read(args.process)
    require(process["exit_code"] == 0, "Wait for complete successful child exit")
    process_registration = args.process.with_suffix(".registration.json")
    require(sha(process_registration) == process["registration_sha256"], "Actual child registration")
    require(sha(args.process.with_suffix(".log")) == process["log_sha256"], "Actual complete child log")
    child_registration = read(process_registration)
    command = child_registration["command"]
    def argument(name):
        path = Path(command[command.index("--" + name) + 1])
        return (path if path.is_absolute() else Path(child_registration["cwd"]) / path).resolve()
    require(argument("output") == args.run.resolve() and argument("protocol") == args.protocol.resolve(), "Actual process paths")
    require(sha(args.protocol) == PROTOCOL_SHA, "Exact frozen prospective protocol")
    spec, primary = read(args.protocol), read(args.primary)
    require(primary["status"] == "completed" and primary["protocol_sha256"] == PROTOCOL_SHA, "Wait for completed primary analysis")
    require(len(spec["frozen_candidate_sha256"]) == 181, "181 prospective pins")
    for path, digest in spec["frozen_candidate_sha256"].items():
        require(Path(path).is_absolute() and sha(path) == digest, "Frozen input changed: " + path)
    for name in ("allocation", "audio-allocation", "qualification"):
        path = argument(name)
        require(spec["frozen_candidate_sha256"].get(str(path)) == sha(path), "Actual source/qualification binding")
    training_path = argument("training") / "RESULTS.json"
    require(spec["frozen_candidate_sha256"][str(training_path)] == sha(training_path) == primary["training_sha256"], "Actual training identity")
    training = read(training_path)
    require(training["status"] == "completed" and set(training["arms"]) == {f"{s}/{p}" for s in (17, 29, 43) for p in ("mean", "entropic")}, "Six trained arms")
    training_registration = training_path.parent / "REGISTRATION.json"
    require(sha(training_registration) == training["registration_sha256"], "Training registration")
    for path, digest in read(training_registration)["source_pins"].items():
        require(sha(path) == digest, "Original training code")
    for seed in (17, 29, 43):
        paired = [training["arms"][f"{seed}/{profile}"] for profile in ("mean", "entropic")]
        require(all(paired[0][name] == paired[1][name] for name in ("initial_sha256", "schedule_sha256")), "Paired initialization/schedule")
        for profile, arm in zip(("mean", "entropic"), paired):
            path = training_path.parent / f"seed-{seed}" / profile / "model.pt"
            require(Path(arm["checkpoint"]).resolve() == path.resolve() and sha(path) == arm["checkpoint_sha256"]
                    == spec["frozen_candidate_sha256"][str(path)], "Actual trained checkpoint")
            require(arm["seed"] == seed and arm["profile"] == profile, "Training arm labels")
    require(argument("cache") == args.cache.resolve() and argument("audio-root") == args.audio_root.resolve(), "Actual source root arguments")
    source_role, targets, census = source_census(spec, args.cache, args.audio_root)
    registration, complete = read(args.run / "registration.json"), read(args.run / "completion.json")
    require(registration["protocol_sha256"] == PROTOCOL_SHA and registration["spec"] == spec, "Actual run registration")
    require(complete["status"] == "completed" and complete["actual_outputs"] == len(complete["rows"]) == 768, "Full output census")
    require(primary["completion_sha256"] == sha(args.run / "completion.json"), "Primary exact completion binding")
    expected_ids = {(seed, profile, case) for seed in spec["seeds"] for profile in spec["profiles"] for case in range(128)}
    reduced = {(row["seed"], row["profile"], row["case"]): row for row in complete["rows"]}
    require(set(reduced) == expected_ids and len(reduced) == 768, "Exactly one source/seed/profile output")
    seen_files, events, counts, rows, raw_pins = set(), {}, Counter(), [], {}
    for seed, profile, case in sorted(expected_ids):
        path = args.run / "raw" / f"seed-{seed}" / profile / f"{case:04d}" / "observation.json"
        raw = read(path); raw_pins[str(path)] = sha(path)
        require({key: raw[key] for key in reduced[(seed, profile, case)]} == reduced[(seed, profile, case)], "Full/reduced actual record equality")
        require(raw["source_ids"] == source_role["source_ids"][2 * case:2 * case + 2], "Actual source IDs")
        require(raw["writer_group"] == case // 4 and raw["connected_cluster"] == (case // 4) % 24, "Writer/connected assignment")
        require(raw["input_route"] == spec["input_routes"][case % 4], "Actual route assignment")
        require(raw["media"]["bindings"]["request_sha256"] == hashlib.sha256(f"joint:{seed}:{case}".encode()).hexdigest(), "Actual request binding")
        rows.append(audit_output(raw, targets[case], complete["physical_codec_files_sha256"], seen_files, events, counts))
    require(seen_files == set(complete["physical_codec_files_sha256"]) and len(seen_files) == 3072, "3072 unique actual codec files")
    require(counts["event_calls"] == complete["actual_event_asr_calls"] == len(events)
            and counts["cache_hits"] == complete["actual_event_cache_hits"]
            and sum(counts.values()) == 1536, "Full actual ASR/cache accounting")
    recalculated = independent_primary(rows, spec)
    close(recalculated, primary["primary"], "Independent primary statistics")
    difference = recalculated["difference_entropic_minus_mean"]
    gates = {"CE_superiority": difference["CE"]["interval"][0] > 0,
             "joint_success_noninferiority": difference["joint_success"]["interval"][0] >= 0}
    require(gates == primary["registered_gates"] and all(gates.values()) == primary["quality_claim_eligible"], "Original exact gates")
    for profile in spec["profiles"]:
        selected = [row for row in rows if row["profile"] == profile]
        for key, values, field in (("by_route", spec["input_routes"], "input_route"), ("by_seed", spec["seeds"], "seed")):
            for value in values:
                result = statistics([row for row in selected if row[field] == value], spec["gamma"])
                close(result, primary["descriptive_only"][profile][key][str(value)], "Descriptive metric cell")
        for field in ("generation_and_codec_ns", "whole_request_ns"):
            values = [row[field] / 1e6 for row in selected]
            result = {"mean": math.fsum(values) / len(values), "p50": quantile(values, .5), "p95": quantile(values, .95)}
            close(result, primary["descriptive_only"][profile][field.replace("_ns", "_ms")], "Descriptive cost", tolerance=1e-8)
    return {"schema": "hepta.next.joint-independent-completed-audit.v1", "status": "passed",
            "audit_source_sha256": sha(__file__), "protocol_sha256": PROTOCOL_SHA,
            "primary_sha256": sha(args.primary), "completion_sha256": sha(args.run / "completion.json"),
            "process_receipt_sha256": sha(args.process), "training_results_sha256": sha(training_path),
            "all_181_frozen_inputs_verified": True, "six_matched_training_arms_verified": True,
            "source_census": census, "actual_outputs": 768, "actual_codec_files_verified": 3072,
            "actual_full_records_verified": 768, "full_record_sha256": raw_pins,
            "actual_event_cache": dict(counts), "unique_actual_event_pcm": len(events),
            "independent_primary": recalculated, "registered_gates": gates,
            "quality_claim_eligible": all(gates.values()), "numeric_comparison_tolerance": 1e-12,
            "primary_metric_functions_imported": False, "models_asr_codecs_or_primary_analysis_rerun": False,
            "scope": ["Recomputed scores from recorded target-free predictions bound to actual media file bytes",
                      "Independently parsed actual captions, WAV PCM, ASR transcripts, ensemble decisions and source labels",
                      "Image/video neural classifications and MP4 decoded frames are original frozen observations; this audit does not rerun classifiers or codecs",
                      "Cluster histogram bootstrap preserves unequal connected-group sizes and the full fixed trained seed panel",
                      "Cost comparisons remain descriptive because arm order was fixed"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "protocol", "primary", "process", "cache", "audio-root", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    require(not args.output.exists(), "Never overwrite an independent audit attempt")
    started = time.time_ns()
    try:
        result = audit(args)
    except BaseException as error:
        result = {"schema": "hepta.next.joint-independent-completed-audit.v1", "status": "failed",
                  "audit_source_sha256": sha(__file__), "error": repr(error), "traceback": traceback.format_exc()}
        raise
    finally:
        result["started_unix_ns"] = started
        result["ended_unix_ns"] = time.time_ns()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x") as stream:
            json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
    print(json.dumps({"status": result["status"], "registered_gates": result["registered_gates"], "audit_sha256": sha(args.output)}))


if __name__ == "__main__":
    main()
