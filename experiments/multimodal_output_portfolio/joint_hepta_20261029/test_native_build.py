"""Lock extraction unit tests; they do not qualify a compiled native owner."""

import tomllib
import unittest

from .native_build import lock_subset, workspace_dependency_versions


REGISTRY = "registry+https://github.com/rust-lang/crates.io-index"


def packages():
    return [
        {"name": "codex-hepta-types", "version": "0.0.0", "dependencies": ["sha2 0.10.9"]},
        {"name": "codex-hepta-infer-core", "version": "0.0.0",
         "dependencies": ["codex-hepta-types", "serde", "serde_json"]},
        {"name": "codex-hepta-neuron", "version": "0.0.0",
         "dependencies": ["codex-hepta-infer-core", "codex-hepta-types", "serde", "serde_json", "pretty_assertions"]},
        *[{"name": name, "version": version, "source": REGISTRY, "checksum": "a" * 64}
          for name, version in (("serde", "1.0.229"), ("serde_json", "1.0.154"),
                                ("sha2", "0.10.9"), ("sha2", "0.11.0"),
                                ("pretty_assertions", "1.4.1"))],
    ]


class NativeLockExtractionTests(unittest.TestCase):
    def test_versions_follow_exact_root_edges_instead_of_old_hardcoded_pins(self):
        rows = packages()
        self.assertEqual(workspace_dependency_versions(rows), {
            "serde": "1.0.229", "serde_json": "1.0.154", "sha2": "0.10.9",
            "pretty_assertions": "1.4.1"})
        next(row for row in rows if row["name"] == "serde")["version"] = "1.0.230"
        self.assertEqual(workspace_dependency_versions(rows)["serde"], "1.0.230")

    def test_ambiguous_lock_edge_is_rejected(self):
        rows = packages()
        rows[0]["dependencies"] = ["sha2"]
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            workspace_dependency_versions(rows)

    def test_nonregistry_workspace_dependency_is_not_silently_replaced(self):
        rows = packages()
        next(row for row in rows if row["name"] == "serde")["source"] = "git+https://example.invalid/serde#fixture"
        with self.assertRaisesRegex(ValueError, "nonregistry"):
            workspace_dependency_versions(rows)

    def test_closure_preserves_original_package_blocks_and_omits_unrelated_version(self):
        blocks = []
        for row in packages():
            block = "[[package]]\n"
            for key, value in row.items():
                if isinstance(value, list):
                    block += key + " = [" + ", ".join('"' + item + '"' for item in value) + "]\n"
                else:
                    block += key + ' = "' + value + '"\n'
            blocks.append(block + "\n")
        raw = "version = 4\n\n" + "".join(blocks)
        subset = lock_subset(raw)
        selected = tomllib.loads(subset)["package"]
        self.assertEqual(len(selected), 7)
        self.assertEqual([row["version"] for row in selected if row["name"] == "sha2"], ["0.10.9"])
        self.assertTrue(all(block in raw for block in subset.split("[[package]]")[1:]))


if __name__ == "__main__":
    unittest.main()
