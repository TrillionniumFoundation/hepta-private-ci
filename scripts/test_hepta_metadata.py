import unittest

from hepta_metadata import AUTHORITY_KEYS, authority_fixture, has_schema_version


class SharedMetadataTests(unittest.TestCase):
    def test_authority_fixture_is_canonical_deny_all(self):
        fixture = authority_fixture()
        self.assertEqual(list(fixture), AUTHORITY_KEYS)
        self.assertTrue(fixture)
        self.assertTrue(all(value is False for value in fixture.values()))

    def test_schema_version_check_is_shape_safe(self):
        self.assertTrue(has_schema_version({"schemaVersion": 3}, 3))
        self.assertFalse(has_schema_version({"schemaVersion": "3"}, 3))
        self.assertFalse(has_schema_version(None, 3))


if __name__ == "__main__":
    unittest.main()
