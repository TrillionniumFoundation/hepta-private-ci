"""Fast, offline adversarial tests of YAML security lock migration gate."""
import copy
import unittest

from check_yaml_lock_migration import (
    CORE, EXPECTED_DIRECT_USERS, PIN, SHIM, check,
)


def fixture():
    before = {"package": [
        {"name": "serde_yaml", "version": "0.9.34", "source": "registry+https://github.com/rust-lang/crates.io-index", "dependencies": ["unsafe-libyaml"]},
        {"name": "unsafe-libyaml", "version": "0.2.11", "source": "registry+https://github.com/rust-lang/crates.io-index"},
        {"name": "safe", "version": "1.0.0", "source": "registry+https://github.com/rust-lang/crates.io-index"},
        *({"name": name, "version": "0.0.0", "dependencies": ["serde_yaml", "safe"]} for name in sorted(EXPECTED_DIRECT_USERS)),
    ]}
    after = {"package": [
        {"name": SHIM, "version": PIN, "source": "registry+https://github.com/rust-lang/crates.io-index", "dependencies": [CORE]},
        {"name": CORE, "version": PIN, "source": "registry+https://github.com/rust-lang/crates.io-index", "dependencies": ["safe"]},
        {"name": "safe", "version": "1.0.0", "source": "registry+https://github.com/rust-lang/crates.io-index"},
        *({"name": name, "version": "0.0.0", "dependencies": [SHIM, "safe"]} for name in sorted(EXPECTED_DIRECT_USERS)),
    ]}
    manifest = {"workspace": {"dependencies": {"serde_yaml": {"package": SHIM, "version": f"={PIN}"}}}}
    return before, after, manifest


class MigrationContractTests(unittest.TestCase):
    def test_only_expected_replacement_still_blocks_global_security_clearance(self):
        before, after, manifest = fixture()
        result = check(before, after, manifest)
        self.assertEqual(result["status"], "yaml_lock_migration_verified_not_full_security_clearance")
        self.assertFalse(result["global_cargo_deny_passed"])
        self.assertFalse(result["matrix_security_gate_passed"])
        self.assertFalse(result["production_promotion_permitted"])
        self.assertFalse(result["advisory_ignore_added"])
        self.assertEqual(len(result["changed_direct_users"]), 4)
        self.assertEqual({r[0] for r in result["removed_dependencies"]}, {"unsafe-libyaml", "serde_yaml"})

    def test_old_yaml_parser_must_be_absent(self):
        for name in ("unsafe-libyaml", "serde_yaml"):
            before, after, manifest = fixture()
            after["package"].append({"name": name, "version": "0.2.11"})
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "still in Cargo.lock"):
                check(before, after, manifest)

    def test_reject_unrelated_lock_upgrade_and_dependency_removal(self):
        before, after, manifest = fixture()
        for item in after["package"]:
            if item["name"] == "safe":
                item["version"] = "1.0.1"
        with self.assertRaisesRegex(ValueError, "unrelated baseline dependencies were removed"):
            check(before, after, manifest)
        before, after, manifest = fixture()
        for item in after["package"]:
            if item["name"] == "safe":
                item["dependencies"] = ["some-new-optional-crate"]
        with self.assertRaisesRegex(ValueError, "unrelated locked dependency records changed"):
            check(before, after, manifest)

    def test_exact_versions_registry_and_direct_users_required(self):
        before, after, manifest = fixture()
        manifest["workspace"]["dependencies"]["serde_yaml"]["version"] = "^0.0"
        with self.assertRaisesRegex(ValueError, "exact maintained shim"):
            check(before, after, manifest)
        before, after, manifest = fixture()
        next(p for p in after["package"] if p["name"] == SHIM)["version"] = "0.0.57"
        with self.assertRaisesRegex(ValueError, "incorrect exact pinned"):
            check(before, after, manifest)
        before, after, manifest = fixture()
        next(p for p in after["package"] if p["name"] == "codex-skills")["dependencies"] = ["safe"]
        with self.assertRaisesRegex(ValueError, "not linked"):
            check(before, after, manifest)
        before, after, manifest = fixture()
        after["package"].append(copy.deepcopy(after["package"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate Cargo.lock package"):
            check(before, after, manifest)


if __name__ == "__main__":
    unittest.main()
