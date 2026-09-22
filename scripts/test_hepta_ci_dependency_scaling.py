"""Selection behavior on long chains, mixed edges and changing exact graphs.

No wall-clock threshold is used as a merge gate.
"""
import unittest

from hepta_ci_dependencies import Graph, select_packages


class SelectionScalingTests(unittest.TestCase):
    def graph(self, names, edges):
        return Graph({f"codex-rs/{n}": n for n in names}, frozenset(edges))

    def test_large_chain_is_fully_selected(self):
        names = [f"p{i}" for i in range(5000)]
        edges = [(names[i], names[i + 1], False) for i in range(len(names) - 1)]
        graph = self.graph(names, edges)
        selected = select_packages(["codex-rs/p0/src/lib.rs"], graph, graph)
        self.assertEqual(selected["packages"], sorted(names))
        self.assertFalse(selected["full_workspace"])

    def test_dev_edges_do_not_propagate_to_downstream_production(self):
        graph = self.graph(
            ["helper", "consumer", "app"],
            [("helper", "consumer", True), ("consumer", "app", False)],
        )
        selected = select_packages(["codex-rs/helper/src/lib.rs"], graph, graph)
        self.assertEqual(selected["packages"], ["consumer", "helper"])

    def test_both_dev_and_production_edge_still_propagate(self):
        graph = self.graph(
            ["helper", "consumer", "app"],
            [("helper", "consumer", True), ("helper", "consumer", False),
             ("consumer", "app", False)],
        )
        selected = select_packages(["codex-rs/helper/src/lib.rs"], graph, graph)
        self.assertEqual(selected["packages"], ["app", "consumer", "helper"])

    def test_cycle_is_bounded(self):
        graph = self.graph(["a", "b"], [("a", "b", False), ("b", "a", False)])
        selected = select_packages(["codex-rs/a/src/lib.rs"], graph, graph)
        self.assertEqual(selected["packages"], ["a", "b"])

    def test_old_edges_remain_relevant(self):
        before = self.graph(["a", "b"], [("a", "b", False)])
        after = self.graph(["a", "b"], [])
        selected = select_packages(["codex-rs/a/src/lib.rs"], before, after)
        self.assertEqual(selected["packages"], ["a", "b"])

    def test_new_edges_are_selected(self):
        before = self.graph(["a", "b"], [])
        after = self.graph(["a", "b"], [("a", "b", False)])
        selected = select_packages(["codex-rs/a/src/lib.rs"], before, after)
        self.assertEqual(selected["packages"], ["a", "b"])

    def test_unknown_and_shared_inputs_keep_full_fallback(self):
        graph = self.graph(["a", "b"], [])
        for path in ("unknown/file", "codex-rs/Cargo.lock", "scripts/test.py",
                     ".github/workflows/ci.yml"):
            with self.subTest(path=path):
                selected = select_packages([path], graph, graph)
                self.assertTrue(selected["full_workspace"])
                self.assertEqual(selected["packages"], ["a", "b"])

    def test_invalid_paths_are_rejected(self):
        graph = self.graph(["a"], [])
        for path in ("", "/etc/passwd", "codex-rs/a/../b", "a\\b", "a\0b"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                select_packages([path], graph, graph)

    def test_deleted_and_renamed_package_targets(self):
        before = Graph(
            {"codex-rs/a": "old", "codex-rs/b": "b"},
            frozenset({("old", "b", False)}),
        )
        after = Graph({"codex-rs/a": "new", "codex-rs/b": "b"}, frozenset())
        selected = select_packages(["codex-rs/a/src/lib.rs"], before, after)
        self.assertEqual(selected["packages"], ["b", "new"])
        self.assertEqual(selected["changed_packages"], ["new", "old"])


if __name__ == "__main__":
    unittest.main()
