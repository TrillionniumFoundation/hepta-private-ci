"""Engineering state and recovery fixtures; no real-task benefit is measured."""

import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from .episodic_memory import EpisodicStore, WorkingState, digest


def provenance(version="1", episode="learn-1"):
    return {
        "source_uri": "fixture://source-a",
        "source_sha256": "a" * 64,
        "source_version": version,
        "episode_id": episode,
    }


class EpisodicMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = EpisodicStore(self.root / "authority.sqlite", namespace="team-a")

    def put(self, key, text, dependencies=()):
        return self.store.put(
            "source-a", key, text, provenance=provenance(), dependencies=dependencies
        )

    def test_update_revokes_transitive_dependencies_and_filters_old_snapshot(self):
        fact = self.put("gate", "Gate is A")
        derived = self.put("route", "Take route A", [fact["record_id"]])
        final = self.put("memo", "Route A memo", [derived["record_id"]])
        unrelated = self.put("contact", "Contact remains valid")
        snapshot = self.root / "before.json"
        self.store.export_snapshot(snapshot)
        updated = self.store.put(
            "source-a", "gate", "Gate is B", provenance=provenance("2", "update-2")
        )
        self.assertEqual(updated["version"], 2)
        self.assertEqual(self.store.view()["records"], [unrelated, updated])
        recovered = self.store.view(snapshot)
        self.assertEqual(recovered["records"], [unrelated])
        self.assertEqual(recovered["receipt"]["snapshot_rejections"], 3)
        # Exact dependency identities remain invalid after a new value is written.
        with self.assertRaises(ValueError):
            self.put("reused", "Wrong old derivation", [final["record_id"]])

    def test_revoke_removes_payload_and_old_snapshot_never_reactivates_it(self):
        fact = self.put("secret", "Fixture retention value")
        dependent = self.put("summary", "Derived fixture value", [fact["record_id"]])
        snapshot = self.root / "old.json"
        self.store.export_snapshot(snapshot)
        receipt = self.store.revoke("source-a", "secret")
        self.assertEqual(
            set(receipt["affected_ids"]), {fact["record_id"], dependent["record_id"]}
        )
        with sqlite3.connect(self.store.path) as db:
            rows = db.execute(
                "SELECT key,payload,status FROM records ORDER BY key"
            ).fetchall()
        self.assertEqual(
            rows, [("secret", None, "revoked"), ("summary", None, "dependency_revoked")]
        )
        reopened = EpisodicStore(self.store.path, namespace="team-a", create=False)
        self.assertEqual(reopened.view(snapshot)["records"], [])
        self.assertEqual(reopened.view()["records"], [])
        self.assertEqual(
            reopened.revoke("source-a", "secret"),
            {"status": "already_revoked", "affected_ids": []},
        )
        replacement = reopened.put(
            "source-a", "secret", "Explicit new evidence", provenance=provenance("3")
        )
        self.assertEqual(replacement["version"], 3)
        self.assertEqual(reopened.view(snapshot)["records"], [])

    def test_reverse_key_order_chain_revokes_entire_dependency_closure(self):
        # Descendants sort before their parents in the SQLite key order; a
        # full repeated scan grows quadratically on this legal input.
        for action in ("update", "revoke"):
            with self.subTest(action=action):
                store = EpisodicStore(
                    self.root / f"reverse-{action}.sqlite", namespace="team-a"
                )
                root = store.put("source-a", "root", "Root", provenance=provenance())
                chain = [root]
                for index in range(96):
                    child = store.put(
                        "source-a",
                        f"{96 - index:04d}",
                        f"Derived {index}",
                        provenance=provenance(),
                        dependencies=[chain[-1]["record_id"]],
                    )
                    chain.append(child)
                before = store.view()["receipt"]["authority_generation"]
                snapshot = self.root / f"reverse-{action}.json"
                store.export_snapshot(snapshot)
                if action == "update":
                    replacement = store.put(
                        "source-a",
                        "root",
                        "New root",
                        provenance=provenance("2", "update"),
                    )
                    self.assertEqual(store.view()["records"], [replacement])
                else:
                    receipt = store.revoke("source-a", "root")
                    self.assertEqual(
                        set(receipt["affected_ids"]),
                        {record["record_id"] for record in chain},
                    )
                    self.assertEqual(store.view()["records"], [])
                recovered = store.view(snapshot)
                self.assertEqual(recovered["records"], [])
                self.assertEqual(
                    recovered["receipt"]["snapshot_rejections"], len(chain)
                )
                self.assertEqual(
                    recovered["receipt"]["authority_generation"], before + 1
                )

    def test_namespace_isolation_and_foreign_dependency_rejection(self):
        first = self.put("fact", "Team A value")
        other = EpisodicStore(self.store.path, namespace="team-b", create=False)
        second = other.put("source-a", "fact", "Team B value", provenance=provenance())
        self.assertEqual(self.store.view()["records"], [first])
        self.assertEqual(other.view()["records"], [second])
        with self.assertRaises(ValueError):
            other.put(
                "source-a",
                "bad",
                "Foreign dependency",
                provenance=provenance(),
                dependencies=[first["record_id"]],
            )
        self.store.revoke("source-a", "fact")
        self.assertEqual(other.view()["records"], [second])

    def test_bounded_tombstones_prevent_replay_and_admission_rolls_back(self):
        store = EpisodicStore(
            self.root / "bounded.sqlite", namespace="n", max_records=1
        )
        store.put("s", "k", "Value", provenance=provenance())
        store.revoke("s", "k")
        before = store.view()
        with self.assertRaises(ValueError):
            store.put(
                "s", "other", "Exceeds tombstone capacity", provenance=provenance()
            )
        self.assertEqual(store.view(), before)
        resumed = store.put("s", "k", "Explicit replacement", provenance=provenance())
        self.assertEqual(resumed["version"], 3)

    def test_byte_admission_failure_preserves_existing_data_and_generation(self):
        store = EpisodicStore(
            self.root / "bytes.sqlite", namespace="n", max_serialized_bytes=2500
        )
        store.put("s", "k", "Kept", provenance=provenance())
        before = store.view()
        with self.assertRaises(ValueError):
            store.put("s", "k", "x" * 4096, provenance=provenance())
        self.assertEqual(store.view(), before)

    def test_current_authority_is_required_and_snapshot_has_its_identity(self):
        self.put("fact", "Known")
        snapshot = self.root / "snapshot.json"
        self.store.export_snapshot(snapshot)
        new_owner = EpisodicStore(self.root / "other.sqlite", namespace="team-a")
        with self.assertRaises(ValueError):
            new_owner.view(snapshot)
        missing = self.root / "missing.sqlite"
        with self.assertRaises(ValueError):
            EpisodicStore(missing, namespace="team-a", create=False)
        self.assertFalse(missing.exists())
        with self.assertRaises(ValueError):
            self.store.export_snapshot(self.store.path)

    def test_snapshot_corruption_and_forged_record_are_rejected(self):
        self.put("fact", "Known")
        snapshot = self.root / "snapshot.json"
        self.store.export_snapshot(snapshot)
        envelope = json.loads(snapshot.read_text())
        envelope["body"]["records"][0]["text"] = "Corrupted"
        snapshot.write_text(json.dumps(envelope))
        with self.assertRaises(ValueError):
            self.store.view(snapshot)
        envelope["sha256"] = digest(envelope["body"])
        snapshot.write_text(json.dumps(envelope))
        with self.assertRaises(ValueError):
            self.store.view(snapshot)

    def test_redigested_snapshot_cannot_move_records_before_their_write(self):
        fact = self.put("fact", "Known")
        snapshot = self.root / "snapshot.json"
        self.store.export_snapshot(snapshot)
        original = json.loads(snapshot.read_text())
        before = self.store.view()
        for mutation in ("generation", "write_sequence", "version"):
            with self.subTest(mutation=mutation):
                envelope = json.loads(json.dumps(original))
                if mutation == "generation":
                    envelope["body"]["generation"] = 0
                else:
                    record = envelope["body"]["records"][0]
                    record[mutation] = 2
                    record["record_id"] = digest(
                        {
                            key: value
                            for key, value in record.items()
                            if key != "record_id"
                        }
                    )
                envelope["sha256"] = digest(envelope["body"])
                snapshot.write_text(json.dumps(envelope))
                with self.assertRaises(ValueError):
                    self.store.view(snapshot)
                self.assertEqual(self.store.view(), before)
        # The true old snapshot remains a legal read after unrelated writes.
        snapshot.write_text(json.dumps(original))
        self.put("other", "Later value")
        self.assertEqual(self.store.view(snapshot)["records"], [fact])

    def test_redigested_snapshot_requires_a_consistent_historical_roster(self):
        root = self.put("fact", "Known")
        self.put("derived", "Derived known", [root["record_id"]])
        snapshot = self.root / "snapshot.json"
        self.store.export_snapshot(snapshot)
        original = json.loads(snapshot.read_text())
        before = self.store.view()
        for mutation in (
            "namespace",
            "duplicate_slot",
            "missing_dependency",
            "dependency_order",
        ):
            with self.subTest(mutation=mutation):
                envelope = json.loads(json.dumps(original))
                records = envelope["body"]["records"]
                if mutation == "missing_dependency":
                    records.pop(0)
                elif mutation == "duplicate_slot":
                    # A snapshot cannot contain two versions of one logical fact.
                    replacement = dict(records[0], version=2, write_sequence=2)
                    replacement["record_id"] = digest(
                        {
                            key: value
                            for key, value in replacement.items()
                            if key != "record_id"
                        }
                    )
                    records.append(replacement)
                else:
                    record = records[0] if mutation == "namespace" else records[1]
                    record[
                        "namespace" if mutation == "namespace" else "write_sequence"
                    ] = "team-b" if mutation == "namespace" else root["write_sequence"]
                    record["record_id"] = digest(
                        {
                            key: value
                            for key, value in record.items()
                            if key != "record_id"
                        }
                    )
                envelope["sha256"] = digest(envelope["body"])
                snapshot.write_text(json.dumps(envelope))
                with self.assertRaises(ValueError):
                    self.store.view(snapshot)
                self.assertEqual(self.store.view(), before)

    def test_empty_snapshot_and_valid_old_dependency_chain_remain_readable(self):
        empty = self.root / "empty.json"
        self.store.export_snapshot(empty)
        self.assertEqual(self.store.view(empty)["records"], [])
        first = self.put("fact", "Known")
        second = self.put("derived", "Derived known", [first["record_id"]])
        snapshot = self.root / "old-chain.json"
        self.store.export_snapshot(snapshot)
        self.put("later", "Later fact")
        self.assertEqual(self.store.view(empty)["records"], [])
        self.assertEqual(self.store.view(snapshot)["records"], [first, second])
        self.store.revoke("source-a", "fact")
        stale = self.store.view(snapshot)
        self.assertEqual(stale["records"], [])
        self.assertEqual(stale["receipt"]["snapshot_rejections"], 2)

    def test_update_cannot_create_an_indirect_dependency_cycle(self):
        fact = self.put("a", "A")
        dependent = self.put("b", "B", [fact["record_id"]])
        before = self.store.view()
        with self.assertRaises(ValueError):
            self.put("a", "New A from stale B", [dependent["record_id"]])
        self.assertEqual(self.store.view(), before)

    def test_caller_cannot_mutate_stored_provenance_or_returned_record(self):
        source = provenance()
        record = self.store.put("source-a", "fact", "Known", provenance=source)
        original = json.loads(json.dumps(record))
        source["source_version"] = "999"
        record["text"] = "Changed by caller"
        self.assertEqual(self.store.view()["records"], [original])
        with self.assertRaises(ValueError):
            self.store.put(
                "source-a", "invalid", "Value", provenance={**source, "gold": True}
            )

    def test_working_state_is_copied_bounded_and_cleared_on_new_session(self):
        state = WorkingState("episode-1", max_serialized_bytes=40)
        value = ["working"]
        state.put("k", value)
        value.append("external")
        self.assertEqual(state.get("k"), ["working"])
        with self.assertRaises(ValueError):
            state.put("oversize", "x" * 100)
        self.assertEqual(state.get("k"), ["working"])
        state.begin_session("episode-2")
        self.assertIsNone(state.get("k"))
        self.assertIsNone(WorkingState("episode-1").get("k"))

    def test_snapshot_rejects_fifo_directory_and_symlink_before_read(self):
        self.put("fact", "Still readable")
        regular = self.root / "safe-snapshot.json"
        self.store.export_snapshot(regular)
        self.assertEqual(len(self.store.view(regular)["records"]), 1)
        with self.assertRaisesRegex(ValueError, "regular file"):
            self.store.view(self.root)
        if hasattr(os, "mkfifo"):
            fifo = self.root / "untrusted.fifo"
            os.mkfifo(fifo)
            # No writer is attached: opening this FIFO must not hang.
            with self.assertRaisesRegex(ValueError, "regular file"):
                self.store.view(fifo)
        alias = self.root / "snapshot-alias.json"
        try:
            alias.symlink_to(regular)
        except (OSError, NotImplementedError):
            pass  # Windows may lack symlink creation privileges.
        else:
            with self.assertRaisesRegex(ValueError, "symlink"):
                self.store.view(alias)
        self.assertEqual(len(self.store.view(regular)["records"]), 1)


if __name__ == "__main__":
    unittest.main()
