import unittest

from cell_fast_path_actionir import ActionIRV1, ActionOpV1, compile_shadow_candidate, canonical_digest
from fast_path_shadow_qualification import (
    AuthorizationEnvelopeV1,
    GenerationBindingV1,
    GuardianAuthorizationVersionV1,
    ParentFallbackV1,
    PreconditionCheckV1,
    ReplayIndexV1,
    ResourceBudgetV1,
    ResourceObservationV1,
    ShadowQualificationContextV1,
    qualify_shadow_candidate,
)


D = "a" * 64
E = "b" * 64
F = "c" * 64
G = "d" * 64
H = "e" * 64
I = "f" * 64


def op(number: int = 1, name: str = "observe_ax") -> ActionOpV1:
    return ActionOpV1(
        op=name,
        target="window:main",
        args={},
        capability_id="cap.observe",
        idempotency_key=f"op-{number}",
        precondition_digest=D,
        postcondition_digest=E,
        reversible=True,
    )


def make_ir(*ops: ActionOpV1) -> ActionIRV1:
    return ActionIRV1(
        cell_id="cell.reflex",
        stem_digest=D,
        head_digest=E,
        objective_digest=F,
        app_identity="app.browser",
        body_generation=4,
        revocation_epoch=9,
        abi="wasm32-wasi",
        ops=tuple(ops),
        required_capabilities=("cap.observe",),
        max_ops=8,
        deadline_ms=25,
        max_memory_bytes=4096,
        determinism="strict",
    )


def make_candidate(program: ActionIRV1, *, backend="wasm_aot", target="cpu"):
    return compile_shadow_candidate(
        program,
        candidate_id="candidate.reflex.4",
        capability_manifest_digest=D,
        runtime_tuple_digest=G,
        policy_digest=E,
        snapshot_id="snapshot-4",
        authorization_version=make_auth().digest,
        backend=backend,
        target=target,
        evidence={"lane": "synthetic", "source": "p1-contract"},
    )


def make_auth() -> GuardianAuthorizationVersionV1:
    return GuardianAuthorizationVersionV1(7, 12, 6, 11)


def make_context(candidate, *, mode="shadow", body_generation=4, revocation_epoch=9, policy_digest=E):
    envelope = AuthorizationEnvelopeV1(
        app_identity="app.browser",
        authorization_version=make_auth().digest,
        capability_ids=("cap.observe",),
        capability_scope_digest=D,
        policy_digest=policy_digest,
        body_generation=body_generation,
        revocation_epoch=revocation_epoch,
        issued_at_ms=100,
        expires_at_ms=200,
    )
    binding = GenerationBindingV1(
        stem_digest=D,
        head_digest=E,
        objective_digest=F,
        artifact_digest=candidate.artifact_digest,
        runtime_tuple_digest=G,
        abi="wasm32-wasi",
        target=target_for(candidate),
        body_generation=4,
        snapshot_id="snapshot-4",
    )
    return ShadowQualificationContextV1(
        envelope=envelope,
        binding=binding,
        budget=ResourceBudgetV1(8, 25, 4096, 1000, 1000, 100),
        capability_scope_digest=D,
        policy_digest=policy_digest,
        target_handle_digest=H,
        window_tree_digest=I,
        mode=mode,
    )


def target_for(candidate):
    return "gpu" if candidate.backend == "cuda_graph" else "cpu"


def checks(program: ActionIRV1, *, passed=True):
    return {
        item.idempotency_key: PreconditionCheckV1(
            op_idempotency_key=item.idempotency_key,
            expected_digest=item.precondition_digest,
            observed_observation_digest=H,
            passed=passed,
            checked_at_ms=110,
        )
        for item in program.ops
    }


def observation(**changes):
    values = dict(
        observed_ops=1,
        elapsed_ms=1,
        cpu_ns=1,
        gpu_ns=0,
        peak_memory_bytes=10,
        bytes_touched=0,
    )
    values.update(changes)
    return ResourceObservationV1(**values)


