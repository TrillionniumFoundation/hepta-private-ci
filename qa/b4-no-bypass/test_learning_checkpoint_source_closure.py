"""Keep learning transport on the original registered Root checkpoint owner."""

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "learning_checkpoint_caller_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
SERVICE = AGENT + "authority_host_learning_checkpoint.rs"
WRITER = AGENT + "authority_host_writer.rs"
TRANSPORT = AGENT + "learning_iteration_checkpoint_transport.rs"
BOUNDARIES = (
    "root_registered_learning_checkpoint_writer",
    "root_original_learning_checkpoint_exchange",
)


class LearningCheckpointSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {
            row.identifier: row for row in PROOF._boundary_rows(cls.manifest)
        }
        cls.sources = {
            path: PROOF._strip_cfg_test_items(
                PROOF._strip_rust_non_code((ROOT / path).read_text())
            )
            for path in (SERVICE, WRITER, TRANSPORT)
        }

    def rejects(self, path, function, marker, replacement="", occurrence=0):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows)
        source = (ROOT / path).read_text()
        start = source.index(function)
        end = PROOF._rust_item_end(PROOF._strip_rust_non_code(source), start)
        self.assertIsNotNone(end)
        assert end is not None
        body = source[start : end + 1]
        offsets = []
        offset = body.find(marker)
        while offset >= 0:
            offsets.append(offset)
            offset = body.find(marker, offset + len(marker))
        self.assertGreater(len(offsets), occurrence, marker)
        offset = start + offsets[occurrence]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            manifest = {"protected_file": rows}
            PROOF._verify_protected_files(root, manifest)
            target.write_text(source[:offset] + replacement + source[offset + len(marker) :])
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, manifest)

    def test_original_typed_callers_cannot_be_omitted_or_extended(self):
        for identifier in BOUNDARIES:
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                PROOF._verify_boundary(ROOT, row, self.sources, ())
                with self.assertRaises(PROOF.VerificationFailure):
                    PROOF._verify_boundary(
                        ROOT, replace(row, product_callers=()), self.sources, ()
                    )
                sources = dict(self.sources)
                sources[AGENT + "unexpected_learning.rs"] = (
                    f"fn unexpected(original: &{row.receiver_type}) {{ "
                    "let renamed = original; renamed.exchange_learning_checkpoint(); }"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, sources, ())

    def test_original_writer_checks_cannot_be_borrowed_from_other_methods(self):
        for marker in (
            ".with_live(&self.leases, |_| {",
            "issuer.retained_writer_authorization(&self.registration)? != self.proof",
            "validate_observation_lease(&self.registration.authority_lease, &before, now)?;",
            ".exchange_learning_checkpoint(bytes, next_request_id)",
            "if before != after",
            "validate_observation_lease(&self.registration.authority_lease, &after, now)?;",
        ):
            with self.subTest(marker=marker):
                self.rejects(WRITER, "fn exchange_learning_checkpoint(", marker)

    def test_service_requires_same_agent_peer_and_both_lifetime_checks(self):
        for marker in (
            "backend.registered_agent_id() != self.identity.agent_id.to_string()",
            "HostAuthorityPeerChannel::from_stream(stream, policy, owner_pidfd)?",
        ):
            with self.subTest(marker=marker):
                self.rejects(SERVICE, "fn serve_learning_checkpoint(", marker)
        for occurrence in range(2):
            with self.subTest(lifetime_check=occurrence):
                self.rejects(
                    SERVICE, "fn serve_learning_checkpoint(",
                    "self.check_logind_lifetime().map_err(unavailable)?;",
                    occurrence=occurrence,
                )

    def test_request_binding_and_original_checkpoint_dispatch_are_required(self):
        function = "fn exchange_learning_checkpoint("
        for marker in (
            "let (schema, binding) = self.profile_identity();",
            "request.schema != schema",
            "request.operation != operation",
            "request.request_id != *next_request_id",
            "request.binding != binding",
            "*next_request_id = next_request_id",
            ".checked_add(1)",
            "self.restore(&self.initial.request)",
            "decode_snapshot(&snapshot)",
            "expected_head != expected.to_string()",
            "self.checkpoint(expected, &next)",
        ):
            with self.subTest(marker=marker):
                self.rejects(TRANSPORT, function, marker)

        # Keep every marker in the same method while moving profile validation
        # after request consumption and dispatch: presence alone is insufficient.
        source = (ROOT / TRANSPORT).read_text()
        start = source.index(function)
        profile = source.index("let (schema, binding) = self.profile_identity();", start)
        counter = source.index("*next_request_id = next_request_id", profile)
        dispatched = source.index("let result = match result {", counter)
        guard = source[profile:counter]
        dispatch = source[counter:dispatched]
        self.rejects(TRANSPORT, function, guard + dispatch, dispatch + guard)

    def test_scoped_profile_and_material_validation_cannot_be_omitted(self):
        cases = (
            ("fn from_root_stream_scoped_v2(", "scope.validate_snapshot(&initial)"),
            ("fn from_root_stream_scoped_v2(", "Some(scope)"),
            ("fn frozen_scope_binding(", "self.scope.as_ref().map(FrozenLearningScopeV2::binding)"),
            ("fn restore(", "scope\n                            .validate_snapshot(&snapshot)"),
            ("fn checkpoint(", "scope.validate_snapshot(snapshot)"),
            ("fn exchange<T>(", "Some(_) => SCOPED_OPERATION"),
            ("fn exchange_learning_checkpoint(", "Some(_) => SCOPED_OPERATION"),
        )
        for function, marker in cases:
            with self.subTest(function=function, marker=marker):
                self.rejects(TRANSPORT, function, marker)

    def test_unvalidated_reply_cannot_restore_the_consumed_connection(self):
        self.rejects(
            TRANSPORT, "fn exchange<T>(",
            "let result = validate(response.result);",
            "let result = Ok(());",
        )
        self.rejects(
            TRANSPORT, "fn exchange<T>(",
            "response.binding != request.binding", "false",
        )
