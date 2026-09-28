import unittest
from cognitive_read_consumers import CONSUMERS, PORT_PREFIX, safe_path, verify_registered


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


if __name__ == "__main__":
    unittest.main()
