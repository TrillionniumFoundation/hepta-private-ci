from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from memory_cells.data import (
    active_events,
    exact_store_predict,
    from_module_registry,
    lexical_retrieval_predict,
    make_associative,
    make_composition,
    make_continual,
    slot_key,
)


class DataTests(unittest.TestCase):
    def test_reproducible_independent_associations(self):
        first = make_associative(1729, (6, 7), 16)
        self.assertEqual(first, make_associative(1729, (6, 7), 16))
        second = make_associative(1730, (6, 7), 16)
        self.assertNotEqual(first.events, second.events)
        self.assertEqual(len({event.key for event in first.events}), len(first.events))
        for query in first.train + first.selection + first.test:
            self.assertNotRegex(query.text, r"\d")
            self.assertIn(query.key, query.text)

    def test_query_splits_share_writes_but_not_query_wording(self):
        data = make_associative(4, (4,), 8)
        split_texts = [
            set(query.text for query in split)
            for split in (data.train, data.selection, data.test)
        ]
        for left in range(len(split_texts)):
            for right in range(left):
                self.assertFalse(split_texts[left] & split_texts[right])
        expected_sources = {event.record_id for event in data.events}
        self.assertEqual(
            {query.source_record_id for query in data.test}, expected_sources
        )
        self.assertEqual(len({query.query_id for query in data.test}), len(data.test))

    def test_explicit_memory_baselines_are_strong(self):
        data = make_associative(91, (8, 8), 16)
        expected = [query.target for query in data.test]
        self.assertEqual(exact_store_predict(data.events, data.test), expected)
        self.assertEqual(lexical_retrieval_predict(data.events, data.test), expected)

    def test_correction_deletion_and_retention_use_current_heads(self):
        base = make_associative(92, (12, 12), 16)
        stream = make_continual(base, 18, additions=4, corrections=5, deletions=3)
        current = stream["current"]
        expected = [query.target for query in current.test]
        self.assertEqual(exact_store_predict(stream["history"], current.test), expected)
        self.assertEqual(
            lexical_retrieval_predict(stream["history"], current.test), expected
        )
        deleted = stream["deleted_queries"]
        self.assertEqual(
            exact_store_predict(stream["history"], deleted), [None] * len(deleted)
        )
        self.assertEqual(
            lexical_retrieval_predict(stream["history"], deleted), [None] * len(deleted)
        )
        old = {event.record_id: event for event in base.events}
        for event in stream["corrections"]:
            self.assertNotEqual(event.value, old[event.record_id].value)
        self.assertTrue(
            {event.record_id for event in stream["retained"].events}.isdisjoint(
                {
                    event.record_id
                    for event in stream["corrections"] + stream["deletions"]
                }
            )
        )
        event = base.events[0]
        with self.assertRaisesRegex(ValueError, "conflicting"):
            active_events((event, replace(event, value=(event.value + 1) % 16)))

    def test_composition_requires_both_maps(self):
        graph = make_composition(99, 12, 16)
        first = {event.key: event.value for event in graph["first"].events}
        second = {event.key: event.value for event in graph["second"].events}
        reconstructed = [
            second[slot_key(first[query.key])] for query in graph["queries"]
        ]
        self.assertEqual(reconstructed, [query.target for query in graph["queries"]])
        self.assertEqual(
            len({query.text for query in graph["queries"]}), len(graph["queries"])
        )
        self.assertFalse(graph["metadata"]["learned_topology"])

    def test_registry_identity_and_label_catalog_are_accounted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            raw = json.dumps(
                {
                    "modules": [
                        {"id": "alpha.reader", "owner": "research-a"},
                        {"id": "beta.writer", "owner": "research-b"},
                        {"id": "gamma.reader", "owner": "research-a"},
                    ]
                }
            ).encode()
            path.write_bytes(raw)
            blob = hashlib.sha1(
                b"blob " + str(len(raw)).encode() + b"\0" + raw
            ).hexdigest()
            data = from_module_registry(path, "f" * 40, expected_blob_sha=blob)
            self.assertEqual(
                data.metadata["source_sha256"], hashlib.sha256(raw).hexdigest()
            )
            labels = data.metadata["label_catalog"]
            restored = [labels[event.value] for event in data.events]
            self.assertEqual(
                restored, [row["owner"] for row in json.loads(raw)["modules"]]
            )
            self.assertGreater(data.metadata["label_catalog_bytes"], 0)
            path.write_bytes(raw + b" ")
            with self.assertRaisesRegex(ValueError, "identity mismatch"):
                from_module_registry(path, "f" * 40, expected_blob_sha=blob)


if __name__ == "__main__":
    unittest.main()
