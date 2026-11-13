"""First-Publish source guards, not a native or whole-chain acceptance claim."""

from dataclasses import replace
from pathlib import Path
import re
import tempfile
import tomllib
import unittest

import test_publication_refusal_source_closure as original

ROOT, PROOF = original.ROOT, original.PROOF
A = original.A
ACCEPT = A + "authority_host_publication_acceptance.rs"
TRANSPORT, REFUSAL = original.TRANSPORT, original.REFUSAL
IDENTIFIER = "root_publication_first_accepted_transition"


def structure(path, source):
    original.require_structure(path, source)
    if path == ACCEPT:
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        start = code.index("struct PublicationAcceptance {")
        end = PROOF._rust_item_end(code, start)
        fields = code[code.index("{", start) + 1:end]
        if re.search(r"\bpub\b", fields):
            raise PROOF.VerificationFailure("first acceptance fields must remain private DATA")
    if path == TRANSPORT:
        body, _ = original.route.function(source, "fn serve_generation_publication_with_end(")
        replay = original.route.original.span(
            body, "if before.current == intent.target {\n"
            "                                    let accepted = retained_acceptance.ok_or_else("
        )
        if any(marker in body[replay[0]:replay[1]] for marker in (
            "original_broker_publish(", "observe_original_publish(",
            "fresh_publication =", "fresh_grant =", "refresh_projection(",
        )):
            raise PROOF.VerificationFailure("accepted replay cannot write or renew the first fact")
        effect = original.route.original.span(body, "if fresh_grant.is_some() {")
        for marker in (
            ".original_broker_publish(intent, signed, witness)",
            "fresh_publication = Some(before);",
        ):
            if not effect[0] < body.index(marker) < effect[1]:
                raise PROOF.VerificationFailure("first fact requires the original successful CAS")


class FirstPublicationAcceptanceSourceClosure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}
        cls.sources = {path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(
            (ROOT / path).read_text())) for path in (ACCEPT, TRANSPORT)}

    def reject(self, path, marker, replacement="", function=None, after=None):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows)
        source = (ROOT / path).read_text()
        if after is not None:
            self.assertEqual(source.count(after), 1)
            start = source.index(after) + len(after)
            self.assertIn(marker, source[start:])
            changed = source[:start] + source[start:].replace(marker, replacement, 1)
        elif function is None:
            self.assertIn(marker, source)
            changed = source.replace(marker, replacement, 1)
        else:
            code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
            start = code.index("fn " + function + "(")
            end = PROOF._rust_item_end(code, start) + 1
            self.assertIn(marker, source[start:end])
            changed = source[:start] + source[start:end].replace(marker, replacement, 1) + source[end:]
        self.assertNotEqual(source, changed)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / path
            target.parent.mkdir(parents=True)
            for value, reject in ((source, False), (changed, True)):
                target.write_text(value)
                def check():
                    PROOF._verify_protected_files(root, {"protected_file": rows})
                    structure(path, value)
                if reject:
                    with self.assertRaises(PROOF.VerificationFailure):
                        check()
                else:
                    check()

    def test_only_actual_publish_transport_can_produce_first_acceptance(self):
        boundary = self.boundaries[IDENTIFIER]
        self.assertEqual(boundary.product_callers, (TRANSPORT,))
        self.assertIn(IDENTIFIER, self.manifest["privileged_inventory"]["required_boundary_ids"])
        ignored = tuple(self.manifest["ignored_path_fragments"])
        PROOF._verify_boundary(ROOT, boundary, self.sources, ignored)
        with self.assertRaises(PROOF.VerificationFailure):
            PROOF._verify_boundary(ROOT, replace(boundary, product_callers=()), self.sources, ignored)
        sources = dict(self.sources)
        sources[A + "unregistered_first_publish.rs"] = (
            "fn bypass() { PublicationAcceptance::observe_original_publish(); }"
        )
        with self.assertRaises(PROOF.VerificationFailure):
            PROOF._verify_boundary(ROOT, boundary, sources, ignored)

    def test_first_transition_cannot_be_inferred_from_published(self):
        for marker in (
            "prepared.current != intent.previous",
            "prepared.prepared.as_ref() != Some(intent)",
            "prepared.current == expected.current",
        ):
            with self.subTest(marker=marker):
                self.reject(ACCEPT, marker, "false", "require_first_transition")

    def test_old_missing_fact_and_replayed_current_are_not_fresh(self):
        for marker in (
            "let accepted = retained_acceptance.ok_or_else(",
            "accepted.original_current() != &before", "published.intent != *intent",
            "published.signed != *signed", "published.witness != *witness",
            "before.current != intent.previous", "before.prepared.as_ref() != Some(intent)",
            "retained_acceptance.is_some()", "if fresh_grant.is_some() {",
        ):
            with self.subTest(marker=marker):
                after = "accepted.original_current() != &before" if marker.startswith("before.") else None
                self.reject(TRANSPORT, marker, after=after)

    def test_actual_cas_precedes_first_fact_after_whole_root_context(self):
        self.reject(TRANSPORT, ".original_broker_publish(intent, signed, witness)")
        self.reject(TRANSPORT, "fresh_publication = Some(before);")
        self.reject(TRANSPORT, "let accepted = match fresh_publication {")
        self.reject(TRANSPORT, "PublicationAcceptance::observe_original_publish(")
        self.reject(TRANSPORT, "// This branch only observes the original fact.",
                    "slot.current.original_broker_publish(intent, signed, witness)?;\n"
                    "// This branch only observes the original fact.")

    def test_physical_owner_cuts_original_window_and_current_issuer_are_required(self):
        for marker in (
            "Self::require_first_transition(&original.intent, prepared, expected)?;",
            "expected.prepared.is_some()", "expected.initial.is_some()",
            "!previous.is_drained()", "!target.is_genesis()",
            "previous.owner_binding() != &original.intent.previous",
            "target.owner_binding() != &original.intent.target",
            "slot.previous.observe().map_err(io::Error::other)? != previous",
            "slot.target.observe().map_err(io::Error::other)? != target",
            "slot.require_selection(verified_at_unix_ms)?;", "transport::require_fresh_window(",
            "slot.verify_retained(&published.signed, &published.witness)? != accepted_revocations",
        ):
            with self.subTest(marker=marker):
                self.reject(ACCEPT, marker, function="observe_original_publish")

    def test_first_fact_is_immutable_in_same_exact_ready_cas(self):
        for marker in (
            "let mut ready = armed.clone();", "publication.require_original(&original)?;",
            ".is_some_and(|old| old != &publication)", "ready.publication = Some(publication);",
            "ready.phase = Phase::Ready;", ".compare_and_set(&self.owner, armed, &ready)",
        ):
            with self.subTest(marker=marker):
                self.reject(REFUSAL, marker, function="complete_armed<T>")

    def test_raw_fact_cannot_change_original_identity_time_or_revocations(self):
        for marker in (
            "self.original_profile != original.binding", "self.verified_at_unix_ms == 0",
            "self.current.current != original.intent.target", "published.intent != original.intent",
            "!= published.signed_grant_digest",
            "self.accepted_revocations.authority_epoch != published.signed.grant.authority_epoch",
            ".contains(&published.signed.grant.grant_id)",
        ):
            with self.subTest(marker=marker):
                self.reject(ACCEPT, marker, function="require_original")
        self.reject(ACCEPT, "current: CurrentHead,", "pub(crate) current: CurrentHead,")


if __name__ == "__main__":
    unittest.main()
