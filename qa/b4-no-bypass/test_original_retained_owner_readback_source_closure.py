"""Keep split Selection/C receipt readback on the same original owners.

These mutations protect the private dispatch, actual before/after reads,
physical journal check, original signature authentication and failure fence.
They add no deployment, caller authority or independent qualification evidence.
"""

import importlib.util
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "retained_owner_readback_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
OWNERS = (
    (AGENT + "circuit_selection_receipt_owner.rs", "Selection", "training_evidence", "authenticate_training", "decision"),
    (AGENT + "circuit_next_use_receipt_owner.rs", "NextUse", "predecessors", "authenticate_predecessors", "selection"),
)


class OriginalRetainedOwnerReadbackClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    def verifies(self, path, source):
        rows = [r for r in self.manifest["protected_file"] if r["path"] == path]
        self.assertEqual(len(rows), 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})

    def rejects(self, path, function, marker, replacement="", occurrence=0):
        if path == AGENT + "circuit_selection_receipt_owner.rs":
            # The same checks now receive the private evaluated/TNU profile.
            # C uses a separate explicit evaluated profile and keeps legacy Remote ordering.
            changes = (
                ("authenticate_training(&self.config,", "authenticate_training(&self.config, &self.profile,"),
                ("require_new_attestation(&self.config,", "require_new_attestation(&self.config, &self.profile,"),
                ("receipt(&self.config,", "receipt(&self.config, &self.profile,"),
                ("if matches!(source.location(), ObservationLocation::RemoteOwner) {",
                 "if matches!(\n            source.location(),\n            ObservationLocation::RemoteOwner | ObservationLocation::EvaluatedOwner\n        ) {"),
                ("ObservationLocation::LocalOwner => {",
                 "ObservationLocation::LocalOwner | ObservationLocation::EvaluatedOwner => {"),
            )
            for before, after in changes:
                marker = marker.replace(before, after)
                replacement = replacement.replace(before, after)
        if path == AGENT + "circuit_next_use_receipt_owner.rs":
            changes = (
                ("authenticate_predecessors(&self.config,", "evaluated::authenticate_predecessors(&self.config, &self.profile,"),
                ("receipt(&self.config,", "evaluated::receipt(&self.config, &self.profile,"),
                ("if matches!(source.location(), ObservationLocation::RemoteOwner) {",
                 "if matches!(source.location(), ObservationLocation::RemoteOwner | ObservationLocation::EvaluatedOwner) {"),
                ("ObservationLocation::LocalOwner => {",
                 "ObservationLocation::LocalOwner | ObservationLocation::EvaluatedOwner => {"),
            )
            for before, after in changes:
                marker = marker.replace(before, after)
                replacement = replacement.replace(before, after)
        source = (ROOT / path).read_text()
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        if path == AGENT + "circuit_next_use_receipt_owner.rs":
            # The mechanical private dispatch has rustfmt-wrapped calls. Match
            # the same complete tokens and mutate the actual original span.
            positions = [i for i in range(start, end + 1) if not source[i].isspace()]
            compact = "".join(source[i] for i in positions)
            wanted = re.sub(r"\s+", "", marker)
            matches = list(re.finditer(re.escape(wanted), compact))
            self.assertGreater(len(matches), occurrence, marker)
            offset = matches[occurrence].start()
            chosen = positions[offset]
            stopped = positions[offset + len(wanted) - 1] + 1
        else:
            offset = start
            for _ in range(occurrence + 1):
                chosen = source.index(marker, offset, end + 1)
                offset = chosen + len(marker)
            stopped = chosen + len(marker)
        self.verifies(path, source)
        with self.assertRaises(PROOF.VerificationFailure, msg=(path, function, marker, occurrence)):
            self.verifies(path, source[:chosen] + replacement + source[stopped:])

    def test_private_source_kind_cannot_promote_remote_reads_to_local_protocol(self):
        for path, name, _, _, _ in OWNERS:
            source = (ROOT / path).read_text()
            self.verifies(path, source)
            for kind, other in (("LocalOwner", "RemoteOwner"), ("RemoteOwner", "LocalOwner")):
                marker = "ObservationLocation::" + kind
                # The first occurrence is the concrete source's private location method.
                changed = source.replace(marker, "ObservationLocation::" + other, 1)
                with self.assertRaises(PROOF.VerificationFailure):
                    self.verifies(path, changed)
            for marker in ("pub enum ObservationLocation", "pub completion_fenced:", "self.completion_fenced = false"):
                with self.assertRaises(PROOF.VerificationFailure):
                    self.verifies(path, source + "\n" + marker + "\n")

    def test_new_and_recovered_requests_preserve_failure_fence_and_attestation_mode(self):
        for path, _, _, _, _ in OWNERS:
            for function, fresh, other in (("fn attest_source(", "true", "false"),
                                           ("fn readback_source(", "false", "true")):
                for marker in ("if self.completion_fenced {", "let result = self",
                               ".finish_original_readback(", "if result.is_err() {",
                               "self.completion_fenced = true;"):
                    self.rejects(path, function, marker)
                self.rejects(path, function, "if self.completion_fenced {", "if !self.completion_fenced {")
                self.rejects(path, function, "if result.is_err() {", "if result.is_ok() {")
                self.rejects(path, function, "self.completion_fenced = true;", "self.completion_fenced = false;")
                marker = "&source, &observed, &bytes, started_at, /*new_attestation*/ " + fresh + ","
                self.rejects(path, function, marker, marker.replace(fresh + ",", other + ","))

    def test_remote_predecessors_are_live_and_authenticated_before_first_journal_read(self):
        for path, _, predecessor, authenticate, _ in OWNERS:
            for marker in (
                "let observed = self.prepare(&source).await?;",
                "if matches!(source.location(), ObservationLocation::RemoteOwner) {",
                "let before = self." + predecessor + "(&source).await?;",
                authenticate + "(&self.config, &before, now()?)?;",
                "let bytes = self.journal.read(&self.saved)?;",
            ):
                self.rejects(path, "fn readback_source(", marker)
            self.rejects(path, "fn readback_source(", "ObservationLocation::RemoteOwner", "ObservationLocation::LocalOwner")

    def test_both_post_observation_paths_and_final_physical_journal_check_are_required(self):
        for path, _, predecessor, _, _ in OWNERS:
            function = "fn finish_original_readback("
            for marker in (
                "let completed = self.decode_completed(source, observed, bytes)?;",
                "let evidence = match source.location() {",
                "ObservationLocation::LocalOwner => {", "ObservationLocation::RemoteOwner => {",
                "if self.journal.read(&self.saved)? != bytes", "let current = now()?;",
                "self.authenticate_completed(completed, &evidence, started_at, current, new_attestation)",
            ):
                self.rejects(path, function, marker)
            for occurrence in (0, 1):
                marker = "if self.prepare(source).await? != *observed"
                self.rejects(path, function, marker, occurrence=occurrence)
                self.rejects(path, function, marker, marker.replace("!=", "=="), occurrence)
                self.rejects(path, function, "self." + predecessor + "(source).await?", occurrence=occurrence)
            marker = "if self.journal.read(&self.saved)? != bytes"
            self.rejects(path, function, marker, marker.replace("!=", "=="))

    def test_decode_preserves_original_payload_receipt_cut_and_signed_issue_time(self):
        for path, _, _, _, cut in OWNERS:
            for marker in (
                "learning_owner_evidence::decode(bytes)?",
                "receipt(&self.config, observed, signed.issued_at)?",
                "payload != learning_iteration_receipt_signing_bytes_v1(&receipt)?",
                ".get(self.config." + cut + ".receipts.len())",
                "Ok((receipt, payload, signed))",
            ):
                self.rejects(path, "fn decode_completed(", marker)
            marker = "payload != learning_iteration_receipt_signing_bytes_v1(&receipt)?"
            self.rejects(path, "fn decode_completed(", marker, marker.replace("!=", "=="))

    def test_final_authentication_cannot_skip_current_roles_identity_or_deadline(self):
        for path, _, _, authenticate, _ in OWNERS:
            for marker in (
                "if current < started_at", "if new_attestation",
                "require_new_attestation(&self.config, started_at, current)?",
                authenticate + "(&self.config, evidence, current)?",
                "let verified = self.config.verifier.verify(",
                "verified.principal() != &self.config.signer.principal",
                "verified.controller_id() != &self.config.signer.controller_id",
                "signed.evidence_id != evidence_id(self.saved.binding_digest)?",
                "verify_signed_actor_separation(", "Ok((receipt, signed))",
            ):
                self.rejects(path, "fn authenticate_completed(", marker)


if __name__ == "__main__":
    unittest.main()
