import copy
import unittest

from adapter_candidate_gate import GIT_REMOTE, audit
from upstream_source_probe import UPSTREAM_GIT_SHA


ORIGINAL = (
    '[workspace.dependencies]\n'
    'matrix-sdk = { version = "0.18.0", default-features = false, '
    'features = ["e2e-encryption", "sqlite"] }\n'
    '[patch.crates-io]\n'
    'matrix-sdk-sqlite = { path = "third_party/matrix-sdk-sqlite-0.18.0" }\n'
).encode()

STAGED = (
    '[workspace.dependencies]\n'
    f'matrix-sdk = {{ git = "{GIT_REMOTE}", '
    f'rev = "{UPSTREAM_GIT_SHA}", version = "0.19.1", '
    'default-features = false, features = ["e2e-encryption", "sqlite"] }\n'
    '[patch.crates-io]\n'
).encode()


def fixture():
    source = f'git+{GIT_REMOTE}?rev={UPSTREAM_GIT_SHA}#{UPSTREAM_GIT_SHA}'
    packages = [
        {"name": "matrix-sdk", "version": "0.19.1", "id": "sdk", "source": source},
        {"name": "matrix-sdk-base", "version": "0.19.1", "id": "base"},
        {"name": "matrix-sdk-crypto", "version": "0.19.1", "id": "crypto"},
        {"name": "matrix-sdk-sqlite", "version": "0.19.1", "id": "sqlite"},
        {"name": "anymap3", "version": "1.0.0", "id": "anymap3"},
        {"name": "codex-hepta-matrix-sdk", "version": "0.0.0", "id": "adapter"},
        {"name": "codex-hepta-matrixd", "version": "0.0.0", "id": "matrixd"},
    ]
    nodes = [
        {"id": "matrixd", "dependencies": ["adapter"]},
        {"id": "adapter", "dependencies": ["sdk"]},
        {"id": "sdk", "dependencies": ["base", "sqlite", "anymap3"],
         "features": ["e2e-encryption", "sqlite"]},
        {"id": "base", "dependencies": ["crypto"]},
        {"id": "crypto", "dependencies": []},
        {"id": "sqlite", "dependencies": ["base"]},
        {"id": "anymap3", "dependencies": []},
    ]
    return {"packages": packages, "resolve": {"nodes": nodes}}


