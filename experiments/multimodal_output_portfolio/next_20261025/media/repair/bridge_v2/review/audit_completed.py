"""Read-only stdlib census of the completed bridge confirmation and identity addendum."""

from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import re
import struct
import wave


REPO = Path(__file__).resolve().parents[7]
AREA = REPO / "experiments/multimodal_output_portfolio/next_20261025"
RUN = Path("/tmp/hepta-ndu-next-media-cache/repair-confirmation-001")
CONTINUITY = AREA / "media/dependency_continuity"
MODES = ("image", "text", "audio", "video", "audio_video")
PRIMARY = "consensus_or_single_v3"
WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""): h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def first_swap(seed):
    state = [seed]
    for i in range(1, 398):
        x = state[-1]; state.append((1812433253 * (x ^ (x >> 30)) + i) & 0xffffffff)
    x = state[397] ^ (((state[0] & 0x80000000) | (state[1] & 0x7fffffff)) >> 1) ^ (0x9908b0df if state[1] & 1 else 0)
    x ^= x >> 11; x ^= (x << 7) & 0x9d2c5680; x ^= (x << 15) & 0xefc60000; x ^= x >> 18
    return x % 2


def parsed(text):
    digits = []
    for token in re.findall(r"[a-z]+|[0-9]+", text.lower()):
        if token in WORDS: digits.append(WORDS.index(token))
        elif len(token) == 1 and token in "0123456789": digits.append(int(token))
        elif token not in {"the", "digit", "is"}: return None
    return digits[0] if len(digits) == 1 else None


