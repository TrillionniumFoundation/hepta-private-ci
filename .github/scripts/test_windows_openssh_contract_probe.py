"""Local rejection controls for diagnostic receipts; no native capability claims."""

import base64
import hashlib
import unittest

import windows_openssh_contract_probe as probe


def raw(data):
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "public_fixture_bytes_base64": base64.b64encode(data).decode(),
        "cr_bytes": data.count(b"\r"),
        "lf_bytes": data.count(b"\n"),
        "crlf_pairs": data.count(b"\r\n"),
        "exact_lf_header": data.startswith(b"-----BEGIN SSH SIGNATURE-----\n"),
        "exact_lf_footer": data.endswith(b"-----END SSH SIGNATURE-----\n"),
    }


def native():
    identity = {
        "ok": True,
        "volume_serial_hex": "0000000000000001",
        "file_id_16_bytes": list(range(16)),
    }
    row = {
        "open": {"ok": True},
        "id_before": identity,
        "id_after": identity,
        "current_path_id": identity,
        "retained_full_id_unchanged": True,
        "current_path_matches_retained_full_id": True,
        "owner_dacl": {
            "ok": True,
            "descriptor_valid": True,
            "descriptor_bytes": [1, 2, 3],
        },
    }
    for name in (
        "canonical_held_id",
        "canonical_private_security",
        "canonical_full_snapshot",
        "canonical_current_path",
    ):
        row[name] = {"ok": True, "facts": "shape fixture only"}
    return row


def trace():
    modes = []
    for mode in probe.MODES:
        modes.append(
            {
                "mode": mode,
                "statement_after": raw(probe.STATEMENT),
                "signature_before_sign": native()
                if mode == "filename_precreated_private"
                else {"absent": True},
                "original_process": {
                    "success": True,
                    "exit_code": 0,
                    "stdout": raw(b"public fixture"),
                    "stderr": raw(b""),
                },
                "signature_after_sign": {
                    "before_read": native(),
                    "after_read": native(),
                    "observations": {
                        "read_ok": True,
                        "raw": raw(b"public fixture"),
                        "strict_rust": {"ok": False, "result": "shape fixture only"},
                        "original_production_verify": {
                            "ok": False,
                            "result": "shape fixture only",
                        },
                    },
                },
            }
        )
    return {
        "schema": "hepta.windows-openssh-native-contract-probe.v1",
        "diagnostic_only": True,
        "functional_qualification": False,
        "production_authority_granted": False,
        "namespace": "hepta-vnext-operator-acceptance-v1",
        "public_fixture_statement": raw(probe.STATEMENT),
        "effective_token": {
            "ok": True,
            "user_sid": {"ok": True, "facts": '"S-1-5-21-1"'},
            "owner_sid": {"ok": True, "facts": '"S-1-5-21-1"'},
        },
        "fixture_signer_before": native(),
        "fixture_signer_after": native(),
        "modes": modes,
    }


class StrictDiagnosticControls(unittest.TestCase):
    def test_failures_are_observations_and_never_functional_pass(self):
        actual = probe.validate_trace(trace())
        self.assertEqual(len(actual), 3)
        self.assertTrue(
            all(
                not row["originalReadObservations"]["strict_rust"]["ok"]
                for row in actual
            )
        )

    def test_newlines_and_digests_bind_unmodified_bytes(self):
        data = b"-----BEGIN SSH SIGNATURE-----\r\nPUBLIC\r\n-----END SSH SIGNATURE-----\r\n"
        self.assertEqual(probe.raw_bytes(raw(data)), data)
        for key, value in (
            ("cr_bytes", 0),
            ("sha256", "0" * 64),
            ("exact_lf_header", True),
            ("bytes", True),
        ):
            row = raw(data)
            row[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                probe.raw_bytes(row)

    def test_mode_set_owner_full_id_and_original_body_reject_mutations(self):
        mutations = []
        row = trace()
        row["modes"].pop()
        mutations.append(row)
        row = trace()
        row["modes"][1]["mode"] = "stdin_stdout"
        mutations.append(row)
        row = trace()
        row["functional_qualification"] = True
        mutations.append(row)
        row = trace()
        row["modes"][0]["statement_after"] = raw(b"changed")
        mutations.append(row)
        row = trace()
        row["modes"][0]["signature_after_sign"]["observations"]["raw"] = raw(
            b"normalized"
        )
        mutations.append(row)
        row = trace()
        row["fixture_signer_after"]["owner_dacl"]["descriptor_bytes"] = [4]
        mutations.append(row)
        row = trace()
        row["modes"][2]["signature_before_sign"]["canonical_private_security"]["ok"] = (
            False
        )
        mutations.append(row)
        row = trace()
        row["fixture_signer_before"]["id_before"]["file_id_16_bytes"] = list(range(8))
        mutations.append(row)
        row = trace()
        del row["effective_token"]["user_sid"]
        mutations.append(row)
        for index, row in enumerate(mutations):
            with self.subTest(index=index), self.assertRaises((ValueError, KeyError)):
                probe.validate_trace(row)

    def test_native_single_case_scope_rejects_missing_duplicate_leak_unknown_recap(
        self,
    ):
        package, case = "codex-utils-path", probe.JUNCTION
        log = f"Starting 1 test across 1 binary (25 tests skipped)\n PASS [0.1s] {package} {case}\n Summary [0.1s] 1 test run: 1 passed, 25 skipped\n"
        self.assertTrue(probe.assess_exact(0, log, package, case)["passed"])
        for changed in (
            log.replace(case, "unknown"),
            log.replace("PASS", "LEAK"),
            log + log,
            log.replace("25 skipped", "24 skipped"),
            log + " Summary [0s] invalid\n",
            log.replace("1 passed,", "1 passed, 2 passed,"),
            log + f" FAIL [0s] {package} {case}\n",
        ):
            with self.subTest(changed=changed):
                self.assertFalse(
                    probe.assess_exact(0, changed, package, case)["passed"]
                )


if __name__ == "__main__":
    unittest.main()
