"""Structured novelty, actual feedback learning, and source-bound task reads."""

import json
from pathlib import Path
import tempfile
import unittest

from v6.store import EventStore
from v6.transfer import FeedbackRouter, TaskExpert, TypedTaskCompiler, run_transfer_study


def leaf(kind, entity="sensor-a", at=2):
    return {"op": "read", "kind": kind, "entity": entity, "at": at}


def apply(entity="sensor-a", at=2, version=2):
    return {
        "op": "apply",
        "inputs": [leaf("procedure", entity, version), leaf("event", entity, at), leaf("semantic", entity)],
    }


class TransferTests(unittest.TestCase):
    def test_compiler_infers_types_deduplicates_and_rejects_invalid_graphs(self):
        compiler = TypedTaskCompiler()
        expression = {"op": "sum", "inputs": [apply(), apply()]}
        graph = compiler.compile(expression)
        self.assertEqual(len(graph["nodes"]), 5)
        self.assertEqual(graph["nodes"][-1]["inputs"], [3, 3])
        other = compiler.compile({"op": "sum", "inputs": [apply("different-domain"), apply("different-domain")]})
        self.assertEqual((graph["shape"], graph["features"]), (other["shape"], other["features"]))
        invalid = apply()
        invalid["inputs"][0] = leaf("semantic")
        with self.assertRaisesRegex(ValueError, "type mismatch"):
            compiler.compile(invalid)
        with self.assertRaisesRegex(ValueError, "node budget"):
            compiler.compile(expression, maximum_nodes=4)
        with self.assertRaisesRegex(ValueError, "unregistered"):
            compiler.compile({"op": "invent_program", "inputs": []})

    def test_expert_reload_reads_parameters_and_revocation_invalidates_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            source = EventStore(Path(directory) / "source.sqlite")
            try:
                supports = {}
                for i in range(4):
                    entity = f"sensor-{i}"
                    supports[entity] = []
                    for kind, at, value in [
                        ("event", 1, i + 2),
                        ("event", 2, i + 5),
                        ("semantic", 2, {"factor": i + 2, "label": f"label-{i}"}),
                        ("procedure", 1, {"opcode": "add_bias", "bias": i + 1, "limit": 20}),
                        ("procedure", 2, {"opcode": "affine", "bias": i + 1, "limit": 20}),
                    ]:
                        identity = source.append(
                            scope="scope",
                            entity=entity,
                            kind=kind,
                            effective_at=at,
                            value=value,
                            origin_id=f"{entity}-{kind}-{at}",
                        )
                        supports[entity].append(identity)
                expert = TaskExpert.from_bytes(TaskExpert.fit(source, "scope", "general", seed=131).to_bytes())
                graph = TypedTaskCompiler().compile(apply("sensor-3", at=1))
                original = source.resolve

                def event_only(scope, entity, kind, **kwargs):
                    self.assertEqual(kind, "event", "parameter serving must not read source answer payloads")
                    return original(scope, entity, kind, **kwargs)

                source.resolve = event_only
                result = expert.execute(graph, source)
                self.assertEqual(result["value"], (3 + 2) * (3 + 2) + 4)
                self.assertEqual(set(result["support_ids"]), {supports["sensor-3"][i] for i in (0, 2, 4)})
                self.assertTrue(result["parameter_digests"])
                limited = expert.execute(graph, source, maximum_work=1)
                self.assertIsNone(limited["value"])
                self.assertIn("budget", limited["abstain"])
                self.assertLessEqual(limited["work_proxy"], 1)
                source.revoke(supports["sensor-3"][0], "development revocation")
                self.assertIn("cut", expert.execute(graph, source)["abstain"])
            finally:
                source.close()

    def test_feedback_allocates_unseen_combinations_without_refitting_router(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "development"
            report = run_transfer_study(137, output)
            self.assertTrue(report["router_unchanged_after_new_domain"])
            self.assertFalse(report["test_feedback_used_for_routing"])
            self.assertFalse(report["new_natural_language_intents_supported"])
            for population in ("old_domain_new_combinations", "new_domain_new_combinations"):
                self.assertFalse(set(report["selection_shapes"]) & set(report["test_shapes"][population]))
                stats = report["populations"][population]
                self.assertEqual(stats["general"]["correct"], stats["general"]["rows"])
                self.assertGreater(stats["learned"]["correct"], 0)
                self.assertGreater(len(stats["learned"]["assignments"]), 1)
            router = FeedbackRouter.from_bytes((output / "router.json").read_bytes())
            graph = TypedTaskCompiler().compile(apply())
            before = router.choose(graph)
            router.weights.fill(0)
            forced = next(name for name in router.names if name != before)
            router.weights[0, router.names.index(forced)] = -100
            self.assertEqual(router.choose(graph), forced)
            manifest = json.loads((output / "MANIFEST.json").read_bytes())
            self.assertEqual(
                set(manifest["files"]), {path.name for path in output.iterdir() if path.name != "MANIFEST.json"}
            )


if __name__ == "__main__":
    unittest.main()
