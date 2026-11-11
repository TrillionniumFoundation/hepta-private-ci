"""Keep remote material on the original completed files and frozen Q24 scope.

This checks exact production source edges and rejects guard removal. Native
fixtures exercise actual Material journals and peer framing separately; neither
is evidence that the external role hosts or ordinary Root assembly are deployed.
"""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_material_peer_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
DATASET = AGENT + "cell_q24_dataset.rs"
DECODE = AGENT + "cell_q24_dataset_remote.rs"
CLIENT = AGENT + "cell_q24_material_source.rs"
SERVE = AGENT + "cell_q24_material_source_service.rs"
WIRE = AGENT + "cell_q24_material_source_wire.rs"
HOST = AGENT + "cell_q24_material_evidence_service.rs"
PAIR = AGENT + "cell_q24_material_receipt_owner.rs"
PAIRED = AGENT + "cell_q24_material_pair_readback.rs"
CAPTURE = AGENT + "cell_q24_training_source.rs"
EXPECTED = {
    "learning_original_material_source_projection": (SERVE,),
    "learning_original_material_source_decode": (CLIENT,),
    "learning_original_material_completed_source_read": (),
    "learning_original_material_pair_readback": (SERVE,),
    "learning_original_material_source_serve": (AGENT + "cell_q24_material_command_service.rs",),
    "learning_original_material_source_client": (),
    "learning_original_material_source_current": (CAPTURE,),
    "learning_original_material_source_binding": (CAPTURE,),
    "learning_original_remote_training_source_capture": (AGENT + "cell_q24_training_bootstrap_build.rs",),
}


class OriginalMaterialSourcePeerClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

    def rejects(self, path, function, marker):
        source = (ROOT / path).read_text()
        code = PROOF._strip_rust_non_code(source)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        offset = source.index(marker, start, end + 1)
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(source[:offset] + source[offset + len(marker):])
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_only_actual_material_edges_open_and_host_handoff_remains_closed(self):
        paths = {path for identifier in EXPECTED for path in (
            self.boundaries[identifier].definition_path,
            *self.boundaries[identifier].product_callers,
        )}
        sources = {path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(
            (ROOT / path).read_text())) for path in paths}
        for identifier, expected in EXPECTED.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                self.assertEqual(row.product_callers, expected)
                PROOF._verify_boundary(ROOT, row, sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                if row.receiver_type:
                    call = f"{row.receiver_type}::{method}()"
                else:
                    call = f"{method}()"
                extra = dict(sources)
                extra[AGENT + "unregistered_remote_material.rs"] = f"fn unexpected() {{ {call}; }}"
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, extra, ())
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_explicit_uid_stream_has_only_the_actual_production_callers(self):
        row = self.boundaries["original_pinned_stream_explicit_uid"]
        expected = (AGENT + "learning_iteration_evidence_client.rs", CLIENT, AGENT + "cell_q24_material_source_connection.rs")
        self.assertEqual(row.product_callers, expected)
        self.assertIn(
            row.identifier,
            self.manifest["privileged_inventory"]["required_boundary_ids"],
        )
        paths = (row.definition_path, *expected)
        sources = {
            path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(
                (ROOT / path).read_text()
            ))
            for path in paths
        }
        PROOF._verify_boundary(ROOT, row, sources, ())
        missing = dict(sources)
        del missing[CLIENT]
        with self.assertRaisesRegex(PROOF.VerificationFailure, "missing"):
            PROOF._verify_boundary(ROOT, row, missing, ())
        unexpected = dict(sources)
        unexpected[AGENT + "unregistered_explicit_uid_peer.rs"] = (
            "fn unexpected() { RootObservationStream::from_stream_for_uid(); }"
        )
        with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
            PROOF._verify_boundary(ROOT, row, unexpected, ())

    def test_decoder_cannot_detach_signatures_provenance_batch_or_frozen_scope(self):
        checks = (
            ("fn from_original_material_peer(", "require_original_material_signatures(config, experience, dataset, started_at)?"),
            ("fn from_original_material_peer(", "config.freeze_plan.objective_digest\n                != config.dataset.request.envelope.objective_digest"),
            ("fn from_original_material_peer(", "let ledger_binding = digest(&wire.ledger_binding)?;"),
            ("fn from_original_material_peer(", "let trust_distribution = digest(&wire.trust_distribution)?;"),
            ("fn from_original_material_peer(", "let source_publication = digest(&wire.source_publication)?;"),
            ("fn from_original_material_peer(", "config.verifier.verify("),
            ("fn from_original_material_peer(", "verify_dataset_snapshot_receipt_v3(&receipt, started_at)?"),
            ("fn from_original_material_peer(", "signed_freeze.extend_from_slice(&config.freeze_evidence.signature)"),
            ("fn from_original_material_peer(", "config.dataset.receipts[0].evidence_digest != material.provenance_digest()"),
            ("fn from_original_material_peer(", "config.dataset.receipts[1].evidence_digest != material.provenance_digest()"),
            ("fn from_original_material_peer(", "material.training_plan("),
            ("fn from_original_material_peer(", "if fresh_now < started_at"),
            ("fn from_original_material_peer(", "require_original_material_signatures(config, experience, dataset, fresh_now)?"),
            ("fn decode_batch(", "text.len() > 1_024"),
            ("fn decode_batch(", "rows != 1"),
            ("fn decode_batch(", "width != expected_width"),
            ("fn decode_batch(", "batch.encoded() != bytes.as_slice()"),
        )
        for function, marker in checks:
            with self.subTest(function=function, marker=marker):
                self.rejects(DECODE, function, marker)
        self.rejects(DATASET, "fn read_current_at_clock(", "ledger_binding: self.ledger.binding_digest()")
        self.rejects(DATASET, "fn read_current_at_clock(", "source_publication: source.publication_digest()")

    def test_peer_is_original_finite_and_exhausted_on_uncertainty(self):
        checks = (
            ("fn from_original_stream(", "libc::getuid()"),
            ("fn from_original_stream(", "peer.pid == std::process::id()"),
            ("fn from_original_stream(", "RootObservationStream::from_stream_for_uid("),
            ("fn read_current(", ".take()"),
            ("fn read_current(", ".read(&request)"),
            ("fn read_current(", "experience != self.config.experience_evidence"),
            ("fn read_current(", "dataset != self.config.dataset_evidence"),
            ("fn read_current(", "OriginalCellQ24DatasetV1::from_original_material_peer("),
            ("fn read_current(", "if fresh_now < started_at"),
            ("fn read_current(", "verify_context(&self.config, fresh_now)?"),
            ("fn read_current(", "root_observation_stream::check_lifetime("),
            ("fn require_source_binding(", "!Arc::ptr_eq(&self.baseline, baseline)"),
            ("fn require_source_binding(", "self.config.freeze_evidence != config.freeze_evidence"),
        )
        for function, marker in checks:
            with self.subTest(function=function, marker=marker):
                self.rejects(CLIENT, function, marker)

    def test_final_material_authentication_follows_original_peer_io(self):
        source = (ROOT / CLIENT).read_text()
        code = PROOF._strip_rust_non_code(source)
        start = code.index("fn read_current(")
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        body = source[start:end + 1]
        peer = (
            "        crate::root_observation_stream::check_lifetime("
            "channel.transport.root_lifetime().get_ref())\n"
            "            .map_err(|_| Error::Unavailable)?;\n"
        )
        clock = "        let fresh_now = now()?;\n"
        authenticate = "        verify_context(&self.config, fresh_now)?;\n"
        self.assertEqual(body.count(peer), 1)
        self.assertEqual(body.count(clock), 1)
        self.assertEqual(body.count(authenticate), 1)
        without_peer = body.replace(peer, "", 1)
        mutations = (
            ("clock-before-peer", without_peer.replace(clock, clock + peer, 1)),
            ("authentication-before-peer", without_peer.replace(
                authenticate, authenticate + peer, 1
            )),
        )
        rows = [row for row in self.manifest["protected_file"] if row["path"] == CLIENT]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / CLIENT
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            for name, changed in mutations:
                with self.subTest(mutation=name):
                    target.write_text(source[:start] + changed + source[end + 1:])
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_source_purpose_only_reads_original_completed_pair(self):
        checks = (
            ("fn serve_material_source(", "policy.timeout > Duration::from_millis(500)"),
            ("fn serve_material_source(", "policy.lifetime > Duration::from_secs(300)"),
            ("fn serve_material_source(", "HostAuthorityPeerChannel::from_stream(stream, policy, original_consumer_pidfd)?"),
            ("fn respond_material(", "let mut owners ="),
            ("fn respond_material(", "let mut ledger ="),
            ("fn respond_material(", "OriginalCellQ24MaterialReceiptOwnersV1::readback_material_pair("),
            ("fn respond_material(", "snapshot: &self.config.initial"),
            ("fn respond_material(", "drop(ledger);"),
            ("fn respond_material(", "drop(owners);"),
            ("fn respond_material(", "experience.receipt.evidence_digest != dataset.material.provenance_digest()"),
            ("fn respond_material(", "dataset.receipt.evidence_digest != dataset.material.provenance_digest()"),
            ("fn respond_material(", "fresh_now < started_at"),
            ("fn respond_material(", "material.original_material_wire()"),
            ("fn respond_material(", "evidence_wire::Evidence::from_original(&experience.attestation)"),
            ("fn respond_material(", "evidence_wire::Evidence::from_original(&dataset.attestation)"),
        )
        for function, marker in checks:
            with self.subTest(function=function, marker=marker):
                self.rejects(SERVE, function, marker)
        for marker in (
            "binding::now()?",
            "self.read_experience(&mut sources, started_at)?",
            "binding::dataset_saved(&self.config, self.dataset_binding, &experience)?",
            "self.dataset.read(&saved)?",
            "self.authenticate_dataset(&mut sources, &experience, &saved, &bytes, started_at)?",
            "Ok((experience, dataset))",
        ):
            self.rejects(PAIRED, "fn readback_material_pair(", marker)
        # The paired view keeps both real material reads and original journal
        # comparisons in the existing authenticator; none becomes a cache.
        for function, marker in (
            ("fn authenticate_experience(", "binding::read_material(&self.config, sources, true)?"),
            ("fn authenticate_experience(", "self.experience.read(&self.experience_saved)? != bytes"),
            ("fn authenticate_dataset(", "self.read_experience(sources, started_at)?"),
            ("fn authenticate_dataset(", "experience.attestation != original_experience.attestation"),
            ("fn authenticate_dataset(", "self.dataset.read(saved)? != bytes"),
            ("fn authenticate_dataset(", "self.experience.read(&self.experience_saved)? != original_experience_bytes"),
            ("fn authenticate_dataset(", "binding::fresh_time(started_at)?"),
        ):
            self.rejects(PAIR, function, marker)
        source = (ROOT / WIRE).read_text()
        self.assertEqual(source.count("#[serde(deny_unknown_fields)]"), 2)
        request = source.split("struct Request {", 1)[1].split("}", 1)[0]
        for forbidden in ("batch", "target", "snapshot", "signature", "observed", "now"):
            self.assertNotIn(f"pub {forbidden}:", request)
        rows = [row for row in self.manifest["protected_file"] if row["path"] == WIRE]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / WIRE
            target.parent.mkdir(parents=True)
            target.write_text(source.replace("struct Request {", "struct Request {\n    pub batch: String,", 1))
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})


if __name__ == "__main__":
    unittest.main()
