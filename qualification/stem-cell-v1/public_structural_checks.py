"""Adversarial local mechanism tests; no network or pretrained-model claim."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import torch
from safetensors.torch import load, save

from development_study import fit_and_seal, prepare_views
from development_study_checks import fixture_rows, fixture_features
from development_study_data import StudyConfig, audit_rows, canonical, phase, write_once
from development_study_replay import replay
from public_structural_data import INTENTS, PARTITIONS, publisher_rows, prepare_dataset
from public_structural_stage import (MODEL_FILES, REVISION, WEIGHTS_SHA256,
                                     download_checked, model_pins)


def public_fixture():
    # Explicit artificial publisher-shaped records, not authentic CLINC samples.
    return {p: [[f"fixture {p} {label} {i}", label] for label in INTENTS for i in range(n)]
            for p, n in PARTITIONS.items()}


class PublisherDataChecks(unittest.TestCase):
    def test_fixed_census_original_validation_test_no_fake_dates(self):
        data = public_fixture()
        rows, config, provenance = publisher_rows(data)
        self.assertEqual(len(rows), 1200)
        self.assertEqual({p: sum(phase(r) == p for r in rows) for p in ("base", "adapt", "extra", "calibration", "held_out")},
                         {"base": 320, "adapt": 240, "extra": 240, "calibration": 160, "held_out": 240})
        self.assertTrue(all(r["observed_at"] is None for r in rows))
        self.assertTrue(all(item["publisher_partition"] == "test" for item in provenance["lineage"]
                            if item["sample_id"].startswith("clinc:test:")))
        self.assertEqual(config.time_basis, "publisher_partition")
        self.assertFalse(provenance["content_groups_are_independent_speakers"])

    def test_public_profile_cannot_claim_future_or_insert_dates(self):
        rows, config, _ = publisher_rows(public_fixture())
        for changes in ({"observed_at": "2026-10-13T00:00:00Z"}, {"split": "future_1"}):
            altered = deepcopy(rows)
            altered[-1].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                audit_rows(altered, config)

    def test_observed_profile_not_relaxed(self):
        rows, _, _ = publisher_rows(public_fixture())
        with self.assertRaises(ValueError):
            audit_rows(rows, StudyConfig(classes=8))
        for origin in ("synthetic_fixture", "prospective_hepta"):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                StudyConfig(origin=origin, time_basis="publisher_partition").validate()

    def test_overlap_is_not_silently_filtered(self):
        data = public_fixture()
        data["test"][0][0] = data["train"][0][0]
        with self.assertRaises(ValueError):
            publisher_rows(data)

    def test_missing_class_or_row_is_not_imputed(self):
        for p in PARTITIONS:
            data = public_fixture()
            data[p].pop()
            with self.subTest(partition=p), self.assertRaises(ValueError):
                publisher_rows(data)

    def test_publisher_blob_binding_and_create_only(self):
        raw = canonical(public_fixture())
        expected = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "publisher.json"
            source.write_bytes(raw)
            with patch("public_structural_data.DATA_BYTES", len(raw)), patch("public_structural_data.DATA_GIT_BLOB", expected):
                result = prepare_dataset(source, root)
                self.assertEqual(result[0], hashlib.sha256((root / "dataset.jsonl").read_bytes()).hexdigest())
                with self.assertRaises(FileExistsError):
                    prepare_dataset(source, root)
                source.write_bytes(raw[:-2] + b"  ")
                with self.assertRaises(ValueError):
                    prepare_dataset(source, root)


class DownloadChecks(unittest.TestCase):
    def response(self, data):
        response = io.BytesIO(data)
        response.status = 200
        return response

    def test_stream_sha_and_exact_count(self):
        content = b"explicit fixture bytes"
        with tempfile.TemporaryDirectory() as d, patch("public_structural_stage.urlopen", return_value=self.response(content)):
            result = download_checked("https://fixture.invalid", Path(d)/"item", len(content), "sha256", hashlib.sha256(content).hexdigest())
            self.assertEqual(result["bytes"], len(content))

    def test_git_blob_hash_not_plain_sha1(self):
        content = b"fixture"
        expected = hashlib.sha1(b"blob 7\0" + content).hexdigest()
        with tempfile.TemporaryDirectory() as d, patch("public_structural_stage.urlopen", return_value=self.response(content)):
            self.assertEqual(download_checked("https://fixture.invalid", Path(d)/"item", 7, "sha1", expected)["publisher_digest"], expected)

    def test_wrong_size_truncated_and_corrupt_download(self):
        for content, size in ((b"xx", 1), (b"x", 2), (b"y", 1)):
            with self.subTest(content=content, size=size), tempfile.TemporaryDirectory() as d:
                with patch("public_structural_stage.urlopen", return_value=self.response(content)), self.assertRaises(ValueError):
                    download_checked("https://fixture.invalid", Path(d)/"item", size, "sha256", hashlib.sha256(b"x").hexdigest())

    def test_existing_download_not_replaced(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d)/"item"
            target.write_bytes(b"keep")
            with patch("public_structural_stage.urlopen") as network, self.assertRaises(FileExistsError):
                download_checked("https://fixture.invalid", target, 1, "sha256", "0"*64)
            network.assert_not_called()
            self.assertEqual(target.read_bytes(), b"keep")

    def info(self):
        return SimpleNamespace(sha=REVISION, siblings=[SimpleNamespace(rfilename=name, size=32,
            lfs=SimpleNamespace(sha256=WEIGHTS_SHA256) if name.endswith("safetensors") else None,
            blob_id="1"*40) for name in MODEL_FILES])

    def test_publisher_pins_reject_wrong_revision_and_weights(self):
        info = self.info()
        self.assertEqual(set(model_pins(info)), set(MODEL_FILES))
        info.sha = "0"*40
        with self.assertRaises(ValueError):
            model_pins(info)
        info = self.info()
        next(x for x in info.siblings if x.lfs).lfs.sha256 = "0"*64
        with self.assertRaises(ValueError):
            model_pins(info)

    def test_missing_duplicate_or_oversized_model_inventory(self):
        for mutate in (lambda info: info.siblings.pop(),
                       lambda info: info.siblings.append(info.siblings[0]),
                       lambda info: setattr(info.siblings[0], "size", 999_999_999)):
            info = self.info()
            mutate(info)
            with self.assertRaises(ValueError):
                model_pins(info)


class ReplayChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.threads = torch.get_num_threads()
        torch.set_num_threads(1)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.threads)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = StudyConfig(classes=2, rank=2, base_steps=6, adaptation_steps=8,
                                  minimum_groups=2, origin="synthetic_fixture", seal_replay=True)
        self.rows = audit_rows(fixture_rows(), self.config)
        self.dataset = self.root / "dataset.jsonl"
        self.dataset.write_bytes(b"".join(canonical(r) for r in self.rows))
        self.output = self.root / "output"
        self.output.mkdir()
        self.sealed = fit_and_seal(*prepare_views(self.rows), fixture_features(self.rows), self.config, self.output)
        write_once(self.output / "run.json", {"schema": "hepta.stem.structural-run.v2", "source_sha": "fixture-not-a-commit", "sealed": self.sealed,
                   "dataset_sha256": hashlib.sha256(self.dataset.read_bytes()).hexdigest()})

    def modify_record(self, name, transform):
        path = self.output / name
        value = json.loads(path.read_bytes())
        transform(value)
        path.write_bytes(canonical(value))
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_all_saved_checkpoints_reproduce_sealed_predictions(self):
        report = replay(self.output, self.dataset)
        self.assertEqual(report["checkpoint_count"], 5)
        self.assertEqual(report["prediction_rows"], 160)
        self.assertEqual(report["argmax_reversals"], 0)
        self.assertLessEqual(report["max_abs_logit_error"], 1e-5)
        self.assertFalse(report["encoder_execution_independently_attested"])

    def test_wrong_normalizer_bytes_rejected(self):
        path = self.output / "normalizer.safetensors"
        tensors = load(path.read_bytes())
        tensors["mean"] += 1
        path.write_bytes(save(tensors))
        with self.assertRaises(ValueError):
            replay(self.output, self.dataset)

    def test_rehashed_non_base_normalizer_still_rejected(self):
        path = self.output / "normalizer.safetensors"
        tensors = load(path.read_bytes())
        tensors["mean"] += 1
        path.write_bytes(save(tensors))
        self.modify_record("run.json", lambda r: r["sealed"].update(normalizer_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        with self.assertRaises(ValueError):
            replay(self.output, self.dataset)

    def test_tampered_checkpoint_rejected(self):
        path = self.output / "frozen.safetensors"
        tensors = load(path.read_bytes())
        tensors["bank.base.bias"] += 1
        path.write_bytes(save(tensors))
        with self.assertRaises(ValueError):
            replay(self.output, self.dataset)

    def test_rehashed_wrong_logits_rejected_by_arithmetic(self):
        def change(rows):
            rows[0]["logits"][0] += .5
        new_hash = self.modify_record("predictions.json", change)
        self.modify_record("run.json", lambda r: r["sealed"].update(predictions_sha256=new_hash))
        with self.assertRaises(ValueError):
            replay(self.output, self.dataset)

    def test_rehashed_feature_row_swap_rejected(self):
        path = self.output / "replay-features.safetensors"
        tensors = load(path.read_bytes())
        tensors["features"][0], tensors["features"][-1] = tensors["features"][-1].clone(), tensors["features"][0].clone()
        path.write_bytes(save(tensors))
        self.modify_record("run.json", lambda r: r["sealed"]["replay"].update(features_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        with self.assertRaises(ValueError):
            replay(self.output, self.dataset)

    def test_failed_run_refused(self):
        (self.output / "FAILED.json").write_text("{}")
        with self.assertRaises(ValueError):
            replay(self.output, self.dataset)

    def test_unknown_artifact_name_cannot_escape_directory(self):
        def change(selection):
            selection["checkpoints"]["../../outside"] = selection["checkpoints"].pop("frozen")
        new_hash = self.modify_record("selection.json", change)
        self.modify_record("run.json", lambda r: r["sealed"].update(selection_sha256=new_hash))
        with self.assertRaises(ValueError):
            replay(self.output, self.dataset)

    def test_evaluation_label_change_does_not_change_replayed_logits(self):
        rows = deepcopy(self.rows)
        for row in rows:
            if phase(row) in {"held_out", "future_1", "future_2", "ood"}:
                row["label"] = 1-row["label"]
        self.dataset.write_bytes(b"".join(canonical(r) for r in rows))
        self.modify_record("run.json", lambda r: r.update(dataset_sha256=hashlib.sha256(self.dataset.read_bytes()).hexdigest()))
        self.assertEqual(replay(self.output, self.dataset)["argmax_reversals"], 0)


if __name__ == "__main__":
    unittest.main()
