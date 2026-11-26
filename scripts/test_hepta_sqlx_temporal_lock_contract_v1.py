"""Frozen synthetic lock-contract controls for one future <=5 second scope.

These are complete minimal TOML lock documents, not downloaded dependencies.
Checksums below are synthetic literals. No registry, resolver, compiler or
application test is invoked; these controls do not count toward E1–E6 or 12+3.
"""

import re
import tomllib
import unittest

import hepta_sqlx_temporal_lock_contract_v1 as contract


REGISTRY = "registry+https://github.com/rust-lang/crates.io-index"
FIXTURE_NAME = "sqlx-temporal-default-contract-v1"

BASELINE = """
version = 4

[[package]]
name = "app"
version = "0.0.0"
dependencies = ["sqlx", "time"]

[[package]]
name = "sqlx"
version = "0.9.1"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
dependencies = ["chrono", "sqlx-core"]

[[package]]
name = "sqlx-core"
version = "0.9.1"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
dependencies = ["chrono", "time"]

[[package]]
name = "chrono"
version = "0.4.45"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"

[[package]]
name = "time"
version = "0.3.47"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
"""

MAIN_WITHOUT_SQLX_CHRONO = """
version = 4

[[package]]
name = "app"
version = "0.0.0"
dependencies = ["sqlx", "time"]

[[package]]
name = "sqlx"
version = "0.9.1"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
dependencies = ["sqlx-core"]

[[package]]
name = "sqlx-core"
version = "0.9.1"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
dependencies = ["time"]

[[package]]
name = "time"
version = "0.3.47"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
"""

FIXTURE_ROOT = """
[[package]]
name = "sqlx-temporal-default-contract-v1"
version = "0.0.0"
dependencies = ["app", "sqlx"]
"""

CHRONO_ROW = """
[[package]]
name = "chrono"
version = "0.4.45"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
"""

TIME_ROW = """
[[package]]
name = "time"
version = "0.3.47"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
"""

SECOND_TIME_ROW = """
[[package]]
name = "time"
version = "0.3.46"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
"""

FOREIGN_ROW = """
[[package]]
name = "foreign"
version = "1.0.0"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
"""

SQLX_ROW = """
[[package]]
name = "sqlx"
version = "0.9.1"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
dependencies = ["chrono", "sqlx-core"]
"""


def changed(source, before, after):
    if source.count(before) != 1:
        raise AssertionError(
            "synthetic TOML mutation does not select exactly one source span"
        )
    return source.replace(before, after, 1)


class SqlxLockContractTests(unittest.TestCase):
    def refuses(self, baseline, candidate, reason, fixture_name=None):
        with self.assertRaisesRegex(ValueError, "^" + re.escape(reason) + "$"):
            contract.lock_relation(
                tomllib.loads(baseline), tomllib.loads(candidate), fixture_name
            )

    def test_main_sqlx_chrono_removal_is_allowed(self):
        result = contract.lock_relation(
            tomllib.loads(BASELINE), tomllib.loads(MAIN_WITHOUT_SQLX_CHRONO)
        )
        self.assertEqual(result["packages"], 4)
        self.assertEqual(result["removed_identities"], [("chrono", "0.4.45", REGISTRY)])
        self.assertEqual(result["added_identities"], [])
        self.assertIs(result["qualification"], False)

    def test_independent_fixture_subset_is_allowed(self):
        result = contract.lock_relation(
            tomllib.loads(BASELINE),
            tomllib.loads(MAIN_WITHOUT_SQLX_CHRONO + FIXTURE_ROOT),
            FIXTURE_NAME,
        )
        self.assertEqual(result["packages"], 5)
        self.assertEqual(result["added_identities"], [(FIXTURE_NAME, "0.0.0", None)])
        self.assertIs(result["registry_versions_and_checksums_reused"], True)
        self.assertIs(result["qualification"], False)

    def test_equivalent_dependency_version_spelling_is_allowed(self):
        candidate = changed(
            MAIN_WITHOUT_SQLX_CHRONO,
            'dependencies = ["sqlx", "time"]',
            'dependencies = ["sqlx 0.9.1", "time 0.3.47"]',
        )
        result = contract.lock_relation(
            tomllib.loads(BASELINE), tomllib.loads(candidate)
        )
        self.assertEqual(result["packages"], 4)
        self.assertEqual(result["added_identities"], [])

    def test_registry_version_drift_is_refused(self):
        candidate = changed(
            MAIN_WITHOUT_SQLX_CHRONO,
            'name = "sqlx"\nversion = "0.9.1"',
            'name = "sqlx"\nversion = "0.9.2"',
        )
        self.refuses(
            BASELINE, candidate, "generated lock added an unreviewed package identity"
        )

    def test_registry_checksum_drift_is_refused(self):
        candidate = changed(
            MAIN_WITHOUT_SQLX_CHRONO,
            'checksum = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"',
            'checksum = "9999999999999999999999999999999999999999999999999999999999999999"',
        )
        self.refuses(
            BASELINE,
            candidate,
            "package version, source, checksum or other attributes drifted",
        )

    def test_non_sqlx_dependency_change_is_refused(self):
        candidate = changed(
            MAIN_WITHOUT_SQLX_CHRONO,
            'dependencies = ["sqlx", "time"]',
            'dependencies = ["sqlx"]',
        )
        self.refuses(BASELINE, candidate, "non-SQLx root-lock dependencies changed")

    def test_sqlx_non_chrono_removal_is_refused(self):
        candidate = changed(
            MAIN_WITHOUT_SQLX_CHRONO,
            'dependencies = ["sqlx-core"]',
            "dependencies = []",
        )
        self.refuses(
            BASELINE,
            candidate,
            "SQLx root-lock change exceeds the removed Chrono capability",
        )

    def test_foreign_fixture_identity_is_refused(self):
        candidate = MAIN_WITHOUT_SQLX_CHRONO + FIXTURE_ROOT + FOREIGN_ROW
        candidate = changed(
            candidate,
            'dependencies = ["app", "sqlx"]',
            'dependencies = ["app", "foreign", "sqlx"]',
        )
        self.refuses(
            BASELINE,
            candidate,
            "generated lock added an unreviewed package identity",
            FIXTURE_NAME,
        )

    def test_foreign_fixture_dependency_edge_is_refused(self):
        candidate = MAIN_WITHOUT_SQLX_CHRONO + FIXTURE_ROOT + CHRONO_ROW
        candidate = changed(
            candidate, TIME_ROW, TIME_ROW + 'dependencies = ["chrono"]\n'
        )
        self.refuses(
            BASELINE,
            candidate,
            "fixture selected a different dependency version or source",
            FIXTURE_NAME,
        )

    def test_duplicate_package_identity_is_refused(self):
        self.refuses(
            BASELINE + SQLX_ROW,
            MAIN_WITHOUT_SQLX_CHRONO,
            "Cargo package identities repeat or are absent",
        )

    def test_ambiguous_dependency_identity_is_refused(self):
        self.refuses(
            BASELINE + SECOND_TIME_ROW,
            MAIN_WITHOUT_SQLX_CHRONO + SECOND_TIME_ROW,
            "Cargo dependency is absent or ambiguous: time",
        )

    def test_absent_dependency_identity_is_refused(self):
        candidate = changed(MAIN_WITHOUT_SQLX_CHRONO, TIME_ROW, "")
        self.refuses(
            BASELINE, candidate, "Cargo dependency is absent or ambiguous: time"
        )


if __name__ == "__main__":
    unittest.main()
