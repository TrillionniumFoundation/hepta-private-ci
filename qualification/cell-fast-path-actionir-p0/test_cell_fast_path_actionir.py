import unittest

from cell_fast_path_actionir import (
    ActionIRV1,
    ActionOpV1,
    DENY_ALL,
    FastPathRuntimeReceiptV1,
    build_shadow_receipt,
    compile_shadow_candidate,
)


D = "a" * 64
E = "b" * 64
F = "c" * 64


def op(number: int = 1, *, args=None, name: str = "observe_ax") -> ActionOpV1:
    return ActionOpV1(
        op=name,
        target="window:main",
        args={} if args is None else args,
        capability_id="cap.observe",
        idempotency_key=f"op-{number}",
        precondition_digest=D,
        postcondition_digest=E,
        reversible=True,
    )


def ir(*ops: ActionOpV1, **kwargs) -> ActionIRV1:
    values = dict(
        cell_id="cell.reflex",
        stem_digest=D,
        head_digest=E,
        objective_digest=F,
        app_identity="app.browser",
        body_generation=4,
        revocation_epoch=9,
        abi="wasm32-wasi",
        required_capabilities=("cap.observe",),
        max_ops=8,
        deadline_ms=25,
        max_memory_bytes=4096,
        determinism="strict",
    )
    values.update(kwargs)
    return ActionIRV1(ops=tuple(ops), **values)


def candidate(program: ActionIRV1):
    return compile_shadow_candidate(
        program,
        candidate_id="candidate.reflex.4",
        capability_manifest_digest=D,
        authorization_version="auth.v3",
        backend="wasm_aot",
        target="cpu",
        evidence={"lane": "synthetic", "source": "contract-test"},
    )


class ActionIRContractTests(unittest.TestCase):
    def test_valid_shadow_candidate_and_receipt(self):
        program = ir(op(1), op(2, name="assert"))
        item = candidate(program)
        self.assertEqual(item.action_ir_digest, program.digest)
        self.assertEqual(item.cell_id, program.cell_id)
        self.assertEqual(item.app_identity, program.app_identity)
        self.assertEqual(item.revocation_epoch, 9)
        self.assertEqual(item.resource_limits["max_ops"], 8)
        receipt = build_shadow_receipt(
            item,
            app_identity="app.browser",
            pre_observation_digest=D,
            post_observation_digest=E,
            capability_ids=("cap.observe",),
        )
        self.assertEqual(receipt.outcome, "shadow")
        self.assertFalse(receipt.executed)
        self.assertFalse(receipt.effect_committed)
        self.assertEqual(receipt.authority, DENY_ALL)

    def test_digest_is_canonical_and_stable(self):
        first = ir(op(1)).digest
        second = ir(op(1)).digest
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    def test_raw_bytes_are_rejected(self):
        with self.assertRaises(ValueError):
            op(args={"payload": b"native-code"})

    def test_pointer_and_machine_code_keys_are_rejected(self):
        for key in ("raw_pointer", "syscall", "machine_code", "ptx", "opcode"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                op(args={key: "1"})

    def test_shadow_evidence_rejects_execution_claims(self):
        with self.assertRaises(ValueError):
            compile_shadow_candidate(
                ir(op(1)),
                candidate_id="candidate.evidence",
                capability_manifest_digest=D,
                authorization_version="auth.v3",
                backend="wasm_aot",
                target="cpu",
                evidence={"lane": "synthetic", "executed": True},
            )

    def test_unknown_operation_is_rejected(self):
        with self.assertRaises(ValueError):
            op(name="run_native_code")

    def test_action_ir_cannot_carry_authority_or_effect(self):
        with self.assertRaises(ValueError):
            ir(op(1), authority="ALLOW")
        with self.assertRaises(ValueError):
            ir(op(1), physical_effect=True)

    def test_idempotency_keys_must_be_unique(self):
        with self.assertRaises(ValueError):
            ir(op(1), op(1, name="assert"))

    def test_operation_capabilities_must_be_declared(self):
        with self.assertRaises(ValueError):
            ir(op(1, args={}, name="observe_ax"), required_capabilities=())

    def test_limits_are_bounded_and_positive(self):
        with self.assertRaises(ValueError):
            ir(op(1), max_ops=0)
        with self.assertRaises(ValueError):
            ir(op(1), deadline_ms=0)
        with self.assertRaises(ValueError):
            ir(op(1), max_memory_bytes=0)
        with self.assertRaises(ValueError):
            ir(*[op(i) for i in range(1, 10)])

    def test_candidate_is_shadow_only(self):
        item = candidate(ir(op(1)))
        with self.assertRaises(ValueError):
            type(item)(**{**item.__dict__, "production_activation": True})
        with self.assertRaises(ValueError):
            type(item)(**{**item.__dict__, "authority": "ALLOW"})

    def test_receipt_cannot_claim_execution_or_effect(self):
        item = candidate(ir(op(1)))
        base = dict(
            candidate_id=item.candidate_id,
            action_ir_digest=item.action_ir_digest,
            artifact_digest=item.artifact_digest,
            app_identity="app.browser",
            body_generation=item.body_generation,
            revocation_epoch=item.revocation_epoch,
            capability_ids=(),
            pre_observation_digest=D,
            post_observation_digest=E,
            outcome="shadow",
            cpu_ns=1,
            gpu_ns=0,
            bytes_touched=0,
        )
        with self.assertRaises(ValueError):
            FastPathRuntimeReceiptV1(**{**base, "executed": True})
        with self.assertRaises(ValueError):
            FastPathRuntimeReceiptV1(**{**base, "effect_committed": True})

    def test_receipt_app_identity_is_bound_to_candidate(self):
        item = candidate(ir(op(1)))
        with self.assertRaises(ValueError):
            build_shadow_receipt(
                item,
                app_identity="app.other",
                pre_observation_digest=D,
                post_observation_digest=E,
            )

    def test_candidate_cache_key_changes_with_backend(self):
        program = ir(op(1))
        wasm = candidate(program)
        cuda = compile_shadow_candidate(
            program,
            candidate_id="candidate.reflex.cuda",
            capability_manifest_digest=D,
            authorization_version="auth.v3",
            backend="cuda_graph",
            target="gpu",
            evidence={"lane": "synthetic", "source": "contract-test"},
        )
        self.assertNotEqual(wasm.artifact_digest, cuda.artifact_digest)


if __name__ == "__main__":
    unittest.main()
