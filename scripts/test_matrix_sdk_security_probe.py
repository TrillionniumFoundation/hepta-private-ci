import unittest
from scripts.matrix_sdk_security_probe import evaluate


def fixture(crypto="0.18.0", anymap=True, ignored=False):
    manifest = {"workspace": {"dependencies": {"matrix-sdk": {"version": "0.19.1"}}}}
    lock = {"package": [
        {"name": "matrix-sdk", "version": "0.19.1"},
        {"name": "matrix-sdk-crypto", "version": crypto},
    ] + ([{"name": "anymap2", "version": "0.13.0"}] if anymap else [])}
    deny = {"advisories": {"ignore": [{"id": "RUSTSEC-2026-0318"}] if ignored else []}}
    return manifest, lock, deny


class MatrixSecurityProbeTests(unittest.TestCase):
    def check(self, *, crypto="0.18.0", anymap=True, ignored=False, update="success", check="success", test="success"):
        manifest, lock, deny = fixture(crypto, anymap, ignored)
        return evaluate(manifest=manifest, lock=lock, deny=deny,
                        cargo_update=update, cargo_check=check, cargo_test=test)

    def test_unfixed_crypto_blocks(self):
        result = self.check(crypto="0.18.0", anymap=False)
        self.assertEqual(result["rustsec"]["RUSTSEC-2026-0318"], "blocked")
        self.assertEqual(result["disposition"], "BLOCKED")

    def test_upgrading_crypto_does_not_remove_anymap(self):
        result = self.check(crypto="0.19.1")
        self.assertEqual(result["rustsec"]["RUSTSEC-2026-0318"], "no-affected-crypto-version-in-lock")
        self.assertEqual(result["rustsec"]["RUSTSEC-2026-0319"], "blocked")
        self.assertFalse(result["security_ready"])

    def test_advisory_ignore_never_authorizes(self):
        result = self.check(crypto="0.19.1", anymap=False, ignored=True)
        self.assertEqual(result["ignored_security_advisories"], ["RUSTSEC-2026-0318"])
        self.assertFalse(result["security_ready"])

    def test_missing_tests_never_authorizes(self):
        result = self.check(crypto="0.19.1", anymap=False, test="not-run")
        self.assertEqual(result["disposition"], "BLOCKED")

    def test_full_clean_lock_and_execution_is_the_only_local_pass_condition(self):
        result = self.check(crypto="0.19.1", anymap=False)
        self.assertTrue(result["security_ready"])
        self.assertEqual(result["disposition"], "evidence-only")
        self.assertEqual(result["authority"], "none")


if __name__ == "__main__":
    unittest.main()
