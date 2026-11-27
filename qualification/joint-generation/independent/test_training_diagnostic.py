"""Handmade source metadata/bytes/state only; no dataset, inference or training."""

import base64
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

import numpy as np

from independent.accounting import WorkLedger
from independent.data_v2 import manifest
from independent.experiments import resolve_experiment
from independent.training_diagnostic import PrefixRecorder, TrainOnlyProvider, data_manifest, encoded, retain_outputs


def sha(value):
    return hashlib.sha256(value).hexdigest()


def handmade_pool():
    n = 12 * 16 * 16
    full = np.zeros((n, 202))
    full[:, 0] = np.arange(n) / n
    full[:, [192, 196, 199]] = 1
    ids, sources, scenes = [], {}, []
    for scene in range(12):
        for index in range(16):
            digest = sha((str(scene) + ":" + str(index)).encode())
            source = "physical-v2:" + digest
            sources[source] = {"scene": scene, "index": index, "image_sha256": digest}
            ids.extend([source] * 16); scenes.extend([scene] * 16)
    profile = {"seeds": {"train": 304797655, "validation": 3249316160, "test": 227603836},
               "sources_per_class": {"train": 16, "validation": 6, "test": 6},
               "instructions_per_source": 8, "variants": 2}
    data = {"full": full, "low": full.copy(), "labels": np.asarray(scenes),
        "source_scenes": np.asarray(scenes), "commands": np.zeros((n, 3), dtype=np.int64),
        "source_ids": ids, "groups": ids.copy(), "sources": sources, "split": "train",
        "input_hashes": [sha(row.astype("<f8").tobytes()) for row in full],
        "profile_sha256": sha(encoded(profile))}
    plan = {"data_profile": profile, "training_diagnostic": {
        "parent_train_seed": 304797655, "source_partition_salt": "handmade-partition-v1",
        "fit_sources_per_class": 12, "monitor_sources_per_class": 4}}
    return data, plan


class HandModel:
    def __init__(self):
        self.dimensions = (2, 2, 3, 3)
        self.params = {"encoder": np.arange(6, dtype=np.float64).reshape(2, 3),
                       "bias": np.zeros(3), "decoder": np.ones((2, 3))}
        self._moments = {"encoder": (np.ones((2, 3)), np.ones((2, 3)) * 2, 3)}

    def digest(self):
        return sha(json.dumps(self.dimensions).encode() + b"".join(
            key.encode() + value.astype("<f8").tobytes() for key, value in sorted(self.params.items())))


class TrainingDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def provider(self, run, pool, plan):
        run.mkdir()
        ledger = WorkLedger("handmade-provider")
        constructor = Mock(return_value=pool)
        return TrainOnlyProvider(plan, run, ledger, constructor, manifest), constructor, ledger

    def test_provider_rejects_official_heldout_before_constructor_or_files(self):
        pool, plan = handmade_pool()
        provider, constructor, ledger = self.provider(self.root / "run", pool, plan)
        for split in ("test", "official-validation", "other"):
            with self.subTest(split=split), self.assertRaisesRegex(ValueError, "TRAIN-only"):
                provider(split)
        constructor.assert_not_called()
        self.assertEqual(list((self.root / "run").iterdir()), [])
        self.assertEqual(ledger.consumed_units, 0)

    def test_provider_preserves_whole_sources_order_bytes_and_train_only_provenance(self):
        pool, plan = handmade_pool()
        run = self.root / "run"
        provider, constructor, ledger = self.provider(run, pool, plan)
        fit, monitor = provider("train"), provider("validation")
        constructor.assert_called_once_with("train", plan["data_profile"])
        self.assertIs(provider("train"), fit)
        self.assertEqual((len(fit["labels"]), len(monitor["labels"])), (2304, 768))
        self.assertEqual((len(set(fit["source_ids"])), len(set(monitor["source_ids"]))), (144, 48))
        self.assertFalse(set(fit["source_ids"]) & set(monitor["source_ids"]))
        self.assertFalse(set(fit["input_hashes"]) & set(monitor["input_hashes"]))
        for data, role, count in ((fit, "fit", 12), (monitor, "monitor", 4)):
            retained_sources = set(data["source_ids"])
            indices = np.asarray([index for index, source in enumerate(pool["source_ids"])
                                  if source in retained_sources])
            np.testing.assert_array_equal(data["full"], pool["full"][indices])
            self.assertEqual(data["split"], "train")
            self.assertEqual(data["training_diagnostic"]["role"], role)
            self.assertEqual(data_manifest(data, manifest)["training_diagnostic"]["parent_split"], "train")
            for scene in range(12):
                members = {source for source, source_scene in zip(data["source_ids"], data["source_scenes"]) if source_scene == scene}
                ranked = sorted([source for source, row in pool["sources"].items() if row["scene"] == scene],
                    key=lambda source: (hashlib.sha256((plan["training_diagnostic"]["source_partition_salt"]
                        + "\0" + str(scene) + "\0" + source).encode()).digest(), source))
                self.assertEqual(members, set(ranked[:12] if role == "fit" else ranked[12:]))
                self.assertEqual(len(members), count)
        receipt = provider.receipt
        self.assertEqual(receipt["actual_constructor_calls"], ["train"])
        self.assertFalse(receipt["official_held_out_constructed"])
        bytes_written = 0
        for role, item in receipt["artifacts"].items():
            for row in item["files"]:
                actual = (run / row["file"]).read_bytes()
                self.assertEqual((sha(actual), len(actual)), (row["sha256"], row["bytes"]))
                bytes_written += len(actual)
            with np.load(run / item["files"][0]["file"], allow_pickle=False) as saved:
                np.testing.assert_array_equal(saved["full"], pool["full"] if role == "pool" else provider.parts["train" if role == "fit" else "validation"]["full"])
        self.assertEqual(ledger.totals["serialized_bytes"], bytes_written)
        other, _, _ = self.provider(self.root / "other", pool, plan)
        other("validation")
        self.assertEqual(other.receipt, receipt)

    def test_parent_identity_or_source_geometry_fault_is_not_silently_resampled(self):
        pool, plan = handmade_pool()
        changed = copy.deepcopy(plan)
        changed["training_diagnostic"]["parent_train_seed"] += 1
        provider, constructor, _ = self.provider(self.root / "bad-seed", pool, changed)
        with self.assertRaisesRegex(ValueError, "seed changed"):
            provider("train")
        constructor.assert_not_called()
        pool["source_ids"][:16] = [pool["source_ids"][16 * 16]] * 16
        provider, constructor, _ = self.provider(self.root / "bad-source", pool, plan)
        with self.assertRaisesRegex(ValueError, "spans source classes"):
            provider("train")
        constructor.assert_called_once()
        self.assertEqual(list((self.root / "bad-source").iterdir()), [])

    def test_output_archive_retains_actual_png_json_rng_and_deterministic_member_bytes(self):
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
        outputs = [{"caption": "handmade", "choices": {"text": i, "image": 0},
                    "png_sha256": sha(png), "png_base64": base64.b64encode(png).decode()} for i in range(2)]
        rng = np.random.default_rng(19)
        before = copy.deepcopy(rng.bit_generator.state)
        rng.random((2, 2))
        after = copy.deepcopy(rng.bit_generator.state)
        trace = {"outputs": outputs, "sample_rng_before": before, "sample_rng_after": after,
                 "route_rng_before": before, "route_rng_after": before, "batches": [{"rows": 2}]}
        original = encoded(trace)
        receipts = []
        for name in ("one", "two"):
            run = self.root / name; run.mkdir()
            ledger = WorkLedger("archive")
            receipt = retain_outputs(trace, run, 11, "full", 0, ledger)
            receipts.append(receipt)
            with zipfile.ZipFile(run / receipt["file"]) as archive:
                self.assertEqual(archive.read("000.png"), png)
                self.assertEqual(archive.read("001.json"), encoded(outputs[1]))
                self.assertEqual(archive.read("rng.json"), encoded({key: value for key, value in trace.items() if key != "outputs"}))
                self.assertTrue(all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist()))
            self.assertEqual(receipt["sha256"], sha((run / receipt["file"]).read_bytes()))
            self.assertEqual(ledger.totals["retained_output_bytes"], receipt["bytes"])
            self.assertEqual(ledger.consumed_units, 0)
            selected = [retain_outputs(trace, run, 11, "full", 0, ledger, namespace=system,
                                      stage="selection_validation")
                        for system in ("supervised", "anchor", "additive", "ndu")]
            self.assertEqual(len({row["file"] for row in selected}), 4)
            self.assertTrue(all(row["sha256"] == receipt["sha256"] for row in selected))
            self.assertEqual(ledger.snapshot()["stages"]["selection_validation"]["retained_output_bytes"],
                             sum(row["bytes"] for row in selected))
            with self.assertRaises(FileExistsError):
                retain_outputs(trace, run, 11, "full", 0, ledger)
        self.assertEqual(receipts[0], receipts[1])
        self.assertEqual(encoded(trace), original)
        self.assertEqual(rng.bit_generator.state, after)
        trace["outputs"][0]["png_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "PNG hash mismatch"):
            retain_outputs(trace, self.root / "one", 11, "full", 1, WorkLedger("bad-png"))

    def test_live_prefix_checkpoints_include_all_prior_draws_state_and_real_step_count(self):
        model, rng = HandModel(), np.random.default_rng(37)
        recorder, ledger, expected = PrefixRecorder([1, 32]), WorkLedger("prefix"), hashlib.sha256()
        states = []
        for step in range(1, 33):
            idx, full = rng.integers(48, size=4), rng.random(4) < .5
            expected.update(idx.astype("<i8").tobytes() + full.astype(np.uint8).tobytes())
            model.params["encoder"][0, 0] = step
            recorder.update(step, idx, full, model, step / 100, rng, ledger)
            if step in (1, 32): states.append(copy.deepcopy(rng.bit_generator.state))
        self.assertEqual([row["step"] for row in recorder.checkpoints], [1, 32])
        final = recorder.checkpoints[-1]
        self.assertEqual(final["draws_sha256"], expected.hexdigest())
        self.assertAlmostEqual(final["mean_prefix_loss"], .165)
        self.assertEqual(final["model_digest"], model.digest())
        self.assertEqual([row["rng_state"] for row in recorder.checkpoints], states)
        rng.random(8)
        self.assertEqual([row["rng_state"] for row in recorder.checkpoints], states)
        self.assertGreater(ledger.totals["diagnostic_prefix_hashed_bytes"], 32 * (4 * 8 + 4))
        self.assertEqual(ledger.totals["diagnostic_prefix_serialized_bytes"], sum(len(encoded(row)) for row in recorder.checkpoints))
        snapshot = ledger.snapshot()
        recorder.update(33, idx, full, model, 999., rng, ledger)
        self.assertEqual(ledger.snapshot(), snapshot)

    def test_missing_32_stays_visible_and_an_earlier_draw_or_model_changes_identity(self):
        records = []
        for variant in ("baseline", "early-draw", "model", "moments"):
            recorder, model, rng = PrefixRecorder([1, 32]), HandModel(), np.random.default_rng(10)
            for step in range(1, 33):
                idx, full = np.arange(4), np.array([True, False, True, False])
                if variant == "early-draw" and step == 16: idx = idx + 1
                if variant == "model": model.params["encoder"][0, 0] = 999
                if variant == "moments":
                    m, v, clock = model._moments["encoder"]
                    model._moments["encoder"] = (m, v, clock + 1)
                recorder.update(step, idx, full, model, .5, rng, WorkLedger("prefix"))
            records.append(recorder.checkpoints[-1])
        self.assertNotEqual(records[0]["draws_sha256"], records[1]["draws_sha256"])
        self.assertEqual(records[0]["idx"], records[1]["idx"])
        self.assertNotEqual(records[0]["model_digest"], records[2]["model_digest"])
        self.assertNotEqual(records[0]["moments_digest"], records[3]["moments_digest"])
        missing = PrefixRecorder([1, 32])
        for step in range(1, 8):
            missing.update(step, np.arange(4), np.ones(4, dtype=bool), HandModel(), .5, np.random.default_rng(3), WorkLedger("short-prefix"))
        self.assertEqual([row["step"] for row in missing.checkpoints], [1])
        with self.assertRaises(ValueError): PrefixRecorder([1, 31])

    def test_diagnostic_formal_capability_denied_before_data_preflight_and_marker_checks(self):
        from independent import evaluation
        self.assertFalse(resolve_experiment("codec-train-d1").can_evaluate)
        self.assertTrue(resolve_experiment("efficient-r2").can_evaluate)
        self.assertTrue(resolve_experiment("core-c1").can_evaluate)
        with patch.object(evaluation, "dataset", side_effect=AssertionError("data")) as data, \
             patch.object(evaluation, "_frozen", side_effect=AssertionError("preflight")) as frozen, \
             patch.object(evaluation, "_exclusive", side_effect=AssertionError("marker write")) as marker, \
             patch.object(Path, "exists", side_effect=AssertionError("marker inspection")):
            with self.assertRaisesRegex(ValueError, "formal|evaluat|TRAIN-only"):
                evaluation.run_evaluation(self.root / "uncreated", "codec-train-d1")
        data.assert_not_called(); frozen.assert_not_called(); marker.assert_not_called()


if __name__ == "__main__":
    unittest.main()
