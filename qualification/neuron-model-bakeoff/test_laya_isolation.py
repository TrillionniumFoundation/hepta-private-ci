"""Synthetic NEU-1 original-weight tokenizer isolation contracts, no model execution."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from laya_isolation import load_laya_isolated


def load_laya_cpu_isolated(snapshot, factory):
    return load_laya_isolated(snapshot, factory, device="cpu")


def fixture(root: Path) -> Path:
    source = root / "pinned"
    (source / "tokenizer").mkdir(parents=True)
    (source / "encoder").mkdir()
    (source / "model.safetensors").write_bytes(b"original-full-decision-model-weights")
    (source / "rl_agent_config.json").write_text('{"encoder":"local","head_layers":2}')
    (source / "encoder" / "config.json").write_text('{"model_type":"modernbert"}')
    (source / "tokenizer" / "tokenizer.json").write_bytes(b'{"model":{}}')
    (source / "tokenizer" / "tokenizer_config.json").write_text(json.dumps({
        "tokenizer_class": "TokenizersBackend",
        "backend": "legacy",
        "extra_special_tokens": ["<slot>"],
    }))
    return source


class ViewTests(unittest.TestCase):
    def test_real_upstream_style_rewrite_only_changes_private_view(self):
        with tempfile.TemporaryDirectory() as t:
            snapshot = fixture(Path(t))
            original = (snapshot / "tokenizer" / "tokenizer_config.json").read_bytes()
            weight_sha = hashlib.sha256((snapshot / "model.safetensors").read_bytes()).hexdigest()
            witnessed = []

            def fake_agent(path, device):
                self.assertEqual(device, "cpu")
                private = Path(path)
                witnessed.append(private)
                self.assertTrue((private / "model.safetensors").is_symlink())
                self.assertEqual((private / "model.safetensors").read_bytes(),
                                 b"original-full-decision-model-weights")
                config_path = private / "tokenizer" / "tokenizer_config.json"
                config = json.loads(config_path.read_text())
                config["tokenizer_class"] = "PreTrainedTokenizerFast"
                config.pop("backend")
                config["extra_special_tokens"] = {"extra_0": "<slot>"}
                config_path.write_text(json.dumps(config))
                return {"device": device}

            agent, report = load_laya_cpu_isolated(snapshot, fake_agent)
            self.assertEqual(agent, {"device": "cpu"})
            self.assertTrue(report["registered_config_rewrite"])
            self.assertTrue(report["no_original_snapshot_mutation_observed"])
            self.assertEqual(report["original_weight_sha256"], weight_sha)
            self.assertNotEqual(report["original_tokenizer_inventory_sha256"],
                                report["effective_tokenizer_inventory_sha256"])
            self.assertEqual((snapshot / "tokenizer" / "tokenizer_config.json").read_bytes(),
                             original)
            self.assertFalse(witnessed[0].exists())

    def test_unregistered_modified_tokenizer_payload_denied(self):
        with tempfile.TemporaryDirectory() as t:
            snapshot = fixture(Path(t))
            def wrong_agent(path, device):
                (Path(path) / "tokenizer" / "tokenizer.json").write_text('{"tampered":true}')
                return object()
            with self.assertRaisesRegex(ValueError, "unexpectedly changed tokenizer"):
                load_laya_cpu_isolated(snapshot, wrong_agent)
            self.assertEqual((snapshot / "tokenizer" / "tokenizer.json").read_bytes(),
                             b'{"model":{}}')

    def test_unregistered_config_transform_denied(self):
        with tempfile.TemporaryDirectory() as t:
            snapshot = fixture(Path(t))
            def wrong_agent(path, device):
                config_path = Path(path) / "tokenizer" / "tokenizer_config.json"
                config_path.write_text('{"tokenizer_class":"Arbitrary"}')
                return object()
            with self.assertRaisesRegex(ValueError, "unregistered tokenizer rewrite"):
                load_laya_cpu_isolated(snapshot, wrong_agent)

    def test_origins_cannot_be_mutated_through_private_view(self):
        with tempfile.TemporaryDirectory() as t:
            snapshot = fixture(Path(t))
            def malicious_agent(path, device):
                (snapshot / "encoder" / "config.json").write_text('{"changed":true}')
                return object()
            with self.assertRaisesRegex(ValueError, "original encoder/config.json"):
                load_laya_cpu_isolated(snapshot, malicious_agent)

    def test_input_symlinks_denied_before_any_loader_runs(self):
        with tempfile.TemporaryDirectory() as t:
            snapshot = fixture(Path(t))
            (snapshot / "tokenizer" / "alias.json").symlink_to(
                snapshot / "tokenizer" / "tokenizer.json")
            calls = []
            def forbidden(path, device):
                calls.append(path)
                return object()
            with self.assertRaisesRegex(ValueError, "linked members"):
                load_laya_cpu_isolated(snapshot, forbidden)
            self.assertEqual(calls, [])

    def test_missing_tok_config_is_not_fabricated(self):
        with tempfile.TemporaryDirectory() as t:
            snapshot = fixture(Path(t))
            (snapshot / "tokenizer" / "tokenizer_config.json").unlink()
            agent, report = load_laya_cpu_isolated(
                snapshot, lambda path, device: (path, device))
            self.assertIsNone(report["original_tokenizer_config_sha256"])
            self.assertIsNone(report["effective_tokenizer_config_sha256"])
            self.assertFalse(report["registered_config_rewrite"])
            self.assertEqual(agent[1], "cpu")

    def test_new_file_from_mutating_loader_denied(self):
        with tempfile.TemporaryDirectory() as t:
            snapshot = fixture(Path(t))
            def wrong_agent(path, device):
                (Path(path) / "tokenizer" / "unknown.json").write_text("{}")
                return object()
            with self.assertRaisesRegex(ValueError, "created or deleted"):
                load_laya_cpu_isolated(snapshot, wrong_agent)


class ExceptionCustodyTests(unittest.TestCase):
    def test_constructor_mutation_then_raise_is_detected_and_chained(self):
        for relative in ("tokenizer/tokenizer_config.json", "encoder/config.json", "model.safetensors"):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as t:
                snapshot = fixture(Path(t))
                failure = RuntimeError("constructor failed")
                witnessed = []

                def broken_agent(path, device):
                    witnessed.append(Path(path))
                    (snapshot / relative).write_bytes(b"changed")
                    raise failure

                with self.assertRaisesRegex(ValueError, "original") as caught:
                    load_laya_cpu_isolated(snapshot, broken_agent)
                self.assertIs(caught.exception.__cause__, failure)
                self.assertFalse(witnessed[0].exists())
                self.assertEqual((snapshot / relative).read_bytes(), b"changed")

    def test_constructor_failure_without_mutation_is_preserved(self):
        with tempfile.TemporaryDirectory() as t:
            snapshot = fixture(Path(t))
            failure = RuntimeError("constructor failed")

            def broken_agent(path, device):
                raise failure

            with self.assertRaises(RuntimeError) as caught:
                load_laya_cpu_isolated(snapshot, broken_agent)
            self.assertIs(caught.exception, failure)

    def test_unregistered_json_type_drift_denied(self):
        for original_value, replacement in ((True, 1), (False, 0),
                                            (1, True), (0, False), (1, 1.0)):
            with self.subTest(original=original_value, replacement=replacement):
                with tempfile.TemporaryDirectory() as t:
                    snapshot = fixture(Path(t))
                    config = snapshot / "tokenizer" / "tokenizer_config.json"
                    raw = json.loads(config.read_text())
                    raw["custom"] = {"values": [original_value]}
                    config.write_text(json.dumps(raw))

                    def wrong_agent(path, device):
                        private = Path(path) / "tokenizer" / "tokenizer_config.json"
                        actual = json.loads(private.read_text())
                        actual["tokenizer_class"] = "PreTrainedTokenizerFast"
                        actual.pop("backend", None)
                        actual.pop("is_local", None)
                        actual["extra_special_tokens"] = {"extra_0": "<slot>"}
                        actual["custom"]["values"][0] = replacement
                        private.write_text(json.dumps(actual))
                        return object()

                    with self.assertRaisesRegex(ValueError, "unregistered tokenizer rewrite"):
                        load_laya_cpu_isolated(snapshot, wrong_agent)


class ResourceBoundsTests(unittest.TestCase):
    def test_bounded_tokenizer_file_and_directory_inventories(self):
        with tempfile.TemporaryDirectory() as t:
            snapshot = fixture(Path(t))
            tok = snapshot / "tokenizer"
            for i in range(64):
                (tok / f"extra-{i:02d}.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "exceeds fixed limits"):
                load_laya_cpu_isolated(snapshot, lambda path, device: None)
        with tempfile.TemporaryDirectory() as t:
            snapshot = fixture(Path(t))
            tok = snapshot / "tokenizer"
            for i in range(513):
                (tok / f"empty-{i:03d}").mkdir()
            with self.assertRaisesRegex(ValueError, "tree exceeds fixed limits"):
                load_laya_cpu_isolated(snapshot, lambda path, device: None)

    def test_encoder_directory_link_denied(self):
        with tempfile.TemporaryDirectory() as t:
            snapshot = fixture(Path(t))
            (snapshot / "encoder" / "config.json").unlink()
            (snapshot / "encoder").rmdir()
            (snapshot / "encoder").symlink_to(snapshot / "tokenizer", target_is_directory=True)
            with self.assertRaises(ValueError):
                load_laya_cpu_isolated(snapshot, lambda path, device: None)


if __name__ == "__main__":
    unittest.main()