def main():
    base_path, final_path = (CONTINUITY / (name + "_CONFIRMATION_PROTOCOL.json") for name in ("BASE", "FINAL"))
    base, final, manifest = read(base_path), read(final_path), read(CONTINUITY / "ADDENDUM.json")
    assert sha(final_path) == "163297a3e210f800a2e7bd6e21aff58708d058f264eab17b5fe56ece3d06eb32"
    assert {k:v for k,v in final.items() if k not in ("frozen_candidate_sha256", "dependency_continuity")} == {k:v for k,v in base.items() if k != "frozen_candidate_sha256"}
    additions = {row["path"]:row["sha256"] for row in manifest["source_closure"]}
    additions.update(manifest["frozen_evidence_sha256"]); additions.update(manifest["frozen_guard_sha256"])
    additions[str((CONTINUITY / "ADDENDUM.json").resolve())] = sha(CONTINUITY / "ADDENDUM.json")
    additions[str(base_path)] = sha(base_path)
    additions[manifest["qualification_process_receipt"]] = sha(manifest["qualification_process_receipt"])
    assert final["frozen_candidate_sha256"] == dict(base["frozen_candidate_sha256"], **additions)
    assert len(base["frozen_candidate_sha256"]) == 114 and len(final["frozen_candidate_sha256"]) == 149
    assert all(sha(path) == value for path,value in final["frozen_candidate_sha256"].items())
    comparison_path = RUN.parent / "repair-confirmation-base-final-comparison.json"
    comparison = read(comparison_path)
    assert comparison["base_protocol_sha256"] == sha(base_path) and comparison["final_protocol_sha256"] == sha(final_path)
    assert comparison["status"] == "passed" and comparison["source_role_opened"] is False
    registration, summary, analysis = (read(RUN / name) for name in ("registration.json", "summary.json", "ANALYSIS.json"))
    assert comparison["recorded_unix_ns"] < registration["started_unix_ns"]
    assert summary["status"] == "completed" and summary["phase"] == "confirmation" and summary["outputs"] == 640
    assert summary["pairs"] == 128 and analysis["outputs"] == 640
    allocation = read(AREA / "SOURCE_ALLOCATION.json")
    assert sha(AREA / "SOURCE_ALLOCATION.json") == final["source_allocation_sha256"]
    role = allocation["roles"]["media"]
    audio = read(AREA / "media/AUDIO_SOURCE_ALLOCATION.json")
    speech = {(r["speaker"],r["label"]):r for r in audio["roles"]["media"]}
    cache = REPO.parent / "ndu-next-assets/qmnist"
    meta_path = cache / "qmnist-test-labels-idx2-int.gz"
    assert sha(meta_path) == allocation["archive_sha256"][meta_path.name]
    metadata = tuple(struct.iter_unpack(">8I", gzip.decompress(meta_path.read_bytes())[12:]))
    counts = {mode: Counter() for mode in MODES}; writers = defaultdict(set)
    inputs, outputs, rows_pins, joint_per_case = {}, {}, {}, defaultdict(list)
    def verify_bundle(bundle, collection):
        assert set(bundle["files"]) == {"text", "image", "audio", "video"}
        assert bundle["lossless_roundtrip"] is True and bundle["all_required_complete"] is True
        for entry in bundle["files"].values():
            path = entry["path"]
            if path not in collection:
                assert Path(path).stat().st_size == entry["bytes"] and sha(path) == entry["sha256"]
                collection[path] = entry["sha256"]
            assert collection[path] == entry["sha256"]
    for case in range(128):
        expected = [metadata[index][0] for index in role["indices"][2*case:2*case+2]]
        if first_swap(23717 + case): expected.reverse()
        expected_writer = role["pair_writer_ids"][case]
        speaker = audio["media_speakers"][role["writer_ids"].index(expected_writer)]
        for mode in MODES:
            path = RUN / f"row-{case:03d}-{mode}.json"; row = read(path); rows_pins[str(path)] = sha(path)
            assert row["index"] == case and row["mode"] == mode and row["writer"] == expected_writer
            assert row["source_ids"] == [role["source_ids"][2*case:2*case+2]]
            assert row["speech_speakers"] == [speaker,speaker]
            assert row["speech_source_sha256"] == [speech[(speaker,d)]["sha256"] for d in expected]
            writers[expected_writer].add(speaker)
            verify_bundle(row["input"], inputs); bundle = row["generation"]["output"]; verify_bundle(bundle, outputs)
            assert Path(row["input"]["files"]["text"]["path"]).read_text() == f"keep left {expected[0]} right {expected[1]}"
            observed = row["observation"]
            assert observed["target_supplied"] is False and observed["speech"]["target_supplied"] is False
            match = re.fullmatch(r"left ([0-9]) right ([0-9]) relation (less|equal|greater)", Path(bundle["files"]["text"]["path"]).read_text().strip())
            actual_digits = [int(match[1]),int(match[2])] if match else None
            actual_relation = match[3] if match else None
            assert actual_digits == observed["caption_digits"] and actual_relation == observed["caption_relation"]
            with wave.open(bundle["files"]["audio"]["path"], "rb") as stream:
                assert (stream.getnchannels(),stream.getsampwidth(),stream.getframerate(),stream.getnframes()) == (1,2,8000,32000)
                pcm = stream.readframes(32000)
            for index,event in enumerate(observed["speech"]["events"]):
                assert event["target_supplied"] is False
                assert hashlib.sha256(pcm[index*32000:(index+1)*32000]).hexdigest() == event["actual_event_pcm_sha256"]
                predictions = {}
                for name in ("base.en", "small.en"):
                    value = event["observations"][name]
                    transcript = " ".join(s["text"].strip() for s in value["segments"]).strip()
                    assert transcript == value["transcript"]
                    predictions[name] = parsed(transcript)
                    assert predictions[name] == value["prediction"] == event["predictions"][name]
                first,second = predictions["base.en"],predictions["small.en"]
                predictions[PRIMARY] = second if first is None else first if second is None or first == second else None
                assert predictions == event["predictions"]
            for name in ("base.en", "small.en", PRIMARY):
                assert observed["speech"]["predictions"][name] == [e["predictions"][name] for e in observed["speech"]["events"]]
            relation = "less" if expected[0] < expected[1] else "greater" if expected[0] > expected[1] else "equal"
            success = {"text":actual_digits == expected and actual_relation == relation,
                       "image":observed["image_digits"] == expected,
                       "audio":observed["speech"]["predictions"][PRIMARY] == expected,
                       "video":observed["video_digits"] == [d for d in expected for _ in range(10)]}
            checks = observed["content_checks"]
            joint = all(success.values()) and checks["moving_video"] and checks["nonempty_audio"]
            assert row["score"]["expected_after_observation"] == expected and row["score"]["success"] == success
            assert row["score"]["joint_success"] == joint and row["score"]["primary_observer"] == PRIMARY
            counts[mode].update({**success,"joint":joint,"tasks":1})
            counts[mode]["secondary_audio"] += observed["speech"]["predictions"]["base.en"] == expected
            joint_per_case[case].append(joint)
    assert len(writers) == 32 and all(len(s) == 1 for s in writers.values()) and len({next(iter(s)) for s in writers.values()}) == 32
    assert len(inputs) == 512 and len(outputs) == 2560 and not set(inputs).intersection(outputs)
    for mode, count in counts.items():
        assert count["tasks"] == 128 and count["joint"] / 128 == summary["strict_joint_by_input"][mode]
        assert count["joint"] == analysis["per_mode"][mode]["strict_joint_correct"]
        assert {name:count[name] for name in ("text","image","audio","video")} == analysis["per_mode"][mode]["component_correct"]
        assert count["secondary_audio"] == analysis["per_mode"][mode]["secondary_audio_correct"]
    assert sum(all(values) for values in joint_per_case.values()) == analysis["tasks_successful_in_all_five_routes"]
    assert all(count["joint"] / 128 >= .75 for count in counts.values()) == summary["gates"]["per_mode_strict_joint_min_075"]
    assert all(summary["gates"].values()) == summary["all_media_sample_gates_pass"] == analysis["all_original_numeric_sample_gates_pass"]
    census = read(RUN / "TASK_ARTIFACT_CENSUS.json")
    assert (census["source_tasks"],census["generated_output_bundles"],census["input_codec_artifacts"],census["generated_output_codec_artifacts"],census["disjoint_task_artifacts"]) == (128,640,512,2560,3072)
    result = {"schema":"hepta.next.media-independent-completed-review.v1","status":"passed", "audit_source_sha256":sha(__file__),
              "final_protocol_sha256":sha(final_path),"base_protocol_sha256":sha(base_path),"comparison_receipt_sha256":sha(comparison_path),
              "all_149_pins_verified":True,"exact_base_final_comparison":True,"summary_sha256":sha(RUN/'summary.json'),
              "analysis_sha256":sha(RUN/'ANALYSIS.json'),"row_sha256":rows_pins,"per_mode_independent_counts":{k:dict(v) for k,v in counts.items()},
              "source_tasks":128,"output_bundles":640,"writer_speaker_clusters":32,"input_codec_files":512,"output_codec_files":2560,
              "actual_task_artifacts_verified":3072,"all_five_routes_successful_tasks":sum(all(v) for v in joint_per_case.values()),
              "new_models_asr_or_codecs_executed":False,"candidate_protocol_or_thresholds_changed":False,
              "limits":["Recomputed scores from actual caption/PCM, frozen target-free neural prediction records and official source metadata",
                        "No independent image/video classification or video codec rerun; original physical readback records are retained",
                        "Per-route bootstrap intervals were not recomputed in this count/identity review; original sample gates unchanged",
                        "Input materializations are not generated outputs, and repeated routes are not independent source tasks"]}
    destination = Path(__file__).with_name('COMPLETED_REVIEW.json')
    with destination.open('x') as stream: json.dump(result,stream,indent=2,sort_keys=True);stream.write('\n')
    print(json.dumps({"status":"passed","counts":{k:v['joint'] for k,v in counts.items()},"review_sha256":sha(destination)}))


if __name__ == "__main__":
    main()
