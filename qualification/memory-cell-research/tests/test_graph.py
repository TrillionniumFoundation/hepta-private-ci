import unittest

from memory_cells.graph import (
    CellEdge,
    CellNode,
    CellRead,
    CellUnavailable,
    TypedGraph,
)


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.nodes = (
            CellNode("e", "episodic", "entity", "concept", "project", "e:1"),
            CellNode("s", "semantic", "concept", "procedure", "project", "s:1"),
            CellNode("p", "procedural", "procedure", "answer", "project", "p:1"),
        )
        self.graph = TypedGraph(
            self.nodes, (CellEdge("e", "s", "supports"), CellEdge("s", "p", "requires"))
        )
        self.calls = []

    def read(self, cell, key):
        self.calls.append((cell, key))
        return CellRead(
            {("e", "request"): "7", ("s", "7"): "12", ("p", "12"): "23"}[(cell, key)],
            0.9,
        )

    def test_only_cell_outputs_become_next_inputs(self):
        result = self.graph.run(
            "e", "request", self.read, scope="project", output_type="answer"
        )
        self.assertEqual((result.value, result.calls, result.abstain), ("23", 3, None))
        self.assertEqual(self.calls, [("e", "request"), ("s", "7"), ("p", "12")])
        self.assertEqual(tuple(t.cell_id for t in result.trace), ("e", "s", "p"))
        self.assertNotIn("request", repr(result.trace))

    def test_removed_edges_prevent_composition(self):
        result = self.graph.no_edges().run(
            "e", "request", self.read, scope="project", output_type="answer"
        )
        self.assertEqual(
            (result.value, result.calls, result.abstain), (None, 1, "missing_edge")
        )
        self.assertEqual(self.calls, [("e", "request")])

    def test_scope_and_artifact_checks_run_before_cell(self):
        scoped = self.graph.run(
            "e", "request", self.read, scope="other", output_type="answer"
        )
        revoked = self.graph.run(
            "e",
            "request",
            self.read,
            scope="project",
            output_type="answer",
            eligible=lambda _: False,
        )
        self.assertEqual(
            (scoped.abstain, revoked.abstain, self.calls),
            ("scope_mismatch", "artifact_unavailable", []),
        )

    def test_unavailable_reader_attempt_is_counted(self):
        def unavailable(cell, key):
            raise CellUnavailable("current owner revoked artifact")

        result = self.graph.run(
            "e", "request", unavailable, scope="project", output_type="answer"
        )
        self.assertEqual(
            (result.calls, result.trace, result.abstain),
            (1, (), "artifact_unavailable"),
        )

    def test_low_confidence_stops_later_calls(self):
        result = self.graph.run(
            "e",
            "request",
            self.read,
            scope="project",
            output_type="answer",
            min_confidence=0.95,
        )
        self.assertEqual(
            (result.calls, result.abstain, self.calls),
            (1, "cell_abstained", [("e", "request")]),
        )

    def test_type_mismatch_rejected_before_execution(self):
        with self.assertRaisesRegex(ValueError, "type or scope"):
            TypedGraph(self.nodes, (CellEdge("e", "p", "invalid"),))

    def test_cycle_and_step_budget(self):
        node = CellNode("loop", "predictive", "state", "state", "project", "loop:1")
        graph = TypedGraph((node,), (CellEdge("loop", "loop", "next"),), max_steps=2)
        cycle = graph.run(
            "loop",
            "x",
            lambda _, value: CellRead(value, 1.0),
            scope="project",
            output_type="answer",
        )
        budget = graph.run(
            "loop",
            "x",
            lambda _, value: CellRead(value + "x", 1.0),
            scope="project",
            output_type="answer",
        )
        self.assertEqual(
            (cycle.abstain, cycle.calls, budget.abstain, budget.calls),
            ("cycle", 1, "step_budget", 2),
        )

    def test_shuffle_changes_association_without_breaking_type(self):
        nodes = (
            CellNode("a", "episodic", "entity", "concept", "p", "a:1"),
            CellNode("b", "episodic", "entity", "concept", "p", "b:1"),
            CellNode("x", "semantic", "concept", "answer", "p", "x:1"),
            CellNode("y", "semantic", "concept", "answer", "p", "y:1"),
        )
        graph = TypedGraph(
            nodes, (CellEdge("a", "x", "supports"), CellEdge("b", "y", "supports"))
        )

        def read(cell, key):
            return CellRead(
                "4" if cell in {"a", "b"} else {"x": "8", "y": "9"}[cell], 1.0
            )

        intact = graph.run("a", "query", read, scope="p", output_type="answer")
        shuffled = graph.shuffled_edges(2).run(
            "a", "query", read, scope="p", output_type="answer"
        )
        self.assertEqual(
            (intact.value, shuffled.value, intact.calls, shuffled.calls),
            ("8", "9", 2, 2),
        )


if __name__ == "__main__":
    unittest.main()
