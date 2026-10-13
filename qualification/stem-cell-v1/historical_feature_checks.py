"""Synthetic byte/tensor regressions; the separate CI job requires the real ZIP."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import torch

from development_study_data import phase, write_once
from development_study_replay import verify_feature_origin
from historical_feature_study import (ARTIFACT_BYTES, ARTIFACT_ID, ARTIFACT_SHA256, FEATURE_SHA256,
                                      MODEL, REVISION, SOURCE_SHA, derive_study, load_reference,
                                      validate_raw_vectors, _tensor_digest)


def fixture():
    raw = torch.randn(328, 384, generator=torch.Generator().manual_seed(314))
    mean, scale = raw[:128].mean(0), raw[:128].std(0).clamp_min(.1)
    ids = [f"fixture:{i}" for i in range(328)]
    payload = {"ids": ids, "raw_vectors": raw, "vectors": ((raw - mean) / scale).clamp(-8, 8),
               "normalizer_mean": mean, "normalizer_scale": scale}
    events = {"normalizer_training_inputs": ids[:128], "events": [
        {"ids": ids[i:i+32], "vectors_sha256": _tensor_digest(raw[i:i+32])} for i in range(0, 328, 32)]}
    return payload, events, ids


class HistoricalFeatureChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.threads = torch.get_num_threads()
        torch.set_num_threads(1)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.threads)

    def test_raw_event_validation_returns_independent_raw_storage(self):
        data, events, ids = fixture()
        raw = validate_raw_vectors(data, events, ids)
        self.assertTrue(torch.equal(raw, data["raw_vectors"]))
        self.assertNotEqual(raw.data_ptr(), data["raw_vectors"].data_ptr())
        self.assertFalse(torch.equal(raw, data["vectors"]))

    def test_self_consistent_new_normalizer_cannot_hide_old_event_mismatch(self):
        data, events, ids = fixture()
        raw = data["raw_vectors"].clone()
        raw[[0, 1]] = raw[[1, 0]]
        mean, scale = raw[:128].mean(0), raw[:128].std(0).clamp_min(.1)
        data.update(raw_vectors=raw, normalizer_mean=mean, normalizer_scale=scale,
                    vectors=((raw-mean)/scale).clamp(-8,8))
        with self.assertRaisesRegex(ValueError, "physical forward event"):
            validate_raw_vectors(data, events, ids)

    def test_historical_normalizer_cannot_include_test_rows(self):
        data, events, ids = fixture()
        raw = data["raw_vectors"]
        data["normalizer_mean"] = raw.mean(0)
        with self.assertRaises(ValueError):
            validate_raw_vectors(data, events, ids)

    def test_nonfinite_and_wrong_dtype_rejected(self):
        for mode in ("nan", "dtype"):
            data, events, ids = fixture()
            if mode == "nan": data["raw_vectors"][0, 0] = float("nan")
            else: data["raw_vectors"] = data["raw_vectors"].double()
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                validate_raw_vectors(data, events, ids)

    def test_reordered_ids_and_missing_event_rejected(self):
        data, events, ids = fixture()
        with self.assertRaises(ValueError):
            validate_raw_vectors(data, events, list(reversed(ids)))
        events["events"].pop()
        with self.assertRaises(ValueError):
            validate_raw_vectors(data, events, ids)

    def test_derived_folds_preserve_all_raw_vectors(self):
        inventory, ids = {}, []
        for fold, count in (("train",32), ("validation",10), ("calibration",10), ("test",30)):
            inventory[fold] = [{"id": f"{fold}:{label}:{i}", "intent": label, "text": f"synthetic {fold} {label} {i}"}
                               for label in range(4) for i in range(count)]
            ids.extend(r["id"] for r in inventory[fold])
        raw = torch.arange(328*384, dtype=torch.float32).reshape(328,384)
        rows, vectors, config = derive_study(inventory,ids,raw)
        self.assertEqual(len(rows),328)
        self.assertEqual({p:sum(phase(r)==p for r in rows) for p in ("base","adapt","extra","calibration","held_out")},
                         {"base":64,"adapt":32,"extra":32,"calibration":80,"held_out":120})
        for r,v in zip(rows,vectors):
            self.assertTrue(torch.equal(v,raw[ids.index(r["sample_id"])]))
        self.assertTrue(all(r["observed_at"] is None for r in rows))
        self.assertTrue(config.seal_replay)

    def test_unpinned_archive_rejected_before_tensor_deserialization(self):
        with tempfile.TemporaryDirectory() as directory, patch("historical_feature_study.torch.load") as decode:
            path=Path(directory)/"wrong.zip"
            path.write_bytes(b"x"*ARTIFACT_BYTES)
            with self.assertRaisesRegex(ValueError,"SHA256"):
                load_reference(path)
            decode.assert_not_called()

    def test_missing_or_symlink_archive_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"missing.zip"
            with self.assertRaises(ValueError): load_reference(path)
            path.write_bytes(b"x")
            link=path.with_name("link.zip");link.symlink_to(path)
            with self.assertRaises(ValueError): load_reference(link)

    def test_cached_origin_cannot_assert_new_forward(self):
        reference={"artifact_id":ARTIFACT_ID,"archive_sha256":ARTIFACT_SHA256,"feature_sha256":FEATURE_SHA256,
                   "model":MODEL,"revision":REVISION,"source_sha":SOURCE_SHA}
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);sha=write_once(folder/"reference.json",reference)
            run={"schema":"hepta.stem.cached-feature-run.v1","reference_sha256":sha,"feature_origin":reference,
                 "real_weights_executed":False,"historical_pretrained_features_reused":True,"encoder_forward_calls_this_run":0}
            self.assertEqual(verify_feature_origin(folder,run)["new_encoder_forward_calls"],0)
            for changes in ({"real_weights_executed":True},{"encoder_forward_calls_this_run":1},
                            {"encoder_forward_calls_this_run":False},{"reference_sha256":"0"*64}):
                with self.subTest(changes=changes),self.assertRaises(ValueError):
                    verify_feature_origin(folder,{**run,**changes})


if __name__ == "__main__":
    unittest.main()
