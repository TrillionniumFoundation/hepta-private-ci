"""Reopen source media and deliveries and rescore without experiment scorers."""
import argparse
from collections import defaultdict
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import time

import cv2
import numpy as np
from PIL import Image


RECORDED_ROOT = Path("/workspace/scratch/95988d8d3ab1")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def distance(left, right):
    # A full edit-distance matrix, independently implemented from the study scorer.
    matrix = np.empty((len(left)+1, len(right)+1), dtype=np.int32)
    matrix[:, 0] = np.arange(len(left)+1)
    matrix[0, :] = np.arange(len(right)+1)
    for i in range(1, len(left)+1):
        for j in range(1, len(right)+1):
            matrix[i, j] = min(matrix[i-1, j]+1, matrix[i, j-1]+1,
                matrix[i-1, j-1]+int(left[i-1] != right[j-1]))
    return int(matrix[-1, -1])


def normalize_field(name, value):
    if value is None:
        return ""
    if name == "total":
        try:
            return str(Decimal(value.replace(",", "").strip()).normalize())
        except InvalidOperation:
            pass
    return "".join(c for c in value.upper() if "A" <= c <= "Z" or "0" <= c <= "9")


class Audit:
    def __init__(self, workspace):
        self.workspace = workspace
        self.assets = workspace/"natural-continuation-assets"
        self.runs = workspace/"natural-continuation-runs"
        self.checked_files = {}

    def path(self, recorded):
        path = Path(recorded)
        return self.workspace/path.relative_to(RECORDED_ROOT)

    def check_file(self, recorded, expected):
        path = self.path(recorded)
        if path not in self.checked_files:
            self.checked_files[path] = digest(path)
        assert self.checked_files[path] == expected, str(path)
        return path

    def registration(self, run):
        record = load(run/"FROZEN_REGISTRATION.json")
        for name, expected in record["source_sha256"].items():
            assert digest(run/"executed-source"/name) == expected, name
        return {"source_files_rehashed": len(record["source_sha256"]),
            "registered_ns": record["registered_ns"], "registration_sha256": digest(run/"FROZEN_REGISTRATION.json")}

    def grid(self, rows, identities, arms, repetitions):
        observed = [(r["id"], r["arm"], r["repetition"]) for r in rows]
        expected = {(identity, arm, repetition) for identity in identities
            for arm in arms for repetition in range(repetitions)}
        assert len(observed) == len(set(observed)) and set(observed) == expected

    def source_media(self):
        manifests = {name: load(self.assets/name/"MANIFEST.json")
            for name in ("speech", "document", "cascade", "video")}
        audio, images = set(), set()
        for name, manifest in manifests.items():
            for record in manifest["files"]:
                self.check_file(record["path"], record["sha256"])
            for row in manifest.get("speech", []):
                audio.add(self.path(row["path"]))
            for row in manifest.get("documents", []):
                images.add(self.path(row["path"]))
        for path in sorted(audio):
            subprocess.run(["ffmpeg", "-v", "error", "-threads", "1", "-i", str(path),
                "-threads", "1", "-f", "null", "-"], check=True, capture_output=True)
        for path in images:
            with Image.open(path) as image:
                image.load()
        speech = manifests["speech"]
        old = set(speech["excluded_historical_speakers"])
        fit, test = set(speech["fit_speakers"]), set(speech["test_speakers"])
        assert not fit & test and not old & (fit | test)
        cascade = manifests["cascade"]["speech"]
        groups = {role: {r["speaker_id"] for r in cascade if r["role"] == role}
            for role in ("train", "validation", "test")}
        assert not groups["train"] & groups["validation"]
        assert not groups["test"] & (groups["train"] | groups["validation"] | test | old)
        docs = manifests["document"]
        merchants = [r["merchant_group"] for r in docs["documents"]]
        assert len(set(merchants)) == len(merchants)
        assert not set(merchants) & set(docs["excluded_historical_merchants"])
        return manifests, {"hashed_source_files": len(self.checked_files),
            "fully_decoded_FLAC_sources": len(audio), "reopened_receipt_images": len(images),
            "speech_fit_test_historical_speaker_disjoint": True,
            "cascade_new_test_speakers_disjoint_from_previous_and_development": True,
            "recorded_merchant_strings_disjoint": True,
            "broader_parent_company_template_deduplication_proven": False}

    def transcript(self, row, cascade=False):
        path_key, hash_key = ("final_path", "final_sha256") if cascade else ("output_path", "output_sha256")
        path = self.check_file(row[path_key], row[hash_key])
        observed = path.read_text(encoding="utf-8").strip()
        assert observed == row["transcript"]
        calls = row["calls"] if cascade else [row]
        for call in calls:
            self.check_file(call["output_path"], call["output_sha256"])
            assert call["encoder_calls"] == len(call["encodings"])
            assert call["decoder_calls"] == len(call["generations"])
            assert len({r["encoded_sha256"] for r in call["encodings"]}) == 1
            for generation in call["generations"]:
                assert not generation["private_reference_received"]
                assert self.path(generation["output_path"]).read_text().strip() == generation["transcript"]
        return observed

    def speech(self, manifest, name, cascade=False):
        run = self.runs/name
        rows, result = load(run/"ROWS.json"), load(run/"RESULT.json")
        sources = {r["id"]: r for r in manifest["speech"] if r["role"] == "test"}
        arms = ("fixed_tiny", "fixed_base", "learned_budget", "matched_random_budget") if cascade else (
            "fixed_greedy", "fixed_beam5", "cached_continuation", "reencoded_continuation")
        self.grid(rows, sources, arms, 3)
        by_arm = defaultdict(list)
        for row in rows:
            delivered = self.transcript(row, cascade)
            truth = re.findall(r"[a-z0-9']+", sources[row["id"]]["reference"].lower())
            actual = re.findall(r"[a-z0-9']+", delivered.lower())
            errors = distance(truth, actual)
            assert (errors, len(truth)) == (row["word_errors"], row["reference_words"])
            assert abs(errors/max(1, len(truth))-row["WER"]) < 1e-12
            delivered_ns = row["delivered_before_scoring_ns" if cascade else "delivered_before_private_scoring_ns"]
            assert delivered_ns < row["private_score_ns" if cascade else "private_scoring_ns"]
            if row["repetition"] == 0:
                by_arm[row["arm"]].append((errors, len(truth)))
        scores = {arm: {"errors": sum(a for a,b in group), "words": sum(b for a,b in group),
            "WER": sum(a for a,b in group)/sum(b for a,b in group)} for arm, group in by_arm.items()}
        for arm, score in scores.items():
            assert abs(score["WER"]-result["summary"][arm]["micro_WER"]) < 1e-12
        gate = load(run/"GATE_FROZEN.json")
        frozen_ns = gate["frozen_ns" if cascade else "fitting_complete_ns"]
        assert frozen_ns < min(row["delivered_before_scoring_ns" if cascade else "delivered_before_private_scoring_ns"] for row in rows)
        batches = self.batch_costs(rows, cascade=True) if cascade else None
        return {"deliveries_reopened": len(rows), "independent_test_speakers": len({r["speaker_id"] for r in sources.values()}),
            "complete_unique_grid": True, "rescored": scores, "batch_audit": batches,
            "snapshot_audit": self.registration(run), "private_scoring_after_delivery": True}

    def cache(self):
        run = self.runs/"cache-mechanism-001"
        rows, protocol = load(run/"ROWS.json"), load(run/"PROTOCOL.json")
        self.grid(rows, protocol["source_ids"], ("cached_continuation", "reencoded_continuation"), 3)
        by_source = defaultdict(list)
        for row in rows:
            by_source[row["id"]].append(self.transcript(row))
            assert row["gate"]["continue"]
            assert row["encoder_calls"] == (1 if row["arm"] == "cached_continuation" else 2)
            assert row["decoder_calls"] == 2
        assert all(len(set(texts)) == 1 for texts in by_source.values())
        code = Path(__file__).parent
        for name, expected in protocol["source_sha256"].items():
            assert digest(code/name) == expected
        return {"actual_forced_continue_episodes": len(rows), "paired_text_equality": True,
            "encoder_hash_equality": True, "correct_encoder_and_decoder_counts": True,
            "registered_code_hashes_match_current_unchanged_files": True,
            "development_mechanism_only": True}

    def documents(self, manifest):
        run = self.runs/"document-002"
        rows = load(run/"ROWS.json")
        sources = {r["id"]: r for r in manifest["documents"] if r["role"] == "test"}
        arms = ("original_rules", "learned_base", "learned_all_refine", "learned_selective")
        self.grid(rows, sources, arms, 2)
        for row in rows:
            folder = self.path(row["output_directory"])
            answer = self.check_file(str(RECORDED_ROOT/folder.relative_to(self.workspace)/"DELIVERED.json"), row["answer_sha256"])
            image_path = self.check_file(str(RECORDED_ROOT/folder.relative_to(self.workspace)/"DELIVERED.jpg"), row["image_sha256"])
            actual = load(answer)
            assert not actual["reference_received"] and actual["answers"] == row["answers"]
            with Image.open(image_path) as image:
                image.load()
                size = image.size
            source = sources[row["id"]]
            with Image.open(self.path(source["path"])) as image:
                assert size == image.size
            qualities, exact = [], []
            for field, target in source["reference"].items():
                truth = normalize_field(field, target)
                if not truth:
                    continue
                prediction = normalize_field(field, actual["answers"][field])
                match = prediction == truth
                similarity = max(0, 1-distance(truth, prediction)/max(len(truth), len(prediction), 1))
                qualities.append(.5*match+.5*similarity)
                exact.append(match)
            assert abs(sum(qualities)/len(qualities)-row["quality"]) < 1e-12
            assert abs(sum(exact)/len(exact)-row["field_exact"]) < 1e-12
            assert len(list(folder.rglob("PUBLIC_OCR.json"))) == row["actual_OCR_calls"]
            assert row["delivered_ns"] < row["private_score_ns"]
        return {"JSON_JPEG_pairs_reopened_and_rehashed": len(rows), "independent_char_quality_recomputed": True,
            "complete_unique_grid": True, "actual_OCR_call_counts_reconciled": True,
            "field_exact_definition": "Macro mean of each document's observed-field fraction; all test fields observed here",
            "snapshot_audit": self.registration(run)}

    def batch_costs(self, rows, cascade=False):
        grouped = defaultdict(list)
        for row in rows:
            path = self.path(row["final_path"] if cascade else row["output_path"])
            grouped[path.parent.parent].append(row)
        max_error = 0
        for folder, group in grouped.items():
            runtime = load(folder/"BATCH_RUNTIME.json")
            for metric in ("cpu", "wall"):
                key = f"batch_{metric}_seconds" if cascade else f"whole_{metric}_seconds"
                error = abs(sum(r[f"whole_{metric}_seconds"] for r in group)-runtime[key])
                max_error = max(max_error, error)
                assert error < 1e-9
            if cascade:
                decision = load(folder/"BATCH_DECISION.json")
                assert not decision["targets_or_base_outputs_received"]
                if group[0]["arm"] in {"learned_budget", "matched_random_budget"}:
                    assert sum(r["actual_base_calls"] for r in group) == decision["acquisition_budget"]
                    assert {r["id"] for r in group if r["actual_base_calls"]} == set(decision["selected_source_ids"])
            else:
                decision = load(folder/"DECISION.json")
                assert not decision["private_target_received"] and decision["flow_calls_before_allocation"] == 0
                assert {r["id"] for r in group if r["expensive_calls"]} == set(decision["selected_ids"])
                assert decision["frozen_before_generation_ns"] < min(r["delivered_ns"] for r in group)
        return {"batches": len(grouped), "maximum_cost_reconciliation_error": max_error,
            "actual_expensive_call_budget_reconciled": True,
            "matched_budget_scope": "Acquisition-call count; not exact CPU, FLOPs, or response latency"}

    def video(self, manifest):
        cv2.setNumThreads(1)
        canonical_checked = 0
        for clip in manifest["clips"]:
            samples = [r for r in manifest["samples"] if r["source"] == clip["name"]]
            targets = {r["target_index"] for r in samples}
            public = {r["target_index"]+offset for r in samples for offset in (-2, 2)}
            assert not targets & public
            files = defaultdict(list)
            for row in samples:
                for key, offset in (("left", -2), ("private_target", 0), ("right", 2)):
                    files[row["target_index"]+offset].append(self.path(row[key]))
            capture = cv2.VideoCapture(str(self.path(clip["path"])))
            for index in range(max(files)+1):
                ok, frame = capture.read()
                assert ok
                if index not in files:
                    continue
                height = round(frame.shape[0]*256/frame.shape[1])
                canonical = cv2.cvtColor(cv2.resize(frame, (256, height), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
                for path in files[index]:
                    with Image.open(path) as image:
                        assert np.array_equal(np.asarray(image), canonical)
                    canonical_checked += 1
            capture.release()
        run = self.runs/"video-001"
        rows, result = load(run/"ROWS.json"), load(run/"RESULT.json")
        sources = {r["id"]: r for r in manifest["samples"] if r["role"] == "test"}
        arms = ("fixed_blend", "fixed_initial_mixer", "fixed_pure_flow", "fixed_learned_flow", "learned_budget", "matched_random_budget")
        self.grid(rows, sources, arms, 2)
        for row in rows:
            path = self.check_file(row["output_path"], row["output_sha256"])
            with Image.open(path) as image:
                observed = np.asarray(image.convert("RGB"), dtype=np.int64)
            with Image.open(self.path(sources[row["id"]]["private_target"])) as image:
                target = np.asarray(image.convert("RGB"), dtype=np.int64)
            mse = float(np.mean((observed-target)**2)/65025)
            psnr = -10*math.log10(max(mse, 1e-12))
            assert abs(mse-row["pixel_MSE"]) < 1e-12 and abs(psnr-row["PSNR"]) < 1e-9
            assert not row["private_target_received"] and row["delivered_ns"] < row["private_scoring_ns"]
        weights = np.load(run/"PIXEL_MIXER.npy", allow_pickle=False)
        assert digest(run/"PIXEL_MIXER.npy") == result["training"]["checkpoint_sha256"]
        assert hashlib.sha256(weights.tobytes()).hexdigest() == result["training"]["final_parameter_sha256"]
        assert result["training"]["initial_parameter_sha256"] != result["training"]["final_parameter_sha256"]
        return {"canonical_source_PNGs_reconstructed_from_videos": canonical_checked,
            "every_source_target_endpoint_intersection_empty": True,
            "delivered_PNGs_reopened_rehashed_independently_rescored": len(rows),
            "complete_unique_grid": True, "source_clusters": len({r["source"] for r in sources.values()}),
            "actual_changed_mixer_checkpoint_verified": True, "batch_audit": self.batch_costs(rows),
            "snapshot_audit": self.registration(run)}

    def run(self):
        manifests, sources = self.source_media()
        return {"schema": "hepta.ndu.natural.independent-output-audit.v1", "audited_ns": time.time_ns(),
            "scoring_implementation_imports_experiment_scorers": False, "sources": sources,
            "speech": self.speech(manifests["speech"], "speech-001"), "cache_mechanism": self.cache(),
            "document": self.documents(manifests["document"]),
            "cascade": self.speech(manifests["cascade"], "cascade-001", cascade=True),
            "video": self.video(manifests["video"]), "status": "passed"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = Audit(args.workspace).run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
    print(json.dumps(result, indent=2))
