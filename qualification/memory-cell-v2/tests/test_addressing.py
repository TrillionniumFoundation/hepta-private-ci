"""Version metadata must resolve correctly without carrying memory answers."""

from dataclasses import replace
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE.parent / "memory-cell-research"))
sys.path.insert(0, str(PACKAGE))
from v2.addressing import AddressIndex, FIELDS  # noqa: E402
from v2.real_study import union_events  # noqa: E402
from v2.tasks import WriteEvent  # noqa: E402


def event(revision=1, timestamp="2026-01-01T00:00:00Z", deleted=False):
    return WriteEvent(
        "secret-event-answer",
        "episodic",
        "module.py",
        "secret-memory-answer",
        revision,
        timestamp,
        "secret-source-answer",
        "/source",
        deleted,
    )


class AddressingTests(unittest.TestCase):
    def test_asof_revision_selection_and_current_deletion(self):
        writes = [
            event(),
            event(2, "2026-01-02T00:00:00Z"),
            event(3, "2026-01-03T00:00:00Z", True),
        ]
        index = AddressIndex.from_events(writes)
        requests = [
            "2025-12-31T23:59:59Z",
            "2026-01-01T00:00:00Z",
            "2026-01-02T12:00:00Z",
            None,
        ]
        self.assertEqual(
            [index.resolve("episodic", "module.py", cut) for cut in requests],
            [
                None,
                "Memory type episodic. Key module.py. Revision 1.",
                "Memory type episodic. Key module.py. Revision 2.",
                None,
            ],
        )
        self.assertIsNone(index.resolve("unregistered", "module.py"))
        with self.assertRaises(ValueError):
            index.resolve("episodic", "module.py", "2026-01-01")

    def test_saved_index_excludes_values_and_provenance_and_cannot_be_mutated_through_entries(
        self,
    ):
        index = AddressIndex.from_events([event()])
        index.entries[0]["value"] = "injected"
        self.assertEqual(set(index.entries[0]), FIELDS)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.json"
            index.save(path)
            self.assertEqual(path.stat().st_size, index.bytes)
            self.assertNotIn("secret", path.read_text(encoding="utf-8"))
            self.assertEqual(AddressIndex.load(path).to_dict(), index.to_dict())
        with self.assertRaisesRegex(ValueError, "metadata fields only"):
            AddressIndex([{**index.entries[0], "event_id": "secret-answer"}])

    def test_duplicate_instants_and_inverted_version_time_are_rejected(self):
        cases = [
            [event(), event(2, "2026-01-01T01:00:00+01:00")],
            [event(), event(2, "2025-12-31T00:00:00Z")],
            [event(), event()],
        ]
        for writes in cases:
            with self.subTest(writes=writes), self.assertRaises(ValueError):
                AddressIndex.from_events(writes)

    def test_union_deduplicates_identical_sources_and_rejects_value_or_provenance_conflicts(
        self,
    ):
        write = event()
        bundles = {
            "first": SimpleNamespace(events=(write,)),
            "second": SimpleNamespace(events=(write,)),
        }
        self.assertEqual(union_events(bundles), (write,))
        for changed in (
            replace(write, value="different"),
            replace(write, source_id="different-source"),
        ):
            bundles["second"] = SimpleNamespace(events=(changed,))
            with self.assertRaisesRegex(ValueError, "conflicting duplicate"):
                union_events(bundles)


if __name__ == "__main__":
    unittest.main()
