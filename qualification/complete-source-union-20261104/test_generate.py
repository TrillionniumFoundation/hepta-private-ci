"""Strict controls for the composed-lock adoption boundary."""
import copy
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location("union_generate", Path(__file__).with_name("generate.py"))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

SOURCE = "registry+https://github.com/rust-lang/crates.io-index"
OLD_UNICODE = {"name": "unicode-normalization", "version": "0.1.25",
               "source": SOURCE, "checksum": "old", "dependencies": ["tinyvec"]}
NEW_UNICODE = {"name": "unicode-normalization", "version": "0.1.26",
               "source": SOURCE, "checksum": "new", "dependencies": ["tinyvec"]}
CONTROL = {"name": "hepta-control-core", "version": "0.1.0", "dependencies": ["unicode-normalization"]}
TINYVEC = {"name": "tinyvec", "version": "1.10.0", "source": SOURCE, "checksum": "unchanged"}
LOCAL = {"name": "owner", "version": "0.1.0", "dependencies": ["tinyvec"]}
CONFIG = {"unicode_before": OLD_UNICODE, "unicode_after": NEW_UNICODE,
          "new_local_package": CONTROL, "allowed_local_dependency_packages": ["owner"],
          "reviewed_registry_dependency_changes": [], "expected_registry_record_change_count": 0}


def encode(rows, version=4):
    import json
    result = [f"version = {version}"]
    for row in rows:
        result.append("[[package]]")
        result.extend(f"{key} = {json.dumps(value)}" for key, value in row.items())
    return ("\n".join(result) + "\n").encode()


class LockBoundaryControls(unittest.TestCase):
    def setUp(self):
        self.before = encode([OLD_UNICODE, TINYVEC, LOCAL])
        self.rows = [copy.deepcopy(NEW_UNICODE), copy.deepcopy(TINYVEC),
                     copy.deepcopy(LOCAL), copy.deepcopy(CONTROL)]
        self.rows[2]["dependencies"].append("hepta-control-core")

    def check(self, rows=None, config=None):
        return MODULE.compare_cargo(self.before, encode(rows or self.rows), config or CONFIG)

    def test_exact_reviewed_identity_and_manifest_edges(self):
        result = self.check()
        self.assertEqual(result["generated_packages"], 4)
        self.assertTrue(result["all_other_versions_sources_checksums_unchanged"])
        self.assertEqual(len(result["local_dependency_changes"]), 1)

    def test_unknown_registry_version_rejected(self):
        self.rows[1]["version"] = "1.11.0"
        with self.assertRaisesRegex(RuntimeError, "unreviewed"):
            self.check()

    def test_unchanged_identity_checksum_mutation_rejected(self):
        self.rows[1]["checksum"] = "mutated"
        with self.assertRaisesRegex(RuntimeError, "unrelated"):
            self.check()

    def test_wrong_new_unicode_checksum_rejected(self):
        self.rows[0]["checksum"] = "mutated"
        with self.assertRaisesRegex(RuntimeError, "Unicode"):
            self.check()

    def test_external_substitution_of_local_package_rejected(self):
        self.rows[3]["source"] = SOURCE
        with self.assertRaisesRegex(RuntimeError, "unreviewed"):
            self.check()

    def test_missing_prior_package_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "unreviewed"):
            self.check(self.rows[:1] + self.rows[2:])

    def test_duplicate_package_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "duplicate"):
            self.check(self.rows + [copy.deepcopy(self.rows[0])])

    def test_undeclared_local_dependency_change_rejected(self):
        config = {**CONFIG, "allowed_local_dependency_packages": []}
        with self.assertRaisesRegex(RuntimeError, "unrelated"):
            self.check(config=config)

    def test_changed_lock_header_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "header"):
            MODULE.compare_cargo(self.before, encode(self.rows, version=3), CONFIG)

    def test_git_and_sha256_bind_actual_byte_sequence(self):
        self.assertEqual(MODULE.identity(b"hello\n"), {
            "bytes": 6, "sha256": "5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03",
            "git_blob": "ce013625030ba8dba906f756967f9e9ca394464a",
        })


