"""Whole-network persistence, scope, binding, and read-channel tests."""

import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np

from memory_cells.encoding import FrozenEncoder, canonical_bytes
from memory_cells.model import MemoryCell
from memory_cells.network import MemoryNetwork, write_network_manifest
from memory_cells.routing import LearnedRouter


class MemoryNetworkTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.encoder = FrozenEncoder(64, 5)
        self.domains = ("alpha", "beta")
        self.queries, self.targets, self.cells = [], [], {}
        for index, domain in enumerate(self.domains):
            keys = [f"item:{domain}-{number:03d}" for number in range(12)]
            targets = np.random.default_rng(37 + index).integers(0, 8, len(keys))
            model = MemoryCell(64, 8, 8, seed=index)
            model.fit(self.encoder.encode(keys), targets, steps=180, lr=0.04)
            model.save(
                self.root / "cells" / str(index),
                encoder_manifest=self.encoder.manifest(),
            )
            self.cells[domain] = model
            self.targets.extend(targets.tolist())
            self.queries.extend(
                SimpleNamespace(
                    key=key, domain=domain, text=f"lookup {domain} {key}", split="train"
                )
                for key in keys
            )
        self.router = LearnedRouter(self.domains, encoder=self.encoder, rank=4, seed=17)
        self.router.fit(self.queries, steps=160, lr=0.04)
        self.router.save(self.root / "router")
        self.manifest = write_network_manifest(self.root, self.domains, scope="fixture")

    def rewrite_network(self, manifest):
        body = {
            key: value for key, value in manifest.items() if key != "manifest_sha256"
        }
        manifest["manifest_sha256"] = hashlib.sha256(canonical_bytes(body)).hexdigest()
        (self.root / "network.json").write_bytes(canonical_bytes(manifest))

    def test_reload_composes_cells_and_router_without_targets(self):
        loaded = MemoryNetwork.load(self.root, expected_scope="fixture")
        typed, routes, raw_confidence = loaded.predict(self.queries, route="typed")
        self.assertEqual(typed, self.targets)
        self.assertEqual(routes, [query.domain for query in self.queries])
        self.assertTrue(all(0 <= value <= 1 for value in raw_confidence))
        expected_routes = self.router.route(self.queries)
        expected = [
            int(self.cells[domain].predict(self.encoder.encode([query.key]))[0])
            for domain, query in zip(expected_routes, self.queries)
        ]
        actual, routes, _ = loaded.predict(self.queries, route="learned")
        self.assertEqual((actual, routes), (expected, expected_routes))
        literal, _, _ = loaded.predict(self.queries, route="literal")
        self.assertEqual(literal, typed)
        self.assertEqual(
            loaded.parameter_bytes,
            sum(cell.parameter_bytes for cell in self.cells.values())
            + self.router.parameter_bytes,
        )
        self.assertFalse(
            any(
                query.key in (self.root / "network.json").read_text()
                for query in self.queries
            )
        )

    def test_scope_and_unknown_route_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "scope mismatch"):
            MemoryNetwork.load(self.root, expected_scope="another")
        loaded = MemoryNetwork.load(self.root, expected_scope="fixture")
        with self.assertRaisesRegex(ValueError, "route must"):
            loaded.predict(self.queries, route="oracle")

    def test_extra_history_is_not_an_admitted_manifest_channel(self):
        manifest = json.loads((self.root / "network.json").read_text())
        manifest["history"] = [{"key": "secret", "target": 4}]
        self.rewrite_network(manifest)
        with self.assertRaisesRegex(ValueError, "manifest fields"):
            MemoryNetwork.load(self.root, expected_scope="fixture")

    def test_path_escape_and_cell_binding_tampering_are_rejected(self):
        manifest = json.loads((self.root / "network.json").read_text())
        manifest["cells"][0]["path"] = "../outside"
        self.rewrite_network(manifest)
        with self.assertRaisesRegex(ValueError, "escapes"):
            MemoryNetwork.load(self.root, expected_scope="fixture")
        manifest["cells"][0]["path"] = "cells/0"
        manifest["cells"][0]["manifest_sha256"] = "0" * 64
        self.rewrite_network(manifest)
        with self.assertRaisesRegex(ValueError, "cell manifest binding"):
            MemoryNetwork.load(self.root, expected_scope="fixture")

    def test_router_bytes_are_bound_even_for_semantically_equivalent_json(self):
        path = self.root / "router" / "router.json"
        path.write_text(json.dumps(json.loads(path.read_text()), indent=2))
        with self.assertRaisesRegex(ValueError, "router manifest binding"):
            MemoryNetwork.load(self.root, expected_scope="fixture")


if __name__ == "__main__":
    unittest.main()
