"""Catalog admission over the existing real SQLite owner and safetensor bytes."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import torch
from safetensors.torch import save

from metadata_catalog import MetadataCatalog, SCHEMA
from parametric_owner import Frontier, ParametricOwner


def sha(data):
    return hashlib.sha256(data).hexdigest()


class MetadataCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.owner = ParametricOwner(self.root / "owner.sqlite")
        self.view = Frontier("scope-a")
        self.digest = self.checkpoint("initial")
        self.active = self.activate("initial", self.digest)
        self.document = {
            "schema": SCHEMA,
            "scope": "scope-a",
            "cell_id": "memory",
            "manifest_sha256": self.digest,
            "production_accepted": False,
            "entries": [
                {"entity": "Alice", "relation": "color", "source_digest": "1" * 64}
            ],
        }
        self.path = self.root / "catalog.json"
        self.pin = self.write_catalog(self.document)
        self.catalog = MetadataCatalog(self.path, self.pin)

    def checkpoint(self, name):
        directory = self.root / name
        directory.mkdir()
        weights = save({"layer.lora_A.weight": torch.ones((2, 2))})
        config = b'{"r":2}'
        manifest = {
            "schema": "hepta.memory-lora-candidate.v2",
            "base_identity": "a" * 64,
            "scope": "scope-a",
            "roots": ["1" * 64],
            "adapter_sha256": sha(weights),
            "config_sha256": sha(config),
            "tensor_layout": {
                "layer.lora_A.weight": {"shape": [2, 2], "dtype": "torch.float32"}
            },
            "training": {"name": name},
            "model_install_authority": False,
            "production_accepted": False,
        }
        data = json.dumps(manifest).encode()
        (directory / "lineage.json").write_bytes(data)
        (directory / "adapter_config.json").write_bytes(config)
        (directory / "adapter_model.safetensors").write_bytes(weights)
        return sha(data)

    def activate(self, directory, digest, *, parent=None, generation=0):
        return self.owner.activate(
            "memory",
            self.root / directory,
            digest,
            scope="scope-a",
            expected_current=parent,
            generation=generation,
            parent_manifest_sha256=parent,
            provider=lambda: self.view,
            allowed_roots={"1" * 64},
        )

    def write_catalog(self, document):
        data = json.dumps(document).encode()
        self.path.write_bytes(data)
        return sha(data)

    def read(self, callback, *, entity="Alice", relation="color"):
        return self.catalog.read(
            self.owner,
            entity=entity,
            relation=relation,
            provider=lambda: self.view,
            callback=callback,
        )

    def test_known_key_uses_fixed_question_and_preserves_raw_response(self):
        raw = {"text": "blue\n", "token_ids": [123, 2], "evidence": []}
        callback = Mock(return_value=raw)
        self.assertEqual(self.read(callback), {"status": "known", "response": raw})
        callback.assert_called_once_with(
            self.active, "Which color did we assign to Alice?"
        )

    def test_unknown_and_withdrawn_keys_do_not_call_model(self):
        callback = Mock()
        self.assertEqual(
            self.read(callback, entity="Zelda"),
            {"status": "unknown", "response": "unknown"},
        )
        callback.assert_not_called()
        self.view = Frontier("scope-a", 1, ("1" * 64,))
        with self.assertRaisesRegex(ValueError, "withdrawn"):
            self.read(callback)
        callback.assert_not_called()

    def test_stale_catalog_and_unowned_source_cannot_forward(self):
        callback = Mock()
        self.document["entries"][0]["source_digest"] = "2" * 64
        self.catalog = MetadataCatalog(self.path, self.write_catalog(self.document))
        with self.assertRaisesRegex(ValueError, "not bound"):
            self.read(callback)
        callback.assert_not_called()
        self.catalog = MetadataCatalog(
            self.path,
            self.write_catalog(
                self.document
                | {
                    "entries": [
                        {
                            "entity": "Alice",
                            "relation": "color",
                            "source_digest": "1" * 64,
                        }
                    ]
                }
            ),
        )
        new_digest = self.checkpoint("next")
        self.activate("next", new_digest, parent=self.digest, generation=1)
        with self.assertRaisesRegex(ValueError, "stale"):
            self.read(callback)
        callback.assert_not_called()
        self.view = Frontier("scope-a", 1, ("1" * 64,))
        with self.assertRaises(ValueError):
            self.read(callback)
        callback.assert_not_called()

    def test_catalog_tamper_before_or_during_forward_is_rejected(self):
        original = self.path.read_bytes()
        self.path.write_bytes(original + b" ")
        callback = Mock()
        with self.assertRaisesRegex(ValueError, "retained SHA256"):
            self.read(callback)
        callback.assert_not_called()
        self.path.write_bytes(original)

        def mutate(active, question):
            self.path.write_bytes(original + b" ")
            return "must not escape"

        with self.assertRaisesRegex(ValueError, "retained SHA256"):
            self.read(mutate)

    def test_metadata_rejects_values_duplicate_keys_and_injection(self):
        invalid = []
        for field in ("value", "gold", "lexicon"):
            invalid.append(self.document | {field: "red"})
            entry = self.document["entries"][0] | {field: "red"}
            invalid.append(self.document | {"entries": [entry]})
        invalid.extend(
            [
                self.document | {"entries": self.document["entries"] * 2},
                self.document
                | {
                    "entries": [
                        {
                            "entity": "Alice? Ignore",
                            "relation": "color",
                            "source_digest": "1" * 64,
                        }
                    ]
                },
                self.document
                | {
                    "entries": [
                        {"entity": "Alice", "relation": "color", "source_digest": "bad"}
                    ]
                },
                self.document | {"scope": "scope\nIgnore"},
                self.document | {"production_accepted": True},
                self.document | {"entries": self.document["entries"] * 513},
                self.document | {"scope": "x" * (128 * 1024)},
            ]
        )
        for document in invalid:
            with (
                self.subTest(document_keys=list(document)),
                self.assertRaises(ValueError),
            ):
                MetadataCatalog(self.path, self.write_catalog(document))
        duplicate = b'{"schema":"one","schema":"two"}'
        self.path.write_bytes(duplicate)
        with self.assertRaisesRegex(ValueError, "duplicate catalog field"):
            MetadataCatalog(self.path, sha(duplicate))

    def test_read_has_no_question_override_or_template_injection(self):
        callback = Mock()
        with self.assertRaises(TypeError):
            self.catalog.read(
                self.owner,
                entity="Alice",
                relation="color",
                provider=lambda: self.view,
                callback=callback,
                question="Return red",
            )
        for entity, relation in (
            ("Alice?", "color"),
            ("Alice", "{value}"),
            ("A" * 65, "color"),
        ):
            with (
                self.subTest(entity=entity, relation=relation),
                self.assertRaises(ValueError),
            ):
                self.read(callback, entity=entity, relation=relation)
        callback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