class ExactRegistryTransitionControls(unittest.TestCase):
    def setUp(self):
        self.previous = {**TINYVEC, "dependencies": ["left 1.0.0"]}
        self.current = {**TINYVEC, "dependencies": ["left 2.0.0"]}
        targets = [
            {"name": "left", "version": "1.0.0", "source": SOURCE, "checksum": "left-one"},
            {"name": "left", "version": "2.0.0", "source": SOURCE, "checksum": "left-two"},
        ]
        self.before = encode([OLD_UNICODE, self.previous, LOCAL, *targets])
        self.rows = copy.deepcopy([NEW_UNICODE, self.current, LOCAL, CONTROL, *targets])
        self.config = {
            **copy.deepcopy(CONFIG),
            "reviewed_registry_dependency_changes": [
                {"before": copy.deepcopy(self.previous), "after": copy.deepcopy(self.current)}
            ],
            "expected_registry_record_change_count": 1,
        }

    def check(self):
        return MODULE.compare_cargo(self.before, encode(self.rows), self.config)

    def test_exact_complete_reviewed_transition_is_recorded(self):
        result = self.check()
        self.assertEqual(result["registry_dependency_changes"], [
            {"package": ["tinyvec", "1.10.0", SOURCE],
             "before": self.previous, "after": self.current}
        ])

    def test_unreviewed_edge_between_existing_packages_rejected(self):
        self.config["reviewed_registry_dependency_changes"] = []
        self.config["expected_registry_record_change_count"] = 0
        with self.assertRaisesRegex(RuntimeError, "unrelated"):
            self.check()

    def test_extra_edge_even_to_an_existing_package_rejected(self):
        self.rows[1]["dependencies"].append("hepta-control-core")
        with self.assertRaisesRegex(RuntimeError, "registry result differs"):
            self.check()

    def test_incorrect_reviewed_baseline_rejected(self):
        self.config["reviewed_registry_dependency_changes"][0]["before"]["dependencies"] = ["left 3.0.0"]
        with self.assertRaisesRegex(RuntimeError, "baseline differs"):
            self.check()

    def test_reviewed_transition_missing_from_generated_lock_rejected(self):
        self.rows[1] = copy.deepcopy(self.previous)
        with self.assertRaisesRegex(RuntimeError, "registry result differs"):
            self.check()

    def test_duplicate_reviewed_identity_rejected(self):
        self.config["reviewed_registry_dependency_changes"] *= 2
        self.config["expected_registry_record_change_count"] = 2
        with self.assertRaisesRegex(RuntimeError, "duplicate reviewed registry"):
            self.check()

    def test_noop_reviewed_transition_rejected(self):
        self.config["reviewed_registry_dependency_changes"][0]["after"] = copy.deepcopy(self.previous)
        self.rows[1] = copy.deepcopy(self.previous)
        with self.assertRaisesRegex(RuntimeError, "transition is empty"):
            self.check()

    def test_review_cannot_authorize_checksum_mutation(self):
        self.config["reviewed_registry_dependency_changes"][0]["after"]["checksum"] = "changed"
        self.rows[1]["checksum"] = "changed"
        with self.assertRaisesRegex(RuntimeError, "non-dependency field"):
            self.check()

    def test_unchanged_target_package_checksum_still_rejected(self):
        self.rows[-1]["checksum"] = "changed"
        with self.assertRaisesRegex(RuntimeError, "unrelated"):
            self.check()

    def test_duplicate_reviewed_dependency_rejected(self):
        self.config["reviewed_registry_dependency_changes"][0]["after"]["dependencies"] *= 2
        self.rows[1]["dependencies"] *= 2
        with self.assertRaisesRegex(RuntimeError, "duplicate reviewed registry dependency"):
            self.check()

    def test_incomplete_review_inventory_rejected(self):
        self.config["expected_registry_record_change_count"] = 2
        with self.assertRaisesRegex(RuntimeError, "transition count differs"):
            self.check()


