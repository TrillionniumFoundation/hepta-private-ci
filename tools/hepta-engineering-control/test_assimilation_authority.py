"""Adversarial consent and dormant-proposal authority boundary coverage."""

from dataclasses import asdict, replace
from pathlib import Path
import os
import tempfile
import unittest
from unittest import mock

from control_engineering_v2 import (
    DebianSandboxAdapter,
    EngineeringError,
    OwnerConsentReceipt,
    SandboxParityReceipt,
    build_manifest_candidate,
    propose_dormant_assimilation,
    semantic_digest,
    synthesize_read_only_contracts,
    validate_consent,
)


class BoundedSentinel:
    def __init__(self, value, maximum_reads):
        self.value = value
        self.maximum_reads = maximum_reads
        self.reads = 0

    def __iter__(self):
        while True:
            self.reads += 1
            if self.reads > self.maximum_reads:
                raise AssertionError("unbounded consent collection consumed")
            yield self.value


class AssimilationAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.consent = OwnerConsentReceipt(
            "owner", "1" * 64, ("query_version",), ("fixture",), 0, 200, "2" * 64
        )
        self.manifest = build_manifest_candidate(
            self.consent,
            {
                "os_id": "debian",
                "os_version": "13",
                "package_inventory_digest": "3" * 64,
                "service_graph_digest": "4" * 64,
                "mutable_state_digest": "5" * 64,
                "provenance_digest": "6" * 64,
            },
            ("runtime_processes_not_observed",),
            now_ns=self.now,
        )
        self.operations = synthesize_read_only_contracts(
            self.consent, self.manifest, now_ns=self.now
        )

    def sandbox(self, manifest=None, operations=None, **changes):
        manifest = self.manifest if manifest is None else manifest
        operations = self.operations if operations is None else operations
        receipt = SandboxParityReceipt(
            self.consent.target_identity_digest,
            semantic_digest(asdict(manifest)),
            semantic_digest([asdict(operation) for operation in operations]),
            "7" * 64,
            "8" * 64,
            "9" * 64,
            "evaluator",
            "generator",
            True,
        )
        return replace(receipt, **changes)

    def propose(self, manifest=None, operations=None, sandbox=None):
        manifest = self.manifest if manifest is None else manifest
        operations = self.operations if operations is None else operations
        sandbox = self.sandbox(manifest, operations) if sandbox is None else sandbox
        return propose_dormant_assimilation(
            self.consent, manifest, operations, sandbox, now_ns=self.now
        )

    def test_legitimate_candidate_is_deterministic_and_dormant(self):
        proposal = self.propose()
        self.assertEqual(proposal, self.propose())
        self.assertEqual(
            (proposal.state, proposal.activation, proposal.federation,
             proposal.propagation, proposal.authority_granted),
            ("dormant_candidate", False, False, False, False),
        )

    def test_scope_is_checked_even_when_parity_digests_match(self):
        operations = (replace(self.operations[0], operation_class="read_status"),)
        with self.assertRaisesRegex(EngineeringError, "operation_not_consented"):
            self.propose(operations=operations)

    def test_manifest_authority_and_secret_flags_are_strict_at_both_boundaries(self):
        for field in ("raw_secrets_copied", "authority_granted"):
            for flag in (True, None, 0, "", []):
                manifest = replace(self.manifest, **{field: flag})
                with self.subTest(field=field, flag=flag):
                    with self.assertRaisesRegex(EngineeringError, "manifest_boundary_violation"):
                        synthesize_read_only_contracts(
                            self.consent, manifest, now_ns=self.now
                        )
                    with self.assertRaisesRegex(EngineeringError, "manifest_boundary_violation"):
                        self.propose(manifest=manifest)

    def test_sandbox_and_operation_falseish_flags_do_not_assert_safety(self):
        for field in ("network_unrestricted", "production_credentials_exposed", "authority_delta"):
            for flag in (None, 0, "", []):
                with self.subTest(field=field, flag=flag):
                    with self.assertRaisesRegex(EngineeringError, "sandbox_boundary_violation"):
                        self.propose(sandbox=self.sandbox(**{field: flag}))
        for flag in (None, 0, "", []):
            with self.subTest(external_effect=flag):
                with self.assertRaisesRegex(EngineeringError, "operation_widens_authority"):
                    self.propose(operations=(replace(self.operations[0], external_effect=flag),))

    def test_consent_iterables_stop_at_hard_limits_before_deduplication(self):
        for field, value, maximum_reads, code in (
            ("allowed_operations", "query_version", 17, "consent_operation_limit"),
            ("allowed_roots", "fixture", 65, "consent_root_limit"),
        ):
            values = BoundedSentinel(value, maximum_reads)
            with self.subTest(field=field):
                with self.assertRaisesRegex(EngineeringError, code):
                    validate_consent(replace(self.consent, **{field: values}), now_ns=self.now)
                self.assertEqual(values.reads, maximum_reads)

    def test_consent_time_requires_nonnegative_bounded_integer(self):
        for now in (True, 100.0, "100", -1, 2**63):
            with self.subTest(now=now):
                with self.assertRaisesRegex(EngineeringError, "invalid_time"):
                    validate_consent(self.consent, now_ns=now)
        for field, timestamp in (
            ("observed_unix_ns", -1),
            ("observed_unix_ns", False),
            ("expires_unix_ns", 2**63),
        ):
            with self.subTest(field=field, timestamp=timestamp):
                with self.assertRaisesRegex(EngineeringError, "consent_expired"):
                    validate_consent(replace(self.consent, **{field: timestamp}), now_ns=self.now)

    def test_operation_shape_and_limits_cannot_be_attested_away(self):
        for field, value in (
            ("deadline_millis", 0), ("deadline_millis", 5_001),
            ("deadline_millis", True), ("maximum_output_bytes", -1),
            ("maximum_output_bytes", 65_537), ("input_schema_digest", ""),
            ("output_schema_digest", ""), ("operation_id", ""),
            ("terminal_observer", ""), ("idempotency", "write_once"),
        ):
            with self.subTest(field=field, value=value):
                with self.assertRaises(EngineeringError):
                    self.propose(operations=(replace(self.operations[0], **{field: value}),))
        with self.assertRaisesRegex(EngineeringError, "duplicate_operation"):
            self.propose(operations=self.operations * 2)

    def test_blank_evaluator_identity_does_not_establish_independence(self):
        for field in ("evaluator_principal", "generator_principal"):
            with self.subTest(field=field):
                with self.assertRaises(EngineeringError):
                    self.propose(sandbox=self.sandbox(**{field: ""}))

    def test_expiry_during_filesystem_read_discards_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "etc").mkdir()
            (root / "etc/os-release").write_text("ID=debian\nVERSION_ID=13\n")
            clock = [self.now]
            adapter = DebianSandboxAdapter(
                root, self.consent, root_label="fixture", clock=lambda: clock[0]
            )
            original_read = os.read

            def read_past_expiry(fd, limit):
                value = original_read(fd, limit)
                clock[0] = self.consent.expires_unix_ns
                return value

            with mock.patch(
                "control_engineering_v2.assimilation.os.read", side_effect=read_past_expiry
            ):
                with self.assertRaisesRegex(EngineeringError, "consent_expired"):
                    adapter.query_version()

    def test_low_level_reads_preserve_the_enrolled_operation_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "var/lib/dpkg").mkdir(parents=True)
            (root / "var/lib/dpkg/status").write_bytes(b"unconsented-status")
            adapter = DebianSandboxAdapter(
                root, self.consent, root_label="fixture", clock=lambda: self.now
            )
            with self.assertRaisesRegex(EngineeringError, "operation_not_consented"):
                adapter._read("var/lib/dpkg/status", limit=128)


if __name__ == "__main__":
    unittest.main()
