"""Bounded upstream metadata and negative digest tests; no real downloads."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parent))
from replacement_gate import EXPECTED
from replacement_metadata import audit, check_metadata

REGISTRY = json.loads(Path(__file__).with_name("replacement_models.json").read_text())


def fixture(spec):
    return {"sha": spec["revision"], "siblings": [
        {"rfilename": "config.json", "size": 100},
        {"rfilename": "tokenizer.json", "size": 100},
        {"rfilename": "model.safetensors", "size": 500000000,
         "lfs": {"sha256": spec["weight_sha256"]}}]}


class MetadataTests(unittest.TestCase):
    def test_all_five_pins_with_external_metadata(self):
        called = []
        def fake(url):
            for name in EXPECTED:
                spec = REGISTRY["models"][name]
                if f"/{spec['repository']}/revision/{spec['revision']}" in url:
                    called.append(name)
                    return fixture(spec)
            raise AssertionError("unregistered external repository")
        result = audit(REGISTRY, fake)
        self.assertEqual(called, list(EXPECTED))
        self.assertFalse(result["real_checkpoint_execution_proved"])
        self.assertFalse(result["production_activation_allowed"])

    def test_wrong_publisher_sha_denied(self):
        spec = REGISTRY["models"][EXPECTED[0]]
        r = fixture(spec)
        r["sha"] = "e" * 40
        with self.assertRaises(ValueError):
            check_metadata(EXPECTED[0], spec, r)

    def test_wrong_lfs_denied(self):
        spec = REGISTRY["models"][EXPECTED[0]]
        r = fixture(spec)
        r["siblings"][2]["lfs"]["sha256"] = "f" * 64
        with self.assertRaises(ValueError):
            check_metadata(EXPECTED[0], spec, r)

    def test_config_and_tokenizer_required(self):
        spec = REGISTRY["models"][EXPECTED[1]]
        for filename in ("config.json", "tokenizer.json"):
            r = fixture(spec)
            r["siblings"] = [e for e in r["siblings"] if e["rfilename"] != filename]
            with self.assertRaises(ValueError):
                check_metadata(EXPECTED[1], spec, r)

    def test_duplicate_file_denied(self):
        spec = REGISTRY["models"][EXPECTED[2]]
        r = fixture(spec)
        r["siblings"].append(copy.deepcopy(r["siblings"][0]))
        with self.assertRaises(ValueError):
            check_metadata(EXPECTED[2], spec, r)


if __name__ == "__main__":
    unittest.main()