def qualify(candidate, program, context, *, index=None, preconditions=None, obs=None, now=150, parent=None, pre=H, post=I):
    return qualify_shadow_candidate(
        candidate,
        program,
        context,
        now_ms=now,
        pre_observation_digest=pre,
        post_observation_digest=post,
        precondition_checks=checks(program) if preconditions is None else preconditions,
        observation=observation() if obs is None else obs,
        replay_index=ReplayIndexV1({}) if index is None else index,
        parent_fallback=parent,
    )


class ShadowQualificationTests(unittest.TestCase):
    def test_exact_candidate_is_admitted_only_to_shadow(self):
        program = make_ir(op())
        item = make_candidate(program)
        result = qualify(item, program, make_context(item))
        self.assertEqual(result.decision.status, "ADMIT_SHADOW")
        self.assertFalse(result.decision.effect_admitted)
        self.assertEqual(result.decision.authority, "DENY_ALL")
        self.assertFalse(result.decision.receipt.executed)

    def test_stale_authorization_and_expiry_fail_closed(self):
        program = make_ir(op())
        item = make_candidate(program)
        stale = type(item)(**{**item.__dict__, "authorization_version": D})
        result = qualify(stale, program, make_context(stale))
        self.assertEqual(result.decision.status, "NO_SAFE_FALLBACK")
        self.assertIn("STALE_AUTHORIZATION", result.decision.reason_codes)
        expired = qualify(item, program, make_context(item), now=200)
        self.assertIn("EXPIRED", expired.decision.reason_codes)

    def test_revocation_and_generation_boundaries(self):
        program = make_ir(op())
        item = make_candidate(program)
        revoked = qualify(item, program, make_context(item, revocation_epoch=10))
        self.assertIn("REVOKED_CAPABILITY", revoked.decision.reason_codes)
        future = qualify(item, program, make_context(item, revocation_epoch=8))
        self.assertIn("FUTURE_REVOCATION_EPOCH", future.decision.reason_codes)
        stale_generation = qualify(item, program, make_context(item, body_generation=5))
        self.assertIn("GENERATION_STALE", stale_generation.decision.reason_codes)
        future_generation = qualify(item, program, make_context(item, body_generation=3))
        self.assertIn("FUTURE_GENERATION_REJECTED", future_generation.decision.reason_codes)

    def test_exact_artifact_and_runtime_bindings_are_checked(self):
        program = make_ir(op())
        item = make_candidate(program)
        wrong_binding = make_context(item)
        wrong_binding = type(wrong_binding)(
            envelope=wrong_binding.envelope,
            binding=type(wrong_binding.binding)(**{**wrong_binding.binding.as_dict(), "stem_digest": G}),
            budget=wrong_binding.budget,
            capability_scope_digest=wrong_binding.capability_scope_digest,
            policy_digest=wrong_binding.policy_digest,
            target_handle_digest=wrong_binding.target_handle_digest,
            window_tree_digest=wrong_binding.window_tree_digest,
            mode=wrong_binding.mode,
        )
        result = qualify(item, program, wrong_binding)
        self.assertIn("STEM_MISMATCH", result.decision.reason_codes)

        stale_binding = make_context(item)
        stale_binding = type(stale_binding)(
            envelope=stale_binding.envelope,
            binding=type(stale_binding.binding)(
                **{
                    **stale_binding.binding.as_dict(),
                    "runtime_tuple_digest": H,
                    "snapshot_id": "snapshot-5",
                }
            ),
            budget=stale_binding.budget,
            capability_scope_digest=stale_binding.capability_scope_digest,
            policy_digest=stale_binding.policy_digest,
            target_handle_digest=stale_binding.target_handle_digest,
            window_tree_digest=stale_binding.window_tree_digest,
            mode=stale_binding.mode,
        )
        stale_result = qualify(item, program, stale_binding)
        self.assertIn("RUNTIME_TUPLE_MISMATCH", stale_result.decision.reason_codes)
        self.assertIn("SNAPSHOT_MISMATCH", stale_result.decision.reason_codes)

    def test_capability_and_policy_scope_mismatch(self):
        program = make_ir(op())
        item = make_candidate(program)
        context = make_context(item)
        empty_values = {field: getattr(context.envelope, field) for field in context.envelope.__dataclass_fields__}
        empty_values["capability_ids"] = ()
        empty_envelope = type(context.envelope)(**empty_values)
        context = type(context)(
            envelope=empty_envelope,
            binding=context.binding,
            budget=context.budget,
            capability_scope_digest=context.capability_scope_digest,
            policy_digest=context.policy_digest,
            target_handle_digest=context.target_handle_digest,
            window_tree_digest=context.window_tree_digest,
            mode=context.mode,
        )
        result = qualify(item, program, context)
        self.assertIn("CAPABILITY_SCOPE_MISMATCH", result.decision.reason_codes)

    def test_precondition_missing_or_false_rejects(self):
        program = make_ir(op(), op(2, "assert"))
        item = make_candidate(program)
        missing = qualify(item, program, make_context(item), preconditions={})
        self.assertIn("PRECONDITION_FAILED", missing.decision.reason_codes)
        failed = qualify(item, program, make_context(item), preconditions=checks(program, passed=False))
        self.assertIn("PRECONDITION_FAILED", failed.decision.reason_codes)

    def test_each_resource_dimension_is_fail_closed(self):
        program = make_ir(op())
        item = make_candidate(program)
        for field, value in {
            "observed_ops": 9,
            "elapsed_ms": 26,
            "cpu_ns": 1001,
            "gpu_ns": 1001,
            "peak_memory_bytes": 4097,
            "bytes_touched": 101,
        }.items():
            with self.subTest(field=field):
                result = qualify(item, program, make_context(item), obs=observation(**{field: value}))
                self.assertIn("BUDGET_EXCEEDED", result.decision.reason_codes)

    def test_duplicate_and_conflicting_replay(self):
        program = make_ir(op())
        item = make_candidate(program)
        context = make_context(item)
        first = qualify(item, program, context)
        duplicate = qualify(item, program, context, index=first.replay_index)
        self.assertEqual(duplicate.decision.status, "NO_SAFE_FALLBACK")
        self.assertIn("DUPLICATE_REPLAY", duplicate.decision.reason_codes)
        conflict = qualify(item, program, context, index=first.replay_index, obs=observation(cpu_ns=2))
        self.assertEqual(conflict.decision.status, "NO_SAFE_FALLBACK")
        self.assertIn("REPLAY_CONFLICT", conflict.decision.reason_codes)

    def test_parent_fallback_is_validated_and_never_admitted(self):
        program = make_ir(op())
        item = make_candidate(program)
        context = make_context(item, body_generation=5)
        parent = ParentFallbackV1(
            parent_candidate_id="candidate.parent.3",
            parent_action_ir_digest=D,
            parent_artifact_digest=E,
            parent_body_generation=3,
            parent_stem_digest=D,
            parent_app_identity="app.browser",
            parent_objective_digest=F,
            reason_code="GENERATION_STALE",
        )
        result = qualify(item, program, context, parent=parent)
        self.assertEqual(result.decision.status, "FALLBACK_PARENT")
        self.assertFalse(result.decision.effect_admitted)
        self.assertEqual(result.decision.parent_fallback.parent_candidate_id, "candidate.parent.3")
        self.assertIsNone(qualify(item, program, context, parent=None).decision.parent_fallback)

    def test_cpu_non_effect_lane_requires_guardian_for_effect_ops(self):
        program = make_ir(op(1, "click"))
        item = make_candidate(program)
        result = qualify(item, program, make_context(item, mode="cpu_non_effect"))
        self.assertIn("EFFECT_REQUIRES_GUARDIAN", result.decision.reason_codes)
        self.assertFalse(result.decision.effect_admitted)

    def test_cuda_graph_target_pairing(self):
        program = make_ir(op())
        item = make_candidate(program, backend="cuda_graph", target="cpu")
        context = make_context(item)
        result = qualify(item, program, context)
        self.assertIn("ARTIFACT_TARGET_MISMATCH", result.decision.reason_codes)

    def test_context_digest_and_reason_order_are_deterministic(self):
        program = make_ir(op())
        item = make_candidate(program)
        first = qualify(item, program, make_context(item), now=200)
        second = qualify(item, program, make_context(item), now=200)
        self.assertEqual(first.decision.context_digest, second.decision.context_digest)
        self.assertEqual(first.decision.reason_codes, second.decision.reason_codes)
        self.assertEqual(first.decision.as_dict(), second.decision.as_dict())


if __name__ == "__main__":
    unittest.main()
