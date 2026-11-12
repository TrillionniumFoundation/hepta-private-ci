"""Keep ordinary learning bootstrap on the original registered Root scope."""

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "root_learning_caller_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
PROFILE = AGENT + "authority_host_learning_profile.rs"
REGISTRATION = AGENT + "authority_host_learning_registration.rs"
SESSION = AGENT + "authority_host_learning_session.rs"
MODEL_REGISTRATION = AGENT + "authority_host_q24_model_registration.rs"
PUBLICATION_ROUTE = AGENT + "authority_host_original_publication_route.rs"
INITIAL_SESSION = AGENT + "authority_host_generation_initial_session.rs"
HANDOFF = AGENT + "root_production_learning_handoff.rs"
INPUTS = AGENT + "root_production_learning_inputs.rs"
CONFIG = AGENT + "config_root_learning.rs"
DELIVERY = AGENT + "learning_iteration_delivery_runtime.rs"
SOURCE = AGENT + "objective_learning_source.rs"
LAUNCHER = AGENT + "production_launcher.rs"
CLI = AGENT + "bin/hepta-authority-host.rs"
CALLERS = {
    "root_prepared_fresh_session": (CLI,),
    "root_retained_native_ui_launch": (),
    "root_retained_native_ready_launch": (CLI,),
    "root_prepared_native_ready_text_session": (AGENT + "authority_host_native_launch.rs", CLI),
    "root_learning_explicit_registration": (CLI,),
    "root_learning_original_store_registration": (AGENT + "authority_host_runtime.rs",),
    "root_learning_original_store_reopen": (SESSION, MODEL_REGISTRATION),
    "root_learning_original_owner_install": (CLI,),
    "root_learning_original_scope_seal": (CLI,),
    "root_learning_original_scope_capture": (SESSION, AGENT + "authority_host_post_a_learning.rs"),
    "root_learning_same_service_serve": (SESSION,),
    "root_learning_registered_checkpoint_constructor": (REGISTRATION,),
    "root_learning_scoped_checkpoint_constructor": (REGISTRATION,),
    "root_learning_original_client_constructor": (),
    "root_learning_scoped_client_constructor": (),
    "root_learning_original_purpose_send": (CLI, AGENT + "authority_host_post_a_worker.rs"),
    "root_learning_original_purpose_receive": (
        LAUNCHER, AGENT + "production_launcher_late_writer.rs",
        AGENT + "production_post_a_q24_handoff.rs",
    ),
    "root_learning_original_handoff_consume": (
        LAUNCHER, AGENT + "production_launcher_late_writer.rs",
    ),
    "root_learning_original_config_hold": (
        LAUNCHER, AGENT + "production_launcher_late_writer.rs",
        AGENT + "production_post_a_q24.rs",
    ),
    "root_learning_original_stage_assembly": (),
    "root_learning_original_runtime_consume": (CONFIG,),
    "root_learning_original_delivery_source": (INPUTS,),
    "root_learning_completed_circuit_source": (DELIVERY,),
    "root_original_registered_ready_serve": (CLI,),
    "root_original_private_sealed_bytes": (
        REGISTRATION, MODEL_REGISTRATION, PUBLICATION_ROUTE, INITIAL_SESSION,
        AGENT + "authority_host_historical_read_session.rs",
    ),
}


class RootLearningBootstrapSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {
            row.identifier: row for row in PROOF._boundary_rows(cls.manifest)
        }
        paths = {
            path
            for identifier in CALLERS
            for path in (
                cls.boundaries[identifier].definition_path,
                *cls.boundaries[identifier].product_callers,
            )
        }
        cls.sources = {
            path: PROOF._strip_cfg_test_items(
                PROOF._strip_rust_non_code((ROOT / path).read_text())
            )
            for path in paths
        }

    def rejects(self, path, function, marker, occurrence=0, *, replacement=""):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows)
        source = (ROOT / path).read_text()
        start = source.index(function)
        end = PROOF._rust_item_end(PROOF._strip_rust_non_code(source), start)
        self.assertIsNotNone(end)
        assert end is not None
        body = source[start : end + 1]
        offset = -len(marker)
        for _ in range(occurrence + 1):
            offset = body.find(marker, offset + len(marker))
            self.assertGreaterEqual(offset, 0, marker)
        offset += start
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

    def test_inventory_and_exact_product_callers_are_closed(self):
        inventory = self.manifest["privileged_inventory"]["required_boundary_ids"]
        for identifier, callers in CALLERS.items():
            with self.subTest(boundary=identifier):
                self.assertIn(identifier, inventory)
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, callers)
                PROOF._verify_boundary(ROOT, row, self.sources, ())
                if callers:
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_boundary(
                            ROOT, replace(row, product_callers=()), self.sources, ()
                        )
                method = row.symbol.rsplit("::", 1)[-1]
                unexpected = (
                    f"fn unregistered(original: &{row.receiver_type}) {{ original.{method}(); }}"
                    if row.receiver_type else f"fn unregistered() {{ {row.symbol}(); }}"
                )
                sources = dict(self.sources)
                sources[AGENT + "unregistered_learning_caller.rs"] = unexpected
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, sources, ())
        self.assertTrue(self.manifest["authority"])
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_registration_cannot_omit_original_authority_or_postchecks(self):
        function = "fn with_learning_profile<T>("
        for marker in (
            "config.required_bind.verify()?",
            "RootAuthorityDirectory::open(&config.state_dir)",
            "config.schema_version != 1",
            "registration.schema_version != 1",
            "config.peer_uid == 0\n            || config.peer_gid == 0",
            "!(1..=500).contains(&config.timeout_ms)",
            "!(1..=300_000).contains(&config.lifetime_ms)",
            "!config\n                .state_dir\n                .starts_with(&config.required_bind.mountpoint)",
            "registration.registered_identity.identity()? != self.identity",
            "config.writer.as_ref() != Some(&writer.registration)",
            "writer.registration.with_live(&writer.leases, |_| {",
            "profile.require_binding(&self.identity, &proof)?",
            "let before = self.issuer.revocations()?",
            "self.issuer.revocations()? != before",
        ):
            with self.subTest(marker=marker):
                self.rejects(REGISTRATION, function, marker)
        for marker in (
            "verify_pinned_process(",
            "self.check_logind_lifetime()?",
            "retained_writer_authorization(&writer.registration)?",
            "validate_observation_lease(",
        ):
            for occurrence in range(2):
                with self.subTest(marker=marker, occurrence=occurrence):
                    self.rejects(REGISTRATION, function, marker, occurrence)

    def test_recovery_is_open_only_and_uses_original_owner(self):
        for function, marker in (
            ("fn open_registered_learning_checkpoint(", "StoreMode::Reopen"),
            ("fn learning_store(", "StoreMode::Reopen => HostAuthorityFrontierStore::open("),
            ("fn learning_store(", "LearningIterationCheckpointOwnerV1::from_registered("),
            ("fn learning_store(", "LearningIterationCheckpointOwnerV1::from_registered_scoped_v2("),
            ("fn learning_store(", "LearningIterationCheckpointRecordV1::vacant_scoped_v2("),
            ("fn seal_learning_checkpoint(", "!= before"),
        ):
            with self.subTest(marker=marker):
                self.rejects(REGISTRATION, function, marker)

    def test_profile_requires_canonical_empty_initial_and_original_writer(self):
        for function, marker in (
            ("fn require_binding(", "proof.is_zero()"),
            ("fn require_binding(", "self.writer_proof_digest != writer_proof_digest"),
            ("fn require_binding(", "neuron_generation_process_identity_digest_v1(identity)"),
            ("fn decode_initial(encoded: &str)", "STANDARD_NO_PAD.encode(&bytes) != encoded"),
            ("fn decode_initial(encoded: &str)", "expected.snapshot() != &initial"),
            ("fn decode_initial(encoded: &str)", "codec::encode(&initial)"),
        ):
            with self.subTest(marker=marker):
                self.rejects(PROFILE, function, marker)

    def test_handoff_requires_original_root_and_exact_two_rights(self):
        for function, markers in (
            ("fn send_root_learning_handoff(", (
                "libc::getuid()", "libc::geteuid()", "root_pair(&socket, timeout)?",
                "peer.pid as u32 != std::process::id()", "validate_bootstrap(bootstrap)?",
                "require_root_pin(root_pidfd, std::process::id())?",
            )),
            ("fn receive_learning_packet(", (
                "libc::MSG_CMSG_CLOEXEC", "if !valid", "libc::MSG_TRUNC | libc::MSG_CTRUNC",
                "descriptors.len() != 2", "length as usize != LEARNING_FRAME.len()",
                "&bytes[..LEARNING_FRAME.len()] != LEARNING_FRAME",
            )),
        ):
            for marker in markers:
                with self.subTest(marker=marker):
                    self.rejects(HANDOFF, function, marker)

    def test_client_requires_cross_lane_scope_and_original_current(self):
        for marker in (
            "!matches!(bundle.schema_version, 1 | 2)", "bundle.frozen_scope(&initial)?",
            "bundle.root != original.root", "bundle.consumer != original.consumer",
            "bundle.root.pid != root_pid", "bundle.root.uid != 0",
            "bundle.registered_identity.identity()? != *expected",
            "original.registered_identity.identity()? != *expected",
            "bundle.writer_proof_digest != original.writer_proof.sha256()?.as_str()",
            "bundle.socket_path != socket", "bundle.decode_initial()?",
        ):
            with self.subTest(marker=marker):
                self.rejects(INPUTS, "fn validate_binding(", marker)
        self.rejects(INPUTS, "fn connect_until(", "client\n            .restore(&initial.request)\n            .await")
        for marker in (
            "timeout.is_zero()", "timeout > Duration::from_millis(500)",
            "lifetime.is_zero()", "lifetime > Duration::from_secs(300)",
        ):
            with self.subTest(marker=marker):
                self.rejects(INPUTS, "fn connect(", marker)
        for occurrence in range(2):
            self.rejects(INPUTS, "fn connect_until(", "validate_sealed(&self.bootstrap, length)?", occurrence)

    def test_unassembled_stage_owners_are_refused_before_runtime_side_effects(self):
        self.rejects(CONFIG, "fn require_root_learning_assembled(", "self.root_learning_inputs.is_some()")
        self.rejects(LAUNCHER, "fn run(", "config.require_root_learning_assembled()?")
        self.rejects(AGENT + "runtime.rs", "fn run_with_shutdown(", "config.require_root_learning_assembled()?")
        self.rejects(CONFIG, "fn with_root_learning_stage_owners(", "inputs.into_learning_runtime(stages, verifier, capacity)?")

    def test_original_source_scope_requires_registered_membership(self):
        function = "fn require_circuit_learning_source("
        membership = (
            "!self\n"
            "                .circuit_learning_sources()\n"
            "                .contains(&request.source_run_id)"
        )
        self.rejects(SOURCE, function, "|| " + membership)
        self.rejects(SOURCE, function, membership, replacement=membership[1:])
        self.rejects(
            SOURCE,
            function,
            membership,
            replacement="self.circuit_learning_sources().first() != Some(&request.source_run_id)",
        )
        self.rejects(
            SOURCE,
            function,
            "request.agent_id.as_str() != self.identity().agent_id.as_str()",
            replacement="false",
        )

    def test_original_root_source_join_cannot_be_dropped_or_downgraded(self):
        self.rejects(INPUTS, "fn into_learning_runtime(", "bootstrap.with_original_circuit_learning_delivery(self.initial.request)?")
        self.rejects(DELIVERY, "fn with_original_circuit_learning_delivery(", "bootstrap.circuit_delivery_source = CircuitLearningSourceV1::OriginalObjective")
        self.rejects(DELIVERY, "fn run(", "if !claimed && self.source.requires_original_objective()")
        self.rejects(DELIVERY, "fn run(", "state.require_circuit_learning_source(request)")
        self.rejects(
            DELIVERY, "fn run(", "else if self.source.requires_original_objective()",
            replacement="else if false",
        )
        self.rejects(DELIVERY, "fn run(", ".require_circuit_learning_source(&source_request)")
        for occurrence in range(2):
            self.rejects(SOURCE, "fn require_circuit_learning_source(", "self.require_learning_source_authentication(&original.0)?", occurrence)
        self.rejects(SOURCE, "fn require_learning_source_authentication(", "authbus_ingress::require_objective_ready(self)?")
        self.rejects(SOURCE, "fn require_learning_source_authentication(", "authbus_ingress::attached(self)?.trust(self)?")
        self.rejects(SOURCE, "fn authenticate_learning_source_at(", "authentication_is_current(record, trust, identity, admitted_ms)?")

    def test_each_original_source_kind_cannot_fall_back_to_host_stage_owners(self):
        branches = (
            "Self::HostStageOwners => false,\n"
            "            Self::OriginalObjective | Self::OriginalQ24 => true,"
        )
        for replacement in (
            "Self::HostStageOwners | Self::OriginalObjective => false,\n"
            "            Self::OriginalQ24 => true,",
            "Self::HostStageOwners | Self::OriginalQ24 => false,\n"
            "            Self::OriginalObjective => true,",
        ):
            with self.subTest(replacement=replacement):
                self.rejects(
                    DELIVERY, "fn requires_original_objective(", branches,
                    replacement=replacement,
                )

    def test_retained_original_source_cannot_be_dropped_or_use_current_outbox(self):
        for path, function, marker, replacement in (
            (DELIVERY, "fn take_circuit_delivery(",
             "retained_source: self.retained_source.take()", "retained_source: None"),
            (DELIVERY, "fn attach_sources(",
             "return state.attach_original_retained_learning_source(Arc::clone(source));", ""),
            (DELIVERY, "fn run(",
             "source.observe_retained_learning(state.identity()).await?;", ""),
            (DELIVERY, "fn run(",
             "self.requests.as_slice() != std::slice::from_ref(source.request())", "false"),
            (DELIVERY, "fn run(",
             "source.original_outbox(state.identity(), source.request())?", "store"),
            (SOURCE, "fn require_circuit_learning_source(",
             "return self\n                .require_registered_retained_source(request, source)\n                .await",
             "return Ok(())"),
        ):
            with self.subTest(path=path, marker=marker):
                self.rejects(path, function, marker, replacement=replacement)

    def test_pending_guard_must_execute_at_top_level(self):
        guard = "config.require_root_learning_assembled()?;"
        for path, function in ((LAUNCHER, "fn run("), (AGENT + "runtime.rs", "fn run_with_shutdown(")):
            for replacement in ("if false { " + guard + " }", "fn unused() { " + guard + " }"):
                with self.subTest(path=path, replacement=replacement):
                    self.rejects(path, function, guard, replacement=replacement)

    def test_registered_learning_cannot_be_silently_dropped_by_retained_serve(self):
        self.rejects(AGENT + "authority_host_session_material.rs", "fn serve_retained(", "self.learning.is_some()")
        self.rejects(SESSION, "fn serve_optional_with_end(", "None => service.serve_learning_checkpoint(")
        self.rejects(SESSION, "fn serve_optional_with_end(", "stream.shutdown(Shutdown::Both)")

    def test_scoped_profile_cannot_downgrade_during_registration_handoff_or_runtime(self):
        for path, function, markers in (
            (PROFILE, "fn require_binding(", ("self.frozen_scope(&initial)?",)),
            (PROFILE, "fn new_scoped_v2(", (
                "FrozenLearningScopeV2::freeze(&request, &owners, scope, update_rule)",
                "profile.schema_version = 2", "profile.require_binding(identity, &profile.writer_proof_digest)?",
            )),
            (PROFILE, "fn decode_scope(", (
                "(1, None) => Ok(None)", "(2, Some(scope)) => scope.freeze(initial).map(Some)",
            )),
            (PROFILE, "fn freeze(", (
                "self.update_rule != update_rule.to_string()", "self.binding != frozen.binding().to_string()",
            )),
            (PROFILE, "impl HostAuthorityLearningBootstrapV1 {", (
                "2 => HOST_AUTHORITY_LEARNING_BOOTSTRAP_V2", "self.operation != expected",
                "decode_scope(self.schema_version, self.update_scope.as_ref(), initial)",
            )),
            (INPUTS, "fn connect_until(", (
                "bundle.frozen_scope(&initial)?",
                "AgentdLearningCheckpointClientV1::from_original_stream_until(",
            )),
            (INPUTS, "fn into_learning_runtime(", (
                "match self.scope", "Some(scope) => crate::learning_iteration_channel_scoped_v2(",
            )),
        ):
            for marker in markers:
                with self.subTest(path=path, function=function, marker=marker):
                    self.rejects(path, function, marker)