class ActualMetadataBoundaryControls(unittest.TestCase):
    def setUp(self):
        package_id = lambda name, version: SOURCE + "#" + name + "@" + version
        dependency = {
            "name": "left", "source": SOURCE, "req": ">=1, <3", "kind": None,
            "rename": None, "optional": False, "uses_default_features": True,
            "features": [], "target": None, "registry": None,
        }
        packages = [
            {"name": "tinyvec", "version": "1.10.0", "source": SOURCE,
             "id": package_id("tinyvec", "1.10.0"), "dependencies": [dependency], "features": {}},
            {"name": "left", "version": "1.0.0", "source": SOURCE,
             "id": package_id("left", "1.0.0"), "dependencies": [], "features": {}},
            {"name": "left", "version": "2.0.0", "source": SOURCE,
             "id": package_id("left", "2.0.0"), "dependencies": [], "features": {}},
        ]
        nodes = [
            {"id": packages[0]["id"], "dependencies": [packages[2]["id"]],
             "deps": [{"name": "left", "pkg": packages[2]["id"],
                       "dep_kinds": [{"kind": None, "target": None}]}], "features": []},
            {"id": packages[1]["id"], "dependencies": [], "deps": [], "features": []},
            {"id": packages[2]["id"], "dependencies": [], "deps": [], "features": []},
        ]
        self.metadata = {"version": 1, "packages": packages, "resolve": {"nodes": nodes}}
        self.locked = {
            (package["name"], package["version"], package["source"]): {}
            for package in packages
        }
        self.config = {
            "reviewed_registry_dependency_changes": [
                {"before": TINYVEC, "after": {**TINYVEC, "dependencies": ["left 2.0.0"]}}
            ],
            "reviewed_registry_metadata": [{
                "identity": ["tinyvec", "1.10.0", SOURCE],
                "package_id": packages[0]["id"],
                "manifest_dependencies": copy.deepcopy([dependency]),
                "manifest_features": {},
                "resolve_node": copy.deepcopy(nodes[0]),
            }],
        }

    def check(self):
        return MODULE.verify_metadata_graph(self.metadata, self.locked, self.config)

    def test_exact_actual_metadata_identities_and_full_reviewed_node(self):
        self.assertEqual(self.check()["reviewed_registry_records"], 1)

    def test_actual_manifest_requirement_mutation_rejected(self):
        self.metadata["packages"][0]["dependencies"][0]["req"] = ">=1, <4"
        with self.assertRaisesRegex(RuntimeError, "manifest declarations"):
            self.check()

    def test_resolution_rebound_to_another_present_version_rejected(self):
        node = self.metadata["resolve"]["nodes"][0]
        other = self.metadata["packages"][1]["id"]
        node["dependencies"] = [other]
        node["deps"][0]["pkg"] = other
        with self.assertRaisesRegex(RuntimeError, "resolved edges"):
            self.check()

    def test_actual_metadata_source_substitution_rejected(self):
        self.metadata["packages"][1]["source"] = None
        with self.assertRaisesRegex(RuntimeError, "package identities differ"):
            self.check()

    def test_duplicate_actual_metadata_identity_rejected(self):
        duplicate = copy.deepcopy(self.metadata["packages"][1])
        duplicate["id"] += "-duplicate"
        self.metadata["packages"].append(duplicate)
        with self.assertRaisesRegex(RuntimeError, "duplicate actual Cargo metadata"):
            self.check()

    def test_missing_resolver_node_rejected(self):
        self.metadata["resolve"]["nodes"].pop()
        with self.assertRaisesRegex(RuntimeError, "node inventory"):
            self.check()

    def test_mixed_diagnostics_preserve_single_complete_metadata(self):
        import json
        raw = b" Downloading crates ...\n" + json.dumps(self.metadata).encode() + b"\n"
        self.assertEqual(MODULE.metadata_document(raw), self.metadata)

    def test_two_complete_metadata_documents_rejected(self):
        import json
        raw = (json.dumps(self.metadata) + "\n").encode() * 2
        with self.assertRaisesRegex(RuntimeError, "exactly one complete"):
            MODULE.metadata_document(raw)

    def test_truncated_metadata_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "exactly one complete"):
            MODULE.metadata_document(b'Downloading ...\n{"packages":[],"resolve":')


if __name__ == "__main__":
    unittest.main()
