"""Mutation guards for the original retained-Version Root issuer path.

These are source controls, not execution, deployment or signature qualification.
They preserve the original protected socket, one actual Prepared binding and
the original FinalUse publication verifier without granting any new policy.
"""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "retained_version_issuer_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
WRAPPER = AGENT + "root_retained_version_issuer.rs"
WORKER = AGENT + "circuit_retained_version_issuer.rs"
HOST = AGENT + "circuit_retained_version_host.rs"
EFFECT = AGENT + "circuit_retained_version_effect.rs"
SERVICE = AGENT + "circuit_retained_version_service.rs"
EXPECTED = {
    "learning_retained_version_original_issuer_attenuation": ('codex-rs/hepta-agentd/src/circuit_retained_version_host.rs', 'codex-rs/hepta-agentd/src/circuit_evaluated_version_host.rs'),
    "learning_retained_version_original_issuer_request": (WORKER,),
    "learning_retained_version_original_issuer_worker": (SERVICE,),
    "learning_retained_version_original_final_use": (WORKER,),
}


class OriginalRetainedVersionIssuerClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

    def rejects_source(self, path, changed):
        source = (ROOT / path).read_text()
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(changed)
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def rejects(self, path, function, marker):
        source = (ROOT / path).read_text()
        start = source.index("fn " + function + "(")
        end = PROOF._rust_item_end(PROOF._strip_rust_non_code(source), start)
        self.assertIsNotNone(end)
        offset = source.index(marker, start, end + 1)
        self.rejects_source(path, source[:offset] + source[offset + len(marker):])

    def reject_each(self, path, function, markers):
        for marker in markers:
            with self.subTest(function=function, marker=marker):
                self.rejects(path, function, marker)

    def test_original_issuer_has_only_actual_version_callers(self):
        paths = {
            path
            for identifier in EXPECTED
            for path in (
                self.boundaries[identifier].definition_path,
                *self.boundaries[identifier].product_callers,
            )
        }
        sources = {
            path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / path).read_text()))
            for path in paths
        }
        for identifier, expected in EXPECTED.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, expected)
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT, row, sources, ())
                method = row.symbol.rsplit("::", 1)[1]
                injected = dict(sources)
                injected[AGENT + "unregistered_retained_issuer.rs"] = (
                    f"fn bypass(owner: &{row.receiver_type}) {{ owner.{method}(); }}"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, injected, ())
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_legacy_or_non_root_provider_cannot_be_promoted(self):
        self.reject_each(WRAPPER, "into_original_retained_version_issuer", (
            "self\n            .protected_root\n            .as_ref()", "root.original_uid != 0",
            "self.check_root()?", "super::super::remaining(root.end)?",
            "self\n                .stream\n                .try_lock()", "if slot.is_none()", "provider: self",
        ))
        self.reject_each(HOST, "from_original_owners", (
            "final_use_issuer: AgentdUnixFinalUseGrantProvider",
            "task.require_completed_a(&inputs.completed)?",
            "RetainedVersionArtifactOwnerV1::new(",
            "AgentdUnixFinalUseGrantProvider::into_original_retained_version_issuer(",
            "final_use_issuer: Some(final_use_issuer)",
        ))

    def test_exact_purpose_and_once_survive_a_legal_denial(self):
        self.reject_each(WRAPPER, "request_for_original_retained_version", (
            'binding.destination_id != ORIGINAL_RETAINED_VERSION_DESTINATION',
            "binding.subject_id.is_empty()", "binding.request_sha256 == [0; 32]",
            "binding.scope_sha256 == [0; 32]", "binding.payload_sha256 == [0; 32]",
            "!matches!(self.access, OriginalVersionIssuerAccessV1::Available)",
            "self.access = OriginalVersionIssuerAccessV1::ReadbackOnly",
            "AgentdUnixFinalUseGrantProvider::request_grant(&self.provider, binding)",
        ))
        self.reject_each(WORKER, "serve_original_final_use", (
            "self.issuer_worker_started.swap(true, Ordering::AcqRel)",
            "AgentdFinalUseIssuerError::Denied",
            "RetainedVersionFinalUseOutcomeV1::Denied as u8",
            "drop(queued)",
        ))

    def test_claim_comes_only_from_the_actual_current_prepared_owner(self):
        self.reject_each(WORKER, "claim_original_final_use", (
            "self.origin != RetainedVersionOriginV1::Fresh",
            "self.original_final_use_outcome() != RetainedVersionFinalUseOutcomeV1::Awaiting",
            "self.state.try_lock()", "RetainedVersionHostPhaseV1::Awaiting",
            "RetainedVersionHostPhaseV1::Prepared",
            "!self.preparation_requested.load(Ordering::Acquire)",
            "self.read_original(&state)?", "let binding = original.final_use_binding().clone()",
            ".require_fresh(started, PublicationAccess::NewWork)?",
            "state\n            .final_use_issuer\n            .take()\n            .ok_or(Error::ReadbackRequired)?",
            "RetainedVersionFinalUseOutcomeV1::Requested as u8",
        ))

    def test_queued_cancel_and_last_actual_read_precede_root_request(self):
        self.reject_each(WORKER, "serve_original_final_use", (
            "QueuedOriginalVersionIssuerV1::new()",
            "let response = tokio::task::spawn_blocking(move ||",
            "require_not_cancelled(&cancelled)?", "owner.read_original(&state)?",
            "original.final_use_binding() != &binding",
            ".require_fresh(started, PublicationAccess::NewWork)?",
            "OriginalRootRetainedVersionIssuerV1::request_for_original_retained_version(",
        ))
        self.rejects(WORKER, "drop", "self.cancelled.store(true, Ordering::Release)")
        self.rejects(WORKER, "require_not_cancelled", "cancelled.load(Ordering::Acquire)")

    def test_cold_and_unknown_never_reset_the_original_issuer(self):
        self.reject_each(HOST, "recover_from_original_owners", (
            "RetainedVersionOriginV1::Recovered", "final_use_issuer: None",
        ))
        self.reject_each(HOST, "new", (
            "issuer_worker_started: AtomicBool::new(origin == RetainedVersionOriginV1::Recovered)",
            "RetainedVersionOriginV1::Fresh => RetainedVersionFinalUseOutcomeV1::Awaiting as u8",
            "RetainedVersionOriginV1::Recovered => {\n                    RetainedVersionFinalUseOutcomeV1::Published as u8\n                }",
            "runtime_started: AtomicBool::new(origin == RetainedVersionOriginV1::Recovered)",
        ))
        source = (ROOT / WORKER).read_text()
        for injected in (
            "self.issuer_worker_started.store(false, Ordering::Release);",
            "state.final_use_issuer = Some(issuer);",
        ):
            with self.subTest(injected=injected):
                self.rejects_source(WORKER, source + "\nfn unsafe_reset() { " + injected + " }\n")

    def test_publication_and_c_runtime_keep_the_original_verifier_tail(self):
        self.reject_each(EFFECT, "publish_original_final_use", (
            "self.original_final_use_outcome() != RetainedVersionFinalUseOutcomeV1::Requested",
            "state.final_use_issuer.is_some()",
            "signed.grant.binding != original.final_use_binding()",
            "self.publication_requested.swap(true, Ordering::AcqRel)",
            "original.publish(signed)", "task\n                .install_original(published, cut, intent)",
            "self.final_use_outcome.store(\n                RetainedVersionFinalUseOutcomeV1::Published as u8,\n                Ordering::Release,\n            )",
        ))
        # The actual owned legacy publication moved into the private enum.
        # Preserve the old consuming call attack at its new active location.
        self.reject_each(AGENT + "circuit_retained_version_prepared.rs", "publish", (
            "self,", "PreparedOriginalCircuitRetainedPublicationV1::publish_and_retain_original_trainer(",
            "*original, signed,",
        ))
        self.reject_each(EFFECT, "run_original_c", (
            "owner.read_original(&state)?",
            "owner.original_final_use_outcome() != RetainedVersionFinalUseOutcomeV1::Published",
            "config.take()", "crate::run(config, arg0_paths).await",
        ))
        source = (ROOT / EFFECT).read_text()
        self.rejects_source(EFFECT, source.replace(
            "pub(super) async fn publish_original_final_use(",
            "pub async fn publish_original_final_use(", 1,
        ))

    def test_ordinary_host_really_serves_the_issuer_and_preserves_denied_readback(self):
        self.rejects(SERVICE, "serve_original_ordinary",
                     "OriginalCircuitRetainedVersionHostV1::serve_original_final_use(")
        self.reject_each(SERVICE, "command_response", (
            "self.read_original(&state)", "self.original_final_use_outcome()",
            "RetainedVersionFinalUseOutcomeV1::Denied", "wire::OriginalResult::FinalUseDenied",
            "RetainedVersionFinalUseOutcomeV1::Requested",
            "RetainedVersionFinalUseOutcomeV1::Uncertain",
        ))

    def test_no_new_key_policy_socket_or_resident_grant_authorizes_publication(self):
        for path in (WRAPPER, WORKER, HOST, EFFECT, SERVICE):
            source = (ROOT / path).read_text()
            for token in (
                "SigningKey", "UnixStream::connect", "initialize_host_authority(",
                "DeploymentFinalUseIssuer::issue(", "ROOT_RESIDENT_LEARNING_EXECUTE",
                "AgentdUnixFinalUseGrantProvider::from_stream(",
            ):
                with self.subTest(path=path, token=token):
                    self.rejects_source(path, source + "\nfn bypass() { " + token + "; }\n")


if __name__ == "__main__":
    unittest.main()
