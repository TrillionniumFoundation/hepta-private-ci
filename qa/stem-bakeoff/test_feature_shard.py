"""Offline byte-integrity and authority boundaries for teacher feature shards."""
import json
import pathlib
import sys
import tempfile
import unittest

try:
    import torch
except ImportError:
    torch = None

if torch is not None:
    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    from feature_shard import FeatureShardError, REPO_ROOT, read_shard, write_shard


def args():
    return {"candidate": "embeddinggemma2_740m", "revision": "a" * 40,
            "checkpoint_inventory_sha256": "b" * 64,
            "ordered_source_manifest_sha256": "c" * 64}


@unittest.skipUnless(torch is not None, "optional Torch offline shard tests")
class FeatureShardTests(unittest.TestCase):
    def test_new_private_shard_roundtrips_and_cannot_grant_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "shard"
            expected = torch.nn.functional.normalize(torch.randn(2, 32), dim=-1)
            receipt = write_shard(path, expected, **args())
            observed, manifest = read_shard(path)
            self.assertTrue(torch.equal(observed, expected.float()))
            self.assertFalse(receipt["production_activation_allowed"])
            self.assertFalse(manifest["source_independently_attested"])
            self.assertEqual(manifest["authority"], "DENY_ALL")
            self.assertEqual((path / "features.npy").stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FeatureShardError):
                write_shard(path, expected, **args())

    def test_payload_tampering_or_authority_smuggling_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "shard"
            write_shard(path, torch.randn(1, 16), **args())
            manifest_path = path / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["production_activation_allowed"] = True
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaises(FeatureShardError):
                read_shard(path)
            manifest["production_activation_allowed"] = False
            manifest_path.write_text(json.dumps(manifest))
            (path / "features.npy").write_bytes(b"poison")
            with self.assertRaises(FeatureShardError):
                read_shard(path)

    def test_links_nonfinite_and_untrusted_source_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            with self.assertRaises(FeatureShardError):
                write_shard(root / "bad", torch.tensor([[float("nan")]]), **args())
            with self.assertRaises(FeatureShardError):
                write_shard(root / "bad", torch.ones(1, 8),
                            **(args() | {"revision": "mutable-branch"}))
            path = root / "okay"
            write_shard(path, torch.ones(1, 8), **args())
            (root / "alias").symlink_to(path, target_is_directory=True)
            with self.assertRaises(FeatureShardError):
                read_shard(root / "alias")
            (path / "features.npy").unlink()
            (path / "features.npy").symlink_to(root / "outside.npy")
            with self.assertRaises(FeatureShardError):
                read_shard(path)

    def test_no_accidental_export_to_git_checkout(self):
        with self.assertRaisesRegex(FeatureShardError, "outside checkout"):
            write_shard(REPO_ROOT / "hepta-sensitive-teacher-features",
                        torch.ones(1, 4), **args())


if __name__ == "__main__":
    unittest.main()
