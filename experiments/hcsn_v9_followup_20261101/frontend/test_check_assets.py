"""Substantive rejection controls; synthetic rows are not real AV evidence."""

import copy
import tempfile
from pathlib import Path
import unittest

from .check_assets import check_recordings, inspect, read_bound, recording_rows


def row(name, sha):
    return {"recording_id": name, "actor_id": name[:4], "media_sha256": sha * 64}


class AssetControls(unittest.TestCase):
    def setUp(self):
        self.history = [row("1001_DFA_ANG_XX", "a")]
        self.dev = [row("1002_DFA_SAD_XX", "b")]
        self.confirm = [row("1001_DFA_HAP_XX", "c")]

    def test_new_recording_with_old_actor_is_not_new_actor_claim(self):
        result = check_recordings(self.history, self.dev, self.confirm)
        self.assertEqual(result, {"history_recordings": 1, "development_recordings": 1,
                                  "confirmation_recordings": 1, "confirmation_actors": ["1001"],
                                  "reused_historical_actors": ["1001"]})

    def test_history_and_development_reuse_fail(self):
        for reused in (self.history, self.dev):
            with self.subTest(reused=reused), self.assertRaisesRegex(ValueError, "reuses"):
                check_recordings(self.history, self.dev, reused)

    def test_different_id_same_media_fails(self):
        duplicate = copy.deepcopy(self.confirm)
        duplicate[0]["media_sha256"] = self.history[0]["media_sha256"]
        with self.assertRaisesRegex(ValueError, "raw media"):
            check_recordings(self.history, self.dev, duplicate)

    def test_prefix_crop_extension_case_and_actor_aliases_fail(self):
        for name in ("1001_DFA_HAP_XX_prefix2", "1001_DFA_HAP_XX.wav", "1001_dfa_hap_xx", " 1001_DFA_HAP_XX"):
            bad = row(name, "c")
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "noncanonical"):
                recording_rows([bad], "confirmation")
        bad = copy.deepcopy(self.confirm)
        bad[0]["actor_id"] = "9999"
        with self.assertRaisesRegex(ValueError, "actor"):
            recording_rows(bad, "confirmation")

    def test_missing_inventory_or_media_identity_fail(self):
        for bad in (None, [], [{"recording_id": "1001_DFA_HAP_XX", "actor_id": "1001"}]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                recording_rows(bad, "confirmation")

    def test_strong_audio_wrong_bytes_and_path_escape_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / "audio.bin").write_bytes(b"unverified substitute")
            with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                read_bound(repo, "audio.bin", "a" * 64)
            with self.assertRaisesRegex(ValueError, "outside repository"):
                read_bound(repo, "../audio.bin", "a" * 64)
            with self.assertRaisesRegex(ValueError, "SHA256"):
                read_bound(repo, "audio.bin", None)

    def test_missing_real_baseline_and_assets_cannot_admit(self):
        with tempfile.TemporaryDirectory() as directory:
            result = inspect(Path(directory))
        self.assertFalse(result["admitted_for_confirmation"])
        self.assertFalse(result["quality_gate_passed"])
        self.assertFalse(result["history_completeness_verified"])
        self.assertTrue(result["problems"])
        self.assertEqual(result["status"], "HOLD")


if __name__ == "__main__":
    unittest.main()
