import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
import types
import sys

from sdk_readonly.readonly_tokenizer import load_readonly_tokenizer, tokenizer_kwargs


class ReadonlyTokenizerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "tokenizer_config.json"

    def write(self, extra, tokenizer_class="PreTrainedTokenizerFast"):
        self.path.write_text(json.dumps({"tokenizer_class": tokenizer_class, "extra_special_tokens": extra}))

    def test_list_mapping_no_write(self):
        self.write(["<a>", "<b>"])
        before = self.path.read_bytes()
        self.assertEqual(tokenizer_kwargs(self.root), {"local_files_only": True, "trust_remote_code": False, "extra_special_tokens": {"extra_0": "<a>", "extra_1": "<b>"}})
        self.assertEqual(self.path.read_bytes(), before)

    def test_mapping_preserved(self):
        self.write({"extra_0": "<a>"})
        self.assertEqual(tokenizer_kwargs(self.root)["extra_special_tokens"], {"extra_0": "<a>"})

    def test_absent_extras(self):
        self.write(None)
        self.assertNotIn("extra_special_tokens", tokenizer_kwargs(self.root))

    def test_unsupported_class_rejects_no_write(self):
        for name in (None, "TokenizersBackend", "CustomTokenizer"):
            with self.subTest(name=name):
                self.write(["<a>"], name)
                before = self.path.read_bytes()
                with self.assertRaises(ValueError):
                    tokenizer_kwargs(self.root)
                self.assertEqual(before, self.path.read_bytes())

    def test_invalid_extras_reject(self):
        for extra in ([True], [1], [""], ["a", "a"], [None], 1, True, "bad", {"": "a"}, {"x": False}):
            with self.subTest(extra=extra):
                self.write(extra)
                with self.assertRaises(ValueError):
                    tokenizer_kwargs(self.root)

    def test_remote_path_rejected(self):
        with self.assertRaises(ValueError):
            tokenizer_kwargs(self.root / "not-present")

    def test_loader_passes_explicit_safety_kwargs(self):
        self.write(["<a>"])
        load = Mock(return_value="tokenizer")
        with patch.dict(sys.modules, {"transformers": types.SimpleNamespace(AutoTokenizer=types.SimpleNamespace(from_pretrained=load))}):
            self.assertEqual(load_readonly_tokenizer(self.root), "tokenizer")
            load.assert_called_once_with(str(self.root), local_files_only=True, trust_remote_code=False, extra_special_tokens={"extra_0": "<a>"})




class CandidateBuildTests(unittest.TestCase):
    def test_pinned_agent_patch_preserves_calibration_and_architecture(self):
        from sdk_readonly.build_candidate import patch_agent
        source = "def _fix_tokenizer_config(path):\n    write(path)\n\ndef _verify_compatibility(*args): pass\n\ndef _load_tokenizer(tok_dir, cfg):\n    return load(tok_dir)\n\ndef _amp_context(*args): pass\n\nclass Agent:\n    def __init__(self):\n        _fix_tokenizer_config(model_dir)\n        self.temperature = [clamp_temperature(t) for t in self.temperature_raw]\n        self.model = build_model(cfg)\n"
        result = patch_agent(source)
        self.assertNotIn("_fix_tokenizer_config", result)
        self.assertIn("return load_readonly_tokenizer(tok_dir)", result)
        self.assertIn("self.temperature = [clamp_temperature(t) for t in self.temperature_raw]", result)
        self.assertIn("self.model = build_model(cfg)", result)

    def test_ambiguous_repair_call_rejected(self):
        from sdk_readonly.build_candidate import patch_agent
        source = "def _fix_tokenizer_config(path): pass\ndef _verify_compatibility(*args): pass\ndef _load_tokenizer(tok_dir, cfg): pass\ndef _amp_context(*args): pass\n"
        with self.assertRaises(ValueError):
            patch_agent(source)

    def test_source_identity_drift_rejects_before_output(self):
        from sdk_readonly.build_candidate import build
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "source"
            source.mkdir()
            (source / "agent.py").write_text("not the official SDK")
            output = Path(root) / "output"
            with self.assertRaisesRegex(ValueError, "differs from the pinned"):
                build(source, output)
            self.assertFalse(output.exists())


class ProvenanceTests(unittest.TestCase):
    def test_self_consistent_workspace_cannot_replace_pinned_source(self):
        from sdk_readonly.provenance import validate_workspace
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root / "source-manifest.json").write_text(json.dumps({"profile": "unreviewed"}))
            with self.assertRaisesRegex(ValueError, "reviewed source pin"):
                validate_workspace(root)

    def test_optimized_python_rejects_before_model_import(self):
        import subprocess
        directory = Path(__file__).resolve().parent / "sdk_readonly"
        for name in ("run_probe.py", "compare.py"):
            with self.subTest(name=name):
                result = subprocess.run([sys.executable, "-O", str(directory / name), "--help"], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("optimized Python disables evidence checks", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "the diagnostic profile is explicitly Linux-only")
    def test_unreviewed_vendor_rejected_before_import(self):
        import subprocess
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root / "source-manifest.json").write_text(json.dumps({"profile": "unreviewed"}))
            package = root / "vendor/laya"
            package.mkdir(parents=True)
            marker = root / "unexpected-import.txt"
            (package / "__init__.py").write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n")
            script = Path(__file__).resolve().parent / "sdk_readonly/run_probe.py"
            result = subprocess.run([sys.executable, str(script), "readonly_candidate", "--workspace", str(root), "--snapshot", str(root / "absent")], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("reviewed source pin", result.stderr)
            self.assertFalse(marker.exists())
