"""Behavioral qualification for shared semantic providers and local training."""

from dataclasses import replace
import hashlib
import unittest

from hepta_cells.lifecycle import (
    Budget,
    CellError,
    CellOwner,
    Partition,
    Qualification,
    StepContext,
)
from hepta_cells.semantic_component import SemanticComponent, semantic_bundle

import numpy as np

from hepta_cells.semantic import (
    CallableFeatureBackend,
    FrozenDomainAdapter,
    LocalHead,
    LocalObjective,
    SemanticBinding,
    SemanticBudget,
    SemanticCell,
    SemanticTrainingError,
    SharedSemanticPool,
)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class SemanticTests(unittest.TestCase):
    def setUp(self):
        self.weights = np.array([[1.0, 0.0], [0.0, 1.0], [0.5, -0.5]])
        self.original = self.weights.copy()
        self.calls = []
        self.binding = SemanticBinding(
            hashlib.sha256(self.weights.tobytes()).hexdigest(),
            digest("model-v1"),
            digest("encoder-v1"),
            digest("tokenizer-v1"),
            digest("fp64-host-v1"),
        )
        self.backend = self.provider(self.binding)
        self.pool = SharedSemanticPool()
        self.pool.register_backend(self.backend)
        self.inputs = [
            np.array([1.0, 0.0, 0.0]),
            np.array([0.0, 1.0, 0.0]),
            np.array([1.0, 1.0, 0.0]),
            np.array([-1.0, 0.5, 0.0]),
        ]

    def provider(self, binding):
        def encode(inputs):
            self.calls.append((binding, len(inputs)))
            return np.stack(inputs) @ self.weights

        return CallableFeatureBackend(
            binding,
            2,
            encode,
            lambda: hashlib.sha256(self.weights.tobytes()).hexdigest(),
            resident_arrays=(self.weights,),
        )

    def cell(
        self, name="a", binding=None, output_dim=1, rank=None, budget=None, **kwargs
    ):
        return SemanticCell(
            name,
            binding or self.binding,
            LocalHead.initialize(2, output_dim, rank, seed=7),
            LocalObjective("mse", output_dim, "next-observation regression"),
            budget,
            **kwargs,
        )

    def test_real_gradient_training_returns_candidate_and_preserves_base_and_active_head(
        self,
    ):
        a, b = self.cell("a"), self.cell("b")
        before = a.digest
        initial, _ = self.pool.predict_batch([(a, self.inputs), (b, self.inputs)])
        targets = np.stack(self.inputs)[:, :2] @ np.array([[2.0], [-1.0]])
        candidate = self.pool.train_candidate(
            a, self.inputs, targets, steps=70, learning_rate=0.1
        )
        self.assertLess(candidate.loss_after, candidate.loss_before * 0.001)
        self.assertEqual(
            (
                candidate.cell_id,
                candidate.source_digest,
                candidate.binding,
                candidate.objective,
            ),
            ("a", before, a.binding, a.objective),
        )
        self.assertNotEqual(candidate.head.digest, a.head.digest)
        after, _ = self.pool.predict_batch([(a, self.inputs), (b, self.inputs)])
        np.testing.assert_array_equal(after, initial)
        np.testing.assert_array_equal(self.weights, self.original)
        self.assertEqual(a.digest, before)
        self.assertEqual(len(candidate.dataset_digest), 64)
        with self.assertRaises(ValueError):
            candidate.head.first.flags.writeable = True

    def test_low_rank_head_learns_and_both_factors_update(self):
        cell = self.cell(output_dim=2, rank=1)
        features = np.stack(self.inputs) @ self.weights
        target = features @ np.array([[1.0, -2.0], [1.0, -2.0]])
        candidate = self.pool.train_candidate(
            cell, self.inputs, target, steps=100, learning_rate=0.2
        )
        self.assertLess(candidate.loss_after, candidate.loss_before * 0.01)
        self.assertFalse(np.array_equal(candidate.head.first, cell.head.first))
        self.assertFalse(np.array_equal(candidate.head.second, cell.head.second))
        np.testing.assert_array_equal(self.weights, self.original)

    def test_cross_entropy_objective_learns_from_labels(self):
        cell = SemanticCell(
            "classifier",
            self.binding,
            LocalHead.initialize(2, 2),
            LocalObjective("cross_entropy", 2, "event class"),
        )
        candidate = self.pool.train_candidate(
            cell, self.inputs[:2], np.array([0, 1]), steps=60, learning_rate=0.2
        )
        self.assertLess(candidate.loss_after, candidate.loss_before * 0.15)
        predictions = candidate.head.predict(np.eye(2)).argmax(axis=1)
        np.testing.assert_array_equal(predictions, [0, 1])
        with self.assertRaises(ValueError):
            self.pool.train_candidate(cell, self.inputs[:2], np.array([0, 2]))

    def test_two_cells_share_backend_without_sharing_heads_state_views_or_budget(self):
        state, view = {"history": [1]}, [{"allowed": ["private-a"]}]
        a = self.cell("a", state=state, retrieval_view=view)
        b = self.cell("b", state=state, retrieval_view=view)
        state["history"].append(2)
        view[0]["allowed"].append("mutated")
        snapshot, retrieval = a.state, a.retrieval_view
        snapshot["history"].append(3)
        retrieval[0]["allowed"].append("returned-value mutation")
        a.set_state({"history": [4]})
        self.assertEqual(
            (a.state, b.state, a.retrieval_view, b.retrieval_view),
            (
                {"history": [4]},
                {"history": [1]},
                ({"allowed": ["private-a"]},),
                ({"allowed": ["private-a"]},),
            ),
        )
        self.assertFalse(np.shares_memory(a.head.first, b.head.first))
        self.pool.predict_batch([(a, self.inputs)])
        self.assertEqual((a.used_items, b.used_items), (4, 0))

    def test_batch_compatibility_covers_domain_and_encoder_and_preserves_order(self):
        adapter = FrozenDomainAdapter(self.binding, np.array([[2.0, 0.0], [0.0, 3.0]]))
        domain_binding = self.pool.register_domain(adapter)
        other_binding = replace(self.binding, encoder=digest("encoder-v2"))
        self.pool.register_backend(self.provider(other_binding))
        cells = [
            self.cell("a"),
            self.cell("d", binding=domain_binding),
            self.cell("e", binding=other_binding),
            self.cell("b"),
        ]
        cells = [
            SemanticCell(
                c.cell_id,
                c.binding,
                LocalHead(np.eye(2), np.zeros(2)),
                LocalObjective("mse", 2, "projected feature"),
            )
            for c in cells
        ]
        result, costs = self.pool.predict_batch(
            [(cell, [self.inputs[i]]) for i, cell in enumerate(cells)]
        )
        self.assertEqual(sorted(count for _, count in self.calls), [1, 1, 2])
        expected = [
            self.inputs[0] @ self.weights,
            self.inputs[1] @ self.weights @ adapter.matrix,
            self.inputs[2] @ self.weights,
            self.inputs[3] @ self.weights,
        ]
        for actual, value in zip(result, expected):
            np.testing.assert_allclose(actual, value[None])
        self.assertEqual(len(costs), 3)
        self.assertTrue(
            all(c["host_wall_ns"] >= 0 and not c["gpu_memory_measured"] for c in costs)
        )
        with self.assertRaises(ValueError):
            adapter.matrix[0, 0] = 3

    def test_every_binding_mismatch_is_rejected_before_encoding(self):
        for field in (
            "base",
            "model",
            "encoder",
            "tokenizer",
            "numeric_profile",
            "domain",
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.pool.predict_batch(
                    [
                        (
                            self.cell(
                                binding=replace(
                                    self.binding, **{field: digest("wrong")}
                                )
                            ),
                            self.inputs,
                        )
                    ]
                )
        self.assertEqual(self.calls, [])
        other = replace(self.binding, tokenizer=digest("other-tokenizer"))
        domain = FrozenDomainAdapter(other, np.eye(2))
        with self.assertRaises(ValueError):
            self.pool.register_domain(domain)
        for invalid in ("0" * 64, "abc", "A" * 64):
            with self.assertRaises(ValueError):
                replace(self.binding, encoder=invalid)

    def test_budget_rejections_happen_before_any_encode_and_are_cell_local(self):
        for budget in (
            SemanticBudget(max_items=1),
            SemanticBudget(max_input_bytes=1),
            SemanticBudget(max_working_bytes=1),
            SemanticBudget(max_total_items=1),
        ):
            a, b = self.cell("a"), self.cell("b", budget=budget)
            with self.assertRaises(ValueError):
                self.pool.predict_batch([(a, self.inputs), (b, self.inputs)])
            self.assertEqual((a.used_items, b.used_items, self.calls), (0, 0, []))
        cell = self.cell(budget=SemanticBudget(max_train_steps=1))
        with self.assertRaises(ValueError):
            self.pool.train_candidate(cell, self.inputs, np.zeros((4, 1)), steps=2)
        self.assertEqual((cell.used_items, self.calls), (0, []))
        cell = self.cell(budget=SemanticBudget(max_total_items=4))
        self.pool.predict_batch([(cell, self.inputs)])
        with self.assertRaises(ValueError):
            self.pool.predict_batch([(cell, self.inputs)])
        self.assertEqual(len(self.calls), 1)
        with self.assertRaises(ValueError):
            self.pool.predict_batch(
                [(cell, [self.inputs[0]]), (cell, [self.inputs[1]])]
            )

    def test_base_mutation_and_provider_shape_fail_closed(self):
        cell = self.cell()
        self.weights[0, 0] += 1
        with self.assertRaises(ValueError):
            self.pool.train_candidate(cell, self.inputs, np.zeros((4, 1)))
        self.assertEqual(self.calls, [])
        np.testing.assert_array_equal(cell.head.first, np.zeros((2, 1)))
        self.assertEqual(cell.used_items, 4)
        wrong = CallableFeatureBackend(
            self.binding,
            2,
            lambda rows: np.zeros((len(rows), 3)),
            lambda: self.binding.base,
        )
        pool = SharedSemanticPool()
        pool.register_backend(wrong)
        with self.assertRaises(ValueError):
            pool.predict_batch([(self.cell(), self.inputs)])

    def test_memory_counts_actual_shared_arrays_once_across_encoders_and_cells(self):
        other = replace(self.binding, encoder=digest("encoder-v2"))
        self.pool.register_backend(self.provider(other))
        adapter = FrozenDomainAdapter(self.binding, np.eye(2))
        domain = self.pool.register_domain(adapter)
        a, b, c = (
            self.cell("a"),
            self.cell("b", binding=other),
            self.cell("c", binding=domain),
        )
        report = self.pool.memory_report([a, b, c, a])
        self.assertEqual(
            (report["shared_array_bytes"], report["private_head_array_bytes"]),
            (self.weights.nbytes + adapter.matrix.nbytes, 3 * (2 + 1) * 8),
        )
        self.assertEqual(
            (
                report["backend_count"],
                report["domain_count"],
                report["unmeasured_backend_count"],
            ),
            (2, 1, 0),
        )
        self.assertEqual(
            report["measurement_kind"], "observed_host_array_storage_bytes"
        )
        self.assertFalse(
            report["gpu_memory_measured"] or report["includes_python_overhead"]
        )

    def test_shared_batch_global_limits_reject_before_any_call(self):
        for limits in (
            {"max_batch_cells": 1},
            {"max_batch_items": 1},
            {"max_batch_input_bytes": 30},
            {"max_batch_working_bytes": 200},
        ):
            pool = SharedSemanticPool(**limits)
            pool.register_backend(self.backend)
            a, b = self.cell("a"), self.cell("b")
            with self.subTest(limits=limits), self.assertRaises(ValueError):
                pool.predict_batch([(a, self.inputs[:1]), (b, self.inputs[:1])])
            self.assertEqual((a.used_items, b.used_items, self.calls), (0, 0, []))
        with self.assertRaises(ValueError):
            self.pool.predict_batch(
                (self.cell(str(i)), self.inputs[:1]) for i in range(100000)
            )
        self.assertEqual(self.calls, [])

    def test_training_receipts_retain_real_host_costs_on_success_and_failure(self):
        cell = self.cell()
        candidate = self.pool.train_candidate(
            cell, self.inputs, np.ones((4, 1)), steps=3
        )
        receipt = candidate.training_receipt
        self.assertEqual(
            (receipt["status"], receipt["completed_steps"]), ("completed", 3)
        )
        self.assertGreaterEqual(receipt["host_wall_seconds"], 0)
        self.assertGreaterEqual(receipt["process_cpu_seconds"], 0)
        self.assertEqual(
            [
                receipt[k]
                for k in ("energy_joules", "peak_ram_bytes", "peak_vram_bytes")
            ],
            [None] * 3,
        )
        with self.assertRaises(SemanticTrainingError) as failed:
            self.pool.train_candidate(cell, self.inputs, np.ones((3, 1)))
        self.assertEqual(
            (
                failed.exception.receipt["status"],
                failed.exception.receipt["completed_steps"],
            ),
            ("failed", 0),
        )
        self.assertGreaterEqual(failed.exception.receipt["host_wall_seconds"], 0)
        self.assertGreaterEqual(failed.exception.receipt["process_cpu_seconds"], 0)

    def test_semantic_component_uses_real_bundle_and_durable_owner_candidate_lifecycle(
        self,
    ):
        cell = self.cell()
        bundle = semantic_bundle(cell, "semantic-a")
        component = SemanticComponent(self.pool, cell, bundle)
        partition = Partition("principal", "agent", "a", "run")
        evaluation = digest("fixture-evaluation-only")
        owner = CellOwner(
            ":memory:", qualify=lambda q: q.evaluation_digest == evaluation
        )
        try:
            owner.create(partition, component, retrieval_view={"private": ["scope-a"]})
            payload = {"inputs": [v.tolist() for v in self.inputs]}
            first = owner.step(partition, component, "predict-1", payload)
            self.assertEqual(
                first, owner.step(partition, component, "predict-1", payload)
            )
            self.assertEqual(len(self.calls), 1)
            checkpoint = owner.checkpoint(partition)
            self.assertEqual(
                (checkpoint["state"]["steps"], checkpoint["state"]["observations"]),
                (1, 4),
            )
            self.assertEqual(checkpoint["retrieval_view"], {"private": ["scope-a"]})
            proposed, training = component.propose(
                self.inputs,
                np.ones((4, 1)),
                artifact_id="semantic-a-candidate",
                evaluation_profile=evaluation,
                steps=5,
            )
            self.assertEqual(
                training.training_receipt["source_bundle_digest"], bundle.digest()
            )
            self.assertEqual(
                owner.checkpoint(partition)["identity"]["bundle_digest"],
                component.identity.bundle_digest,
            )
            qualified = Qualification(
                component.identity.digest, proposed.identity.digest, evaluation
            )
            adopted = owner.adopt(partition, proposed, qualified)
            self.assertEqual(adopted["state"], proposed.initial_state())
            current = owner.step(partition, proposed, "predict-after-adoption", payload)
            self.assertNotEqual(first["output"]["logits"], current["output"]["logits"])
            owner.rollback(partition, component, proposed.identity.digest)
            self.assertEqual(
                owner.checkpoint(partition)["state"], component.initial_state()
            )
            self.assertEqual(cell.used_items, 0)
        finally:
            owner.close()

    def test_component_rejects_binding_owner_and_work_budget_before_provider(self):
        cell = self.cell()
        bundle = semantic_bundle(cell, "semantic-a")
        component = SemanticComponent(self.pool, cell, bundle)
        for name in bundle.components:
            changed = dict(bundle.components, **{name: digest("wrong")})
            with self.subTest(component=name), self.assertRaises(CellError):
                SemanticComponent(self.pool, cell, replace(bundle, components=changed))
        partition = Partition("p", "a", "a", "r")
        context = StepContext(
            partition, "request", component.identity, None, Budget(max_work_units=1)
        )
        with self.assertRaises(CellError):
            component.step(
                {"inputs": [self.inputs[0].tolist()]},
                component.initial_state(),
                context,
            )
        with self.assertRaises(CellError):
            component.step(
                {"inputs": [self.inputs[0].tolist()]},
                component.initial_state(),
                replace(
                    context,
                    partition=replace(partition, cell_id="foreign"),
                    budget=Budget(),
                ),
            )
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
