import unittest
from cognitive_read_consumers import CONSUMERS, PORT_PREFIX, safe_path, verify_registered, mapped_tests


class ConsumerRegistryTests(unittest.TestCase):
    def registry(self):
        return {"contracts": [{"id": PORT_PREFIX + item} for item in CONSUMERS]}

    def test_exact_registry(self):
        verify_registered(self.registry())

    def test_missing_consumer_rejected(self):
        registry = self.registry()
        registry["contracts"].pop()
        with self.assertRaises(ValueError):
            verify_registered(registry)

    def test_unreviewed_consumer_rejected(self):
        registry = self.registry()
        registry["contracts"].append({"id": PORT_PREFIX + "unexpected.consumer"})
        with self.assertRaises(ValueError):
            verify_registered(registry)

    def test_escape_paths_rejected(self):
        for path in ("../owner", "/owner", "source/../../owner", "source\\owner", ""):
            with self.subTest(path=path), self.assertRaises(ValueError):
                safe_path(path)


class ConsumerTestReferenceTests(unittest.TestCase):
    def test_path_and_symbol_references_are_preserved(self):
        mapping = {"operations": [{"tests": ["src/a.rs", {"path": "src/b.rs", "symbol": "reject_stale"}]}]}
        rows = mapped_tests(mapping, {"src/a.rs": "a" * 40, "src/b.rs": "b" * 40})
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["present"] for row in rows))
        self.assertTrue(any(row["symbol"] == "reject_stale" for row in rows))

    def test_missing_source_is_reported_not_dropped(self):
        rows = mapped_tests({"operations": [{"tests": [{"path": "missing.rs", "symbol": "test"}]}]}, {})
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["present"])
        self.assertIsNone(rows[0]["blob"])

    def test_object_reference_cannot_escape_repository(self):
        with self.assertRaises(ValueError):
            mapped_tests({"operations": [{"tests": [{"path": "../secret"}]}]}, {})


if __name__ == "__main__":
    unittest.main()
