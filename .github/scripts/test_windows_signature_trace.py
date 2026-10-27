import copy
import unittest

from windows_signature_trace import (
    CASES,
    PACKAGE,
    TESTS,
    assess_collector,
    validate_trace,
)


def log():
    return (
        "Starting 2 tests across 1 binaries\n"
        + "".join(f"PASS [ 0.010s] {PACKAGE} {name}\n" for name in TESTS)
        + "Summary [ 0.020s] 2 tests run: 2 passed\n"
    )


def trace(role):
    identity = {
        "ok": True,
        "file_id_16_bytes": list(range(16)),
        "volume_serial_hex": "0000000012345678",
    }
    observation = {
        "id_before": identity,
        "id_after": identity,
        "current_path_id": identity,
        "retained_full_id_unchanged": True,
        "current_path_matches_retained_full_id": True,
        "owner_dacl": {
            "ok": True,
            "descriptor_valid": True,
            "descriptor_bytes": [1, 2, 3],
            "owner_and_dacl_sddl": "diagnostic fixture",
        },
    }
    observation.update(
        {
            key: {
                "ok": False,
                "raw_win32_error": None,
                "kind": "PermissionDenied",
                "message": "indeterminate",
            }
            for key in (
                "canonical_held_id",
                "canonical_private_security",
                "canonical_full_snapshot",
                "canonical_current_path",
            )
        }
    )
    result = {
        "schema": "hepta.windows-original-signature-metadata.v1",
        "original_case": f"{role}::tests::{CASES[role]}",
        "collection_is_not_functional_qualification": True,
        "effective_token": {
            "ok": True,
            "user_sid": {"ok": True, "facts": '"S-1-5-21-1"'},
            "owner_sid": {"ok": True, "facts": '"S-1-5-21-1"'},
        },
        "namespace": "hepta-vnext-operator-acceptance-v1",
        "original_verify" if role == "trust" else "original_assess": {
            "ok": False,
            "result": "actual private-identity failure remains failure",
        },
    }
    result.update(
        {
            key: copy.deepcopy(observation)
            for key in (
                "generated_signature_before",
                "generated_signature_after",
                "private_allowed_signers_control",
                "private_policy_control",
            )
        }
    )
    return result


class SignatureCollectorRejectionTests(unittest.TestCase):
    def test_only_exact_two_collectors_are_accepted(self):
        self.assertTrue(assess_collector(0, log())["passed"])
        for bad in (
            log() + log(),
            log().replace(TESTS[1], TESTS[0]),
            log().replace(TESTS[1], "unknown"),
            log().replace("Starting 2", "Starting 1"),
            log().replace("PASS", "FAIL", 1),
            log().replace(PACKAGE, "unknown", 1),
            log().replace("Summary", "missing"),
        ):
            self.assertFalse(assess_collector(0, bad)["passed"])
        self.assertFalse(assess_collector(1, log())["passed"])

    def test_original_refusal_is_collected_without_becoming_functional_success(self):
        for role in CASES:
            self.assertFalse(validate_trace(role, trace(role))["ok"])

    def test_missing_metadata_or_truncated_identity_is_rejected(self):
        for key in (
            "generated_signature_before",
            "generated_signature_after",
            "private_allowed_signers_control",
            "private_policy_control",
        ):
            bad = trace("trust")
            del bad[key]
            with self.assertRaises(ValueError):
                validate_trace("trust", bad)
            bad = trace("trust")
            bad[key]["id_before"]["file_id_16_bytes"] = [1] * 8
            with self.assertRaises(ValueError):
                validate_trace("trust", bad)

    def test_changed_signature_identity_and_dacl_are_rejected(self):
        for field in ("id_before", "owner_dacl"):
            bad = trace("trust")
            bad["generated_signature_after"][field]["changed"] = True
            with self.assertRaises(ValueError):
                validate_trace("trust", bad)

    def test_unknown_original_case_and_missing_result_are_rejected(self):
        for key, value in (
            ("original_case", "other"),
            ("original_verify", {}),
            ("effective_token", {}),
            ("collection_is_not_functional_qualification", False),
        ):
            bad = trace("trust")
            bad[key] = value
            with self.assertRaises(ValueError):
                validate_trace("trust", bad)


if __name__ == "__main__":
    unittest.main()
