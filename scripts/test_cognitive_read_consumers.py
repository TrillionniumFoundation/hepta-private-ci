import unittest

from cognitive_read_consumers import (
    AUDIT_SCHEMA,
    CONSUMERS,
    MIGRATION_CLASSES,
    POLICY_SCHEMA,
    PORT_PREFIX,
    mapped_product_callers,
    mapped_tests,
    policy_by_consumer,
    safe_path,
    selected_claim_flags,
    verify_registered,
)


def valid_policy():
    rows = []
    for index, consumer in enumerate(CONSUMERS):
        rows.append(
            {
                "consumer": consumer,
                "expectedProductCallerState": f"state-{index}",
                "minimumMappedProductCallers": 0,
                "migrationClass": sorted(MIGRATION_CLASSES)[index],
                "adoptedReadBoundary": "typed-local",
                "finalUseResponsibility": "existing owner",
                "errorMappingRequirement": "typed errors",
                "requiredExecutionEvidence": ["normal product path"],
            }
        )
    return {"schema": POLICY_SCHEMA, "consumers": rows}


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


class ConsumerPolicyTests(unittest.TestCase):
    def test_closed_policy_is_accepted(self):
        policies = policy_by_consumer(valid_policy())
        self.assertEqual(set(policies), set(CONSUMERS))

    def test_missing_or_duplicate_policy_consumer_is_rejected(self):
        for mutation in ("missing", "duplicate"):
            value = valid_policy()
            if mutation == "missing":
                value["consumers"].pop()
            else:
                value["consumers"].append(dict(value["consumers"][0]))
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                policy_by_consumer(value)

    def test_policy_requires_reviewed_migration_class_and_evidence(self):
        value = valid_policy()
        value["consumers"][0]["migrationClass"] = "invented"
        with self.assertRaises(ValueError):
            policy_by_consumer(value)
        value = valid_policy()
        value["consumers"][0]["requiredExecutionEvidence"] = []
        with self.assertRaises(ValueError):
            policy_by_consumer(value)

    def test_schema_is_versioned(self):
        self.assertEqual(AUDIT_SCHEMA, "hepta.cognitive.read.consumer-audit.v2")


class ConsumerTestReferenceTests(unittest.TestCase):
    def test_path_and_symbol_references_are_preserved(self):
        mapping = {
            "operations": [
                {
                    "tests": [
                        "src/a.rs",
                        {"path": "src/b.rs", "symbol": "reject_stale"},
                    ]
                }
            ]
        }
        rows = mapped_tests(
            mapping,
            {"src/a.rs": "a" * 40, "src/b.rs": "b" * 40},
        )
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["present"] for row in rows))
        self.assertTrue(any(row["symbol"] == "reject_stale" for row in rows))

    def test_missing_source_is_reported_not_dropped(self):
        rows = mapped_tests(
            {
                "operations": [
                    {"tests": [{"path": "missing.rs", "symbol": "test"}]}
                ]
            },
            {},
        )
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["present"])
        self.assertIsNone(rows[0]["blob"])

    def test_object_reference_cannot_escape_repository(self):
        with self.assertRaises(ValueError):
            mapped_tests(
                {"operations": [{"tests": [{"path": "../secret"}]}]},
                {},
            )


class ConsumerProductCallerTests(unittest.TestCase):
    def test_callers_bind_exact_file_blob_and_symbol(self):
        mapping = {
            "productCallers": [
                {
                    "sourcePath": "src/product.rs",
                    "nativeSymbol": "normal_entry",
                    "state": "source_composed",
                }
            ]
        }
        rows = mapped_product_callers(
            mapping,
            {"src/product.rs": "a" * 40},
            lambda _: "fn normal_entry() {}",
        )
        self.assertEqual(
            rows,
            [
                {
                    "path": "src/product.rs",
                    "blob": "a" * 40,
                    "symbol": "normal_entry",
                    "state": "source_composed",
                    "present": True,
                    "symbol_present": True,
                }
            ],
        )

    def test_missing_symbol_is_explicit(self):
        rows = mapped_product_callers(
            {
                "productCallers": [
                    {
                        "sourcePath": "src/product.rs",
                        "nativeSymbol": "missing",
                    }
                ]
            },
            {"src/product.rs": "a" * 40},
            lambda _: "fn other() {}",
        )
        self.assertFalse(rows[0]["symbol_present"])

    def test_claim_flags_do_not_promote_unrelated_booleans(self):
        flags = selected_claim_flags(
            {
                "claimBoundary": {
                    "productExecutionProved": False,
                    "requestLocalReadOnlyProductExecutionProved": True,
                    "activation": False,
                    "sourceRootPresent": True,
                }
            }
        )
        self.assertEqual(
            flags,
            {
                "activation": False,
                "productExecutionProved": False,
                "requestLocalReadOnlyProductExecutionProved": True,
            },
        )


if __name__ == "__main__":
    unittest.main()
