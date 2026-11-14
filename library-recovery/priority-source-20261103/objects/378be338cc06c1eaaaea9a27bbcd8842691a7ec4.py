import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from readonly_tokenizer import load_readonly_tokenizer, tokenizer_kwargs


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
        with patch("transformers.AutoTokenizer.from_pretrained", return_value="tokenizer") as load:
            self.assertEqual(load_readonly_tokenizer(self.root), "tokenizer")
            load.assert_called_once_with(str(self.root), local_files_only=True, trust_remote_code=False, extra_special_tokens={"extra_0": "<a>"})


if __name__ == "__main__":
    unittest.main()
