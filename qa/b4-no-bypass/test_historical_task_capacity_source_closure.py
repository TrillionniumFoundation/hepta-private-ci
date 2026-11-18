"""Protect the paired Task response capacity without granting native use.

All mutations target the actual retained source. Default CURRENT/request/other-op
limits, global framing, original deadlines and pidfd checks remain independent.
"""
from dataclasses import replace
from pathlib import Path
import tempfile
import tomllib
import unittest

import test_initial_absolute_deadline_source_closure as original

ROOT = original.ROOT
PROOF = original.PROOF
A = original.AGENT
PROTOCOL = A + "root_historical_task_read_protocol.rs"
CLIENT = A + "root_historical_task_read_client.rs"
PROVIDER = A + "authority_host_historical_read.rs"
RUNTIME = A + "authority_host_historical_read_runtime.rs"
STREAM = A + "root_generation_publication_stream.rs"
LEDGER = A + "root_historical_ledger_data.rs"
PUBLICATION = A + "circuit_task_source_data.rs"
BOUNDARY = "root_historical_task_response_frame_capacity"


class HistoricalTaskCapacitySourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    reject_removal = original.InitialAbsoluteDeadlineTests.reject

    def mutate(self, path, transform):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows)
        source = (ROOT / path).read_text()
        changed = transform(source)
        self.assertNotEqual(changed, source)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(changed)
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def remove_exact(self, path, marker):
        def transform(source):
            self.assertEqual(source.count(marker), 1, marker)
            return source.replace(marker, "/* removed actual capacity predicate */", 1)
        self.mutate(path, transform)

    def test_explicit_capacity_api_has_exact_typed_caller_and_inventory(self):
        boundaries = PROOF._boundary_rows(self.manifest)
        row = next(row for row in boundaries if row.identifier == BOUNDARY)
        self.assertEqual(row.product_callers, (CLIENT,))
        self.assertEqual(row.receiver_type, "OriginalPublicationStream")
        self.assertEqual(row.symbol, "OriginalPublicationStream::exchange_with_response_bound")
        self.assertIn(BOUNDARY, self.manifest["privileged_inventory"]["required_boundary_ids"])
        sources = {
            path: PROOF._strip_cfg_test_items(
                PROOF._strip_rust_non_code((ROOT / path).read_text())
            )
            for path in (STREAM, CLIENT)
        }
        PROOF._verify_boundary(ROOT, row, sources, ())
        bypass = dict(sources)
        bypass[A + "unregistered_response_capacity.rs"] = (
            "fn bypass(owner: &OriginalPublicationStream) { "
            "owner.exchange_with_response_bound(&[], 1); }"
        )
        with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
            PROOF._verify_boundary(ROOT, row, bypass, ())
        with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
            PROOF._verify_boundary(ROOT, replace(row, product_callers=()), sources, ())
        missing = dict(self.manifest)
        missing["privileged_inventory"] = dict(self.manifest["privileged_inventory"])
        missing["privileged_inventory"]["required_boundary_ids"] = [
            value for value in self.manifest["privileged_inventory"]["required_boundary_ids"]
            if value != BOUNDARY
        ]
        with self.assertRaisesRegex(PROOF.VerificationFailure, "inventory mismatch"):
            PROOF._verify_privileged_inventory(missing, boundaries)

    def test_task_capacity_depends_on_both_original_dto_caps_and_finite_envelope(self):
        for marker in (
            "RootHistoricalLedgerReadDataV1::JSON_BOUND\n    + RootHistoricalTaskPublicationDataV1::JSON_BOUND",
            "+ TASK_RESPONSE_ENVELOPE_BOUND",
            "+ PURPOSE.len()",
            "+ (MAX_READS.ilog10() as usize + 1)",
            "+ 2 * 64",
        ):
            with self.subTest(marker=marker):
                self.remove_exact(PROTOCOL, marker)
        self.remove_exact(LEDGER, "pub(crate) const JSON_BOUND: usize = 12 * 1024;")
        self.remove_exact(PUBLICATION, "pub(crate) const JSON_BOUND: usize = 16_384;")
        self.reject_removal("root_historical_ledger_data.rs", "fn validate_data(",
                            "serde_json::to_vec(self).map_err(io::Error::other)?.len() > Self::JSON_BOUND")
        self.reject_removal("circuit_task_source_data.rs", "fn decode_data(",
                            "json(self)?.len() > Self::JSON_BOUND")

    def test_only_task_uses_the_derived_reply_capacity(self):
        self.reject_removal("root_historical_task_read_protocol.rs", "fn response_bound(",
                            "Self::Task => TASK_RESPONSE_BOUND")
        for marker in (
            "Self::LearningTrust", "Self::PostAFrozenLearning",
            "Self::AcceptCompletedLearning", "Self::CaptureCompletedHistory",
            "Self::ReadCompletedHistory => WIRE_BOUND",
        ):
            with self.subTest(marker=marker):
                self.reject_removal("root_historical_task_read_protocol.rs",
                                    "fn response_bound(", marker)
        self.remove_exact(PROTOCOL, "pub(crate) const WIRE_BOUND: usize = 16_384;")
        self.remove_exact(PROTOCOL, "pub(crate) const MAX_READS: u64 = 64;")

    def test_task_semantic_and_transport_bindings_remain_in_all_four_layers(self):
        for filename, function, marker in (
            ("root_historical_task_read_protocol.rs", "fn require_complete_reply(",
             "bytes.len() > TASK_RESPONSE_BOUND"),
            ("authority_host_historical_read.rs", "fn observe_complete_task(",
             "reply.is_empty() || reply.len() > operation.response_bound()"),
            ("authority_host_historical_read_runtime.rs", "fn serve_optional(",
             "request_bound: WIRE_BOUND"),
            ("authority_host_historical_read_runtime.rs", "fn serve_optional(",
             "response_bound: TASK_RESPONSE_BOUND"),
            ("root_historical_task_read_client.rs", "fn exchange(",
             ".exchange_with_response_bound(&request, operation.response_bound())"),
        ):
            with self.subTest(path=filename, marker=marker):
                self.reject_removal(filename, function, marker)

    def test_original_default_wrapper_and_explicit_wrapper_keep_the_same_end(self):
        self.reject_removal("root_generation_publication_stream.rs", "fn exchange_until(",
                            "self.exchange_until_with_response_bound(request, requested_end, 16_384)")
        for marker in (
            "self.exchange_until_with_response_bound(",
            "(Instant::now() + self.timeout).min(self.end)",
            "response_bound,",
        ):
            with self.subTest(marker=marker):
                self.reject_removal("root_generation_publication_stream.rs",
                                    "fn exchange_with_response_bound(", marker)

    def test_bounded_helper_keeps_original_request_global_reply_and_pidfd_checks(self):
        filename = "root_generation_publication_stream.rs"
        function = "fn exchange_until_with_response_bound("
        for marker in (
            "request.is_empty() || request.len() > 16_384",
            "!(1..=65_536).contains(&response_bound)",
            "requested_end.min(now + self.timeout).min(self.end)",
            "now >= end", "size == 0 || size > response_bound",
            "Instant::now() >= end",
        ):
            with self.subTest(marker=marker):
                self.reject_removal(filename, function, marker)
        for occurrence in (0, 1):
            self.reject_removal(filename, function, "check_lifetime(&self.root)", occurrence)

    def test_peer_length_rejection_precedes_allocation(self):
        def allocate_first(source):
            allocation = "        let mut response = vec![0; size];\n"
            before = "        if size == 0 || size > response_bound {\n"
            self.assertEqual(source.count(allocation), 1)
            self.assertEqual(source.count(before), 1)
            source = source.replace(allocation, "", 1)
            return source.replace(before, allocation + before, 1)
        self.mutate(STREAM, allocate_first)


if __name__ == "__main__":
    unittest.main()
