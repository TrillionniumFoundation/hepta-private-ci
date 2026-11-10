"""Keep the frozen Cell/Organ profile on its original Root capability path."""

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "root_learning_scope_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
PROFILE = AGENT + "authority_host_learning_profile.rs"
Q24_PLAN = AGENT + "cell_composed_q24_training_plan.rs"
REGISTRATION = AGENT + "authority_host_learning_registration.rs"
CHECKPOINT = AGENT + "learning_iteration_checkpoint.rs"
TRANSPORT = AGENT + "learning_iteration_checkpoint_transport.rs"
INPUTS = AGENT + "root_production_learning_inputs.rs"
WORKER = AGENT + "learning_iteration.rs"
SCOPE = "codex-rs/hepta-learning-artifacts/src/learning_iteration_scope.rs"
CALLERS = {
    "learning_frozen_update_scope_constructor": (PROFILE, Q24_PLAN),
    "root_learning_scoped_profile_constructor": (),
    "root_learning_scoped_checkpoint_record": (REGISTRATION,),
    "root_learning_scoped_checkpoint_constructor": (REGISTRATION,),
    "root_learning_scoped_client_constructor": (INPUTS,),
    "root_learning_scoped_runtime_constructor": (INPUTS,),
}


class RootLearningScopeSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}
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

    def rejects(self, path, item, marker, *, replacement=""):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows)
        source = (ROOT / path).read_text()
        start = source.index(item)
        end = PROOF._rust_item_end(PROOF._strip_rust_non_code(source), start)
        self.assertIsNotNone(end)
        assert end is not None
        offset = source[start : end + 1].find(marker)
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

    def test_scoped_product_caller_sets_remain_exact(self):
        inventory = self.manifest["privileged_inventory"]["required_boundary_ids"]
        for identifier, callers in CALLERS.items():
            with self.subTest(boundary=identifier):
                self.assertIn(identifier, inventory)
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, callers)
                PROOF._verify_boundary(ROOT, row, self.sources, ())
                if callers:
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_boundary(ROOT, replace(row, product_callers=()), self.sources, ())
                sources = dict(self.sources)
                sources[AGENT + "unregistered_scope_caller.rs"] = (
                    f"fn unregistered() {{ {row.symbol}(); }}"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, sources, ())
        self.assertEqual(
            self.boundaries["root_learning_original_stage_assembly"].product_callers, ()
        )
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_evidence_uid_constructor_distinguishes_other_stream_types(self):
        row = self.boundaries["original_pinned_stream_explicit_uid"]
        paths = (
            row.definition_path,
            *row.product_callers,
            AGENT + "learning_iteration_evidence_test_support.rs",
            AGENT + "cognitive_checkpoint_unix.rs",
            "codex-rs/hepta-contracts/src/authority_root_frontier.rs",
        )
        sources = {
            path: PROOF._strip_cfg_test_items(
                PROOF._strip_rust_non_code((ROOT / path).read_text())
            )
            for path in paths
        }
        # The two existing transports call Self::from_stream_for_uid on their
        # own types. They cannot become callers of RootObservationStream.
        PROOF._verify_boundary(ROOT, row, sources, ())
        self.assertEqual(row.product_callers, (AGENT + "learning_iteration_evidence_client.rs",))
        for call in (
            "RootObservationStream :: from_stream_for_uid();",
            "use crate::root_observation_stream::RootObservationStream as Stream; "
            "Stream::from_stream_for_uid();",
            "type Stream = crate::root_observation_stream::RootObservationStream; "
            "Stream::from_stream_for_uid();",
        ):
            with self.subTest(call=call):
                changed = dict(sources)
                changed[AGENT + "unregistered_evidence_stream.rs"] = (
                    f"fn unregistered() {{ {call} }}"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, changed, ())

    def test_profile_requires_original_scope_rule_and_matching_schema(self):
        for item, marker in (
            ("fn require_binding(", "self.frozen_scope(&initial)?"),
            ("fn freeze(", "self.update_rule != update_rule.to_string()"),
            ("fn freeze(", "self.binding != frozen.binding().to_string()"),
            ("fn new_scoped_v2(", "FrozenLearningScopeV2::freeze("),
            ("fn new_scoped_v2(", "profile.require_binding("),
            ("fn decode_scope(", "(1, None) => Ok(None)"),
            ("fn decode_scope(", "(2, Some(scope)) => scope.freeze(initial).map(Some)"),
            ("impl HostAuthorityLearningBootstrapV1 {", "self.operation != expected"),
        ):
            with self.subTest(item=item, marker=marker):
                self.rejects(PROFILE, item, marker)

    def test_transport_cannot_downgrade_or_accept_another_profile(self):
        for item, markers in (
            ("fn from_root_stream(", ("None",)),
            ("fn from_root_stream_scoped_v2(", ("scope.validate_snapshot(&initial)", "Some(scope)")),
            ("fn from_stream_profile(", (
                "LearningIterationCoordinatorV1::new(", "expected.snapshot() != &initial",
                "RootObservationStream::from_stream(",
            )),
            ("fn profile_identity(", (
                "Some(binding) => (2, binding.to_string())",
                "None => (1, self.initial.head_digest.to_string())",
            )),
            ("async fn exchange<T>(", ("response.schema != request.schema",)),
            ("fn exchange_learning_checkpoint(", (
                "request.schema != schema", "request.binding != binding",
            )),
        ):
            for marker in markers:
                with self.subTest(item=item, marker=marker):
                    self.rejects(TRANSPORT, item, marker)

    def test_restored_training_and_checkpoint_are_checked_before_cas(self):
        for path, item, marker in (
            (CHECKPOINT, "fn vacant_scoped_v2(", "scope\n            .validate_request(&request, &owners)"),
            (CHECKPOINT, "fn from_registered_scoped_v2(", "scope\n            .validate_request(&request, &owners)"),
            (CHECKPOINT, "fn checkpoint(", "scope.validate_snapshot(next)"),
            (CHECKPOINT, "fn load(", "record.schema != schema"),
            (CHECKPOINT, "fn load(", "record.binding != binding"),
            (CHECKPOINT, "fn load(", "scope\n                .validate_snapshot(&snapshot)"),
            (TRANSPORT, "fn restore(", "scope\n                            .validate_snapshot(&snapshot)"),
            (TRANSPORT, "fn checkpoint(", "scope.validate_snapshot(snapshot)"),
        ):
            with self.subTest(path=path, item=item, marker=marker):
                self.rejects(path, item, marker)

    def test_worker_checks_scope_before_authentication_and_progress(self):
        for item, marker in (
            ("fn learning_iteration_channel_v1(", "None"),
            ("fn learning_iteration_channel_scoped_v2(", "Some(scope)"),
            ("fn learning_iteration_channel(", "ports.frozen_scope_binding() != scope.as_ref().map(FrozenLearningScopeV2::binding)"),
            ("fn require_frozen_scope(", "self.ports.frozen_scope_binding()"),
            ("fn require_frozen_scope(", "scope.validate_request(request, &self.owners)?"),
            ("fn process_readback(", "self.require_frozen_scope(&request)?"),
            ("fn process_readback(", "scope.validate_snapshot(restored.snapshot())?"),
            ("fn process(", "self.require_frozen_scope(&request)?"),
            ("fn process(", "scope.validate_snapshot(restored.snapshot())?"),
            ("fn process(", "scope.validate_observation(&receipt.observation)?"),
        ):
            with self.subTest(item=item, marker=marker):
                self.rejects(WORKER, item, marker)

    def test_root_handoff_retains_scope_through_the_worker_choice(self):
        for path, item, marker in (
            (REGISTRATION, "fn register_learning_checkpoint(", "profile.frozen_scope(&initial)?"),
            (REGISTRATION, "fn seal_learning_checkpoint(", "learning.backend.frozen_scope_binding()"),
            (REGISTRATION, "fn learning_store(", "scope.validate_snapshot(initial)"),
            (REGISTRATION, "fn learning_store(", "LearningIterationCheckpointOwnerV1::from_registered_scoped_v2("),
            (INPUTS, "fn validate_binding(", "bundle.frozen_scope(&initial)?"),
            (INPUTS, "fn connect(", "AgentdLearningCheckpointClientV1::from_root_stream_scoped_v2("),
            (INPUTS, "fn into_learning_runtime(", "match self.scope"),
            (INPUTS, "fn into_learning_runtime(", "crate::learning_iteration_channel_scoped_v2("),
        ):
            with self.subTest(path=path, item=item, marker=marker):
                self.rejects(path, item, marker)

    def test_frozen_component_boundary_and_rule_cannot_be_widened(self):
        for item, marker in (
            ("fn freeze(", "LearningIterationError::SlowReleaseRequired"),
            ("fn freeze(", "update_rule.is_zero()"),
            ("fn validate_request(", "initial_digest(request, owners)? != self.initial_head"),
            ("fn validate_observation(", "preserved != self.components"),
            ("fn validate_observation(", "!= Some(self.update_rule)"),
            ("fn validate_snapshot(", "self.validate_observation(&receipt.observation)?"),
        ):
            with self.subTest(item=item, marker=marker):
                self.rejects(SCOPE, item, marker)
        marker = "let mut preserved = candidate.components.clone();"
        for component in (
            "base", "encoder", "tokenizer", "normalizer", "numeric_profile",
            "output_schema", "state_schema", "state_semantics",
        ):
            with self.subTest(component=component):
                self.rejects(
                    SCOPE, "fn validate_observation(", marker,
                    replacement=marker + f" preserved.{component} = self.components.{component};",
                )
