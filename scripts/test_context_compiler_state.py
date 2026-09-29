#!/usr/bin/env python3
"""Local document/source-identity tests, not native execution qualification."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import generate_context_compiler_module_docs as docs


def blob(content):
    return hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()


class CurrentStateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.state = copy.deepcopy(docs.load_state())
        self.source = self.root / "source.rs"
        self.source.write_bytes(b"pub fn guarded() {}\n")
        self.small = {"runtimeSourceFiles": [{"path": "source.rs", "blobSha": blob(self.source.read_bytes())}]}

    def write_state(self, state):
        path = self.root / docs.STATE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state), encoding="utf-8")

    def test_registered_runtime_bytes_match_the_current_git_blobs(self):
        docs.validate_runtime_sources(self.state)

    def test_modified_source_is_rejected(self):
        self.source.write_bytes(b"pub fn unguarded() {}\n")
        with self.assertRaises(ValueError):
            docs.validate_runtime_sources(self.small, self.root)

    def test_missing_source_is_rejected(self):
        self.source.unlink()
        with self.assertRaises(OSError):
            docs.validate_runtime_sources(self.small, self.root)

    def test_duplicate_and_escaping_source_paths_are_rejected(self):
        duplicate = copy.deepcopy(self.small)
        duplicate["runtimeSourceFiles"] *= 2
        with self.assertRaises(ValueError):
            docs.validate_runtime_sources(duplicate, self.root)
        for path in ("../source.rs", "/source.rs"):
            invalid = copy.deepcopy(self.small)
            invalid["runtimeSourceFiles"][0]["path"] = path
            with self.assertRaises(ValueError):
                docs.validate_runtime_sources(invalid, self.root)

    def test_symlinked_source_is_rejected(self):
        link = self.root / "linked.rs"
        try:
            link.symlink_to(self.source)
        except OSError:
            self.skipTest("symlinks unavailable on this host")
        self.small["runtimeSourceFiles"][0]["path"] = "linked.rs"
        with self.assertRaises(ValueError):
            docs.validate_runtime_sources(self.small, self.root)

    def test_source_cannot_self_grant_acceptance_or_execution(self):
        for key in ("independentAcceptance", "activation", "release", "exactHeadExecution"):
            invalid = copy.deepcopy(self.state)
            invalid["maturity"][key] = "passed" if key == "exactHeadExecution" else True
            self.write_state(invalid)
            with self.assertRaises(ValueError):
                docs.load_state(self.root)

    def test_complete_with_open_gates_and_short_anchors_are_rejected(self):
        invalid = copy.deepcopy(self.state)
        invalid["status"]["v2ProviderClosure"] = "complete"
        self.write_state(invalid)
        with self.assertRaises(ValueError):
            docs.load_state(self.root)
        invalid = copy.deepcopy(self.state)
        invalid["runtimeSourceAnchor"] = "deadbeef"
        self.write_state(invalid)
        with self.assertRaises(ValueError):
            docs.load_state(self.root)

    def test_duplicate_state_keys_are_rejected(self):
        with self.assertRaises(ValueError):
            json.loads('{"module":"context.compiler","module":"other"}', object_pairs_hook=docs.unique_object)

    def test_five_projections_are_deterministic_and_share_state_digest(self):
        first = docs.render_all(self.state)
        self.assertEqual(first, docs.render_all(copy.deepcopy(self.state)))
        self.assertEqual(set(first), set(docs.OUTPUTS.values()))
        digest = docs.canonical_hash(self.state)
        for path, content in first.items():
            self.assertIn(digest, content, str(path))

    def test_consumer_rows_bind_real_source_and_complete_native_inventory(self):
        docs.validate_consumer_execution(self.state)
        broken = copy.deepcopy(self.state)
        broken["consumerExecution"][0]["consumer"]["call"] = "NONEXISTENT_PRODUCT_CALL"
        with self.assertRaises(ValueError):
            docs.validate_consumer_execution(broken)
        broken = copy.deepcopy(self.state)
        broken["consumerExecution"][0]["testSources"] = []
        with self.assertRaises(ValueError):
            docs.validate_consumer_execution(broken)

    def test_source_rows_cannot_promote_a_missing_consumer_or_product_e2e(self):
        for mutation in ("consumer", "authenticatedProductE2E", "exactExecution"):
            broken = copy.deepcopy(self.state)
            row = broken["consumerExecution"][0]
            row[mutation] = None if mutation == "consumer" else "passed"
            with self.assertRaises(ValueError):
                docs.validate_consumer_execution(broken)

    def test_projection_keeps_contract_inventory_and_uses_current_narrative(self):
        state = copy.deepcopy(self.state)
        state["verificationNarrative"] = "TEST-ONLY-VERIFICATION-SENTINEL"
        state["productCallGraph"] = "TEST-ONLY-CALL-GRAPH-SENTINEL\n"
        rendered = docs.render_all(state)
        for kind in ("technical", "product", "dossier"):
            self.assertIn(state["verificationNarrative"], rendered[docs.OUTPUTS[kind]])
            self.assertIn(state["productCallGraph"], rendered[docs.OUTPUTS[kind]])
        for kind, filename in (("map", "IMPLEMENTATION_MAP.json"), ("manifest", "MODULE_MANIFEST.json")):
            baseline = json.loads((docs.ROOT / "docs/modules/context.compiler/design-baseline" / filename).read_text())
            current = json.loads(rendered[docs.OUTPUTS[kind]])
            for key in ("publicSurface", "proofObjects", "byteIdentities", "invariants", "testMatrix"):
                self.assertEqual(baseline[key], current[key])
            self.assertEqual(current["runtimeSourceFiles"], state["runtimeSourceFiles"])
            self.assertEqual(current["status"], state["status"])


if __name__ == "__main__":
    unittest.main()