class CandidatePreflightTests(unittest.TestCase):
    def test_approved_disposable_full_family_is_only_preflight_not_accepted(self):
        result = audit(fixture(), ORIGINAL, STAGED)
        self.assertTrue(result["candidate_preflight_passed"], result["errors"])
        self.assertEqual(result["errors"], [])
        self.assertFalse(result["production_authorized"])
        self.assertFalse(result["hepta_adapter_compiled"])
        self.assertFalse(result["cargo_deny_verified"])
        self.assertFalse(result["sqlite_wal_recovery_verified"])

    def test_patched_crypto_and_anymap3_are_both_required(self):
        data = fixture()
        data["packages"].append({"name": "anymap2", "version": "0.13.0", "id": "legacy"})
        self.assertIn("ANYMAP2_STILL_IN_GRAPH",
                      audit(data, ORIGINAL, STAGED)["errors"])
        data = fixture()
        data["packages"][2]["version"] = "0.18.0"
        self.assertFalse(audit(data, ORIGINAL, STAGED)["candidate_preflight_passed"])

    def test_hidden_crypto_version_skew_or_duplicate_is_rejected(self):
        data = fixture()
        data["packages"][3]["version"] = "0.18.0"
        self.assertFalse(audit(data, ORIGINAL, STAGED)["candidate_preflight_passed"])
        data = fixture()
        data["packages"].append(copy.deepcopy(data["packages"][2]))
        self.assertIn("MISSING_OR_MULTIPLE_MATRIX_SDK_CRYPTO",
                      audit(data, ORIGINAL, STAGED)["errors"])

    def test_candidate_source_must_be_exact_upstream_git_sha(self):
        data = fixture()
        data["packages"][0]["source"] = f"registry+{GIT_REMOTE}"
        self.assertIn("SDK_SOURCE_GIT_SHA_NOT_PINNED",
                      audit(data, ORIGINAL, STAGED)["errors"])
        data = fixture()
        data["packages"][0]["source"] = data["packages"][0]["source"].replace(
            UPSTREAM_GIT_SHA, "0" * 40
        )
        self.assertFalse(audit(data, ORIGINAL, STAGED)["candidate_preflight_passed"])

    def test_reject_weakened_e2ee_or_sqlite_features(self):
        data = fixture()
        data["resolve"]["nodes"][2]["features"] = ["sqlite"]
        self.assertIn("SDK_E2EE_SQLITE_FEATURES_NOT_ENABLED",
                      audit(data, ORIGINAL, STAGED)["errors"])
        manifest = STAGED.replace(b'"e2e-encryption", ', b'')
        self.assertIn("UNPINNED_OR_WEAKENED_MATRIX_SDK",
                      audit(fixture(), ORIGINAL, manifest)["errors"])

    def test_unlinked_adapter_or_matrixd_cannot_pass(self):
        data = fixture()
        data["resolve"]["nodes"][1]["dependencies"] = []
        result = audit(data, ORIGINAL, STAGED)
        self.assertIn("HEPTA_ADAPTER_NOT_LINKED_TO_PINNED_SDK_CODEX_HEPTA_MATRIX_SDK",
                      result["errors"])
        self.assertIn("HEPTA_ADAPTER_NOT_LINKED_TO_PINNED_SDK_CODEX_HEPTA_MATRIXD",
                      result["errors"])

    def test_stale_sqlite_patch_or_source_baseline_change_is_rejected(self):
        candidate = STAGED + b'matrix-sdk-sqlite = { path = "third_party/matrix-sdk-sqlite-0.18.0" }\n'
        self.assertIn("OBSOLETE_SQLITE_PATCH_STILL_PRESENT",
                      audit(fixture(), ORIGINAL, candidate)["errors"])
        original = ORIGINAL.replace(b"matrix-sdk = { version = \"0.18.0\"",
                                    b"matrix-sdk = { version = \"0.19.1\"")
        self.assertIn("ORIGINAL_MATRIX_SECURITY_BASELINE_CHANGED",
                      audit(fixture(), original, STAGED)["errors"])

    def test_unreachable_anymap3_or_crypto_is_not_accepted_as_graph_presence(self):
        data = fixture()
        data["resolve"]["nodes"][2]["dependencies"] = ["base", "sqlite"]
        self.assertIn("PINNED_SDK_NOT_LINKED_TO_ANYMAP3",
                      audit(data, ORIGINAL, STAGED)["errors"])
        data = fixture()
        data["resolve"]["nodes"][3]["dependencies"] = []
        self.assertIn("PINNED_SDK_NOT_LINKED_TO_MATRIX_SDK_CRYPTO",
                      audit(data, ORIGINAL, STAGED)["errors"])

    def test_disposable_manifest_cannot_modify_unrelated_dependencies(self):
        other = STAGED + b'# unauthorized comment'
        self.assertIn(
            "DISPOSABLE_WORKSPACE_MANIFEST_UNAUTHORIZED_DRIFT",
            audit(fixture(), ORIGINAL, other)["errors"]
        )
        # E2EE/SQLite scope cannot silently widen; a valid TOML feature edit
        # still differs from the approved exact two-change candidate.
        changed = STAGED.replace(b'"sqlite"', b'"sqlite", "extra"')
        self.assertIn(
            "DISPOSABLE_WORKSPACE_MANIFEST_UNAUTHORIZED_DRIFT",
            audit(fixture(), ORIGINAL, changed)["errors"]
        )

    def test_missing_resolver_or_package_roots_fail_closed(self):
        data = fixture()
        data.pop("resolve")
        self.assertFalse(audit(data, ORIGINAL, STAGED)["candidate_preflight_passed"])
        data = fixture()
        data["packages"] = [x for x in data["packages"] if x["name"] != "matrix-sdk"]
        self.assertFalse(audit(data, ORIGINAL, STAGED)["candidate_preflight_passed"])

    def test_resolver_missing_matrixd_root_or_duplicate_node_fails_closed(self):
        data = fixture()
        data["resolve"]["nodes"] = [
            node for node in data["resolve"]["nodes"] if node["id"] != "matrixd"
        ]
        self.assertFalse(audit(data, ORIGINAL, STAGED)["candidate_preflight_passed"])
        data = fixture()
        data["resolve"]["nodes"].append(data["resolve"]["nodes"][0].copy())
        self.assertIn("DUPLICATE_RESOLVED_NODE",
                      audit(data, ORIGINAL, STAGED)["errors"])


if __name__ == "__main__":
    unittest.main()
