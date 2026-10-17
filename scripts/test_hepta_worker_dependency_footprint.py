"""Guard against fabricated graph savings or counting dev-only dependencies."""
import unittest
from scripts.hepta_worker_dependency_footprint import report

def fixture():
    return {
        "packages": [
            {"id": key, "name": name}
            for key, name in [
                ("w", "codex-hepta-infer-worker-host"),
                ("a", "codex-hepta-agentd"),
                ("s", "shared-runtime"),
                ("h", "heavy-agentd-host"),
                ("d", "dev-only"),
            ]
        ],
        "workspace_members": ["w", "a"],
        "resolve": {"nodes": [
            {"id": "w", "deps": [
                {"pkg": "a", "dep_kinds": [{"kind": None}]},
                {"pkg": "s", "dep_kinds": [{"kind": "normal"}]},
                {"pkg": "d", "dep_kinds": [{"kind": "dev"}]},
            ]},
            {"id": "a", "deps": [
                {"pkg": "s", "dep_kinds": [{"kind": None}]},
                {"pkg": "h", "dep_kinds": [{"kind": "build"}]},
            ]},
            {"id": "s", "deps": []},
            {"id": "h", "deps": []},
            {"id": "d", "deps": []},
        ]},
    }

class FootprintTests(unittest.TestCase):
    def test_direct_edge_exclusion_is_not_recursive_deletion(self):
        result = report(fixture())
        self.assertEqual(result["current"]["packages"], 4)
        self.assertEqual(result["without_direct_agentd_edge"]["packages"], 2)
        self.assertEqual(result["edge_only"]["package_names_sample"],
                         ["codex-hepta-agentd", "heavy-agentd-host"])
    def test_no_edge_means_no_savings(self):
        data = fixture()
        data["resolve"]["nodes"][0]["deps"] = data["resolve"]["nodes"][0]["deps"][1:]
        result = report(data)
        self.assertFalse(result["direct_agentd_dependency"])
        self.assertEqual(result["edge_only"]["packages"], 0)
    def test_malformed_metadata_fails_closed(self):
        data = fixture()
        data["resolve"]["nodes"][0]["deps"][0]["pkg"] = "unknown"
        with self.assertRaises(ValueError):
            report(data)
        with self.assertRaises(ValueError):
            report({"packages": []})

    def test_missing_dependency_kind_fails_closed(self):
        data = fixture()
        del data["resolve"]["nodes"][0]["deps"][0]["dep_kinds"]
        with self.assertRaises(ValueError):
            report(data)

if __name__ == "__main__":
    unittest.main()
