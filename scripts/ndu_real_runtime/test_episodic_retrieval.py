"""New-process retrieval and mechanism controls, with synthetic engineering data."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from . import episodic_retrieval
from .episodic_memory import EpisodicStore, canonical_bytes, digest
from .episodic_retrieval import (
    assemble_context,
    hashlib_sha,
    read_memory,
    verify_read_receipt,
)
from .test_episodic_memory import provenance


class EpisodicRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = EpisodicStore(self.root / "authority.sqlite", namespace="n")
        self.gate = self.store.put(
            "s1", "gate", "Current gate is B12", provenance=provenance()
        )
        self.route = self.store.put(
            "s1", "route", "Gate B12 needs a shuttle", provenance=provenance()
        )
        self.foreign = self.store.put(
            "s2", "gate", "Other source gate C30", provenance=provenance()
        )

    def read(self, **kwargs):
        return read_memory(
            self.store,
            **{
                "session_id": "eval-1",
                "source_ids": ["s1"],
                "query": "gate B12",
                **kwargs,
            },
        )

    def test_exact_kv_and_bm25_only_read_approved_sources(self):
        exact = self.read(strategy="exact_kv", key="gate")
        self.assertEqual(exact["records"], [self.gate])
        ranked = self.read(strategy="bm25")
        self.assertEqual(
            {r["record_id"] for r in ranked["records"]},
            {self.gate["record_id"], self.route["record_id"]},
        )
        self.assertTrue(verify_read_receipt(ranked))
        self.assertEqual(self.read(source_ids=["missing"])["records"], [])
        self.assertEqual(self.read(query="No matching tokens")["records"], [])
        other = EpisodicStore(self.store.path, namespace="another", create=False)
        self.assertEqual(
            read_memory(other, session_id="fresh", source_ids=["s1"], query="gate")[
                "records"
            ],
            [],
        )

    def test_foreign_dependency_and_transitive_summary_are_not_retrieved(self):
        """An allowlisted source must not launder disallowed source evidence."""
        derived = self.store.put(
            "s1",
            "derived",
            "Derived fact reveals restricted source C30",
            provenance=provenance(),
            dependencies=[self.foreign["record_id"]],
        )
        chained = self.store.put(
            "s1",
            "descendant",
            "Second-order C30 summary",
            provenance=provenance(),
            dependencies=[derived["record_id"]],
        )
        before = self.root / "cross-source-before.json"
        self.store.export_snapshot(before)
        rejected_ids = {derived["record_id"], chained["record_id"]}
        for strategy in ("exact_kv", "bm25", "uniform_replay", "icl"):
            with self.subTest(strategy=strategy):
                result = self.read(
                    strategy=strategy,
                    key="derived" if strategy == "exact_kv" else None,
                    query="C30",
                    snapshot_path=before,
                )
                self.assertFalse(
                    rejected_ids.intersection(r["record_id"] for r in result["records"])
                )
                self.assertEqual(result["receipt"]["source_dependency_rejections"], 2)
                self.assertTrue(verify_read_receipt(result))
        approved = read_memory(
            self.store,
            session_id="both-sources",
            source_ids=["s1", "s2"],
            strategy="exact_kv",
            key="derived",
        )
        self.assertEqual(approved["records"], [derived])
        self.assertEqual(approved["receipt"]["source_dependency_rejections"], 0)
        self.assertTrue(verify_read_receipt(approved))

    def test_modes_separate_store_read_retrieval_and_delivery(self):
        with patch.object(
            self.store, "view", side_effect=AssertionError("unexpected read")
        ):
            off = self.read(mode="off")
        absent = read_memory(None, session_id="fresh", source_ids=["s1"], mode="off")
        self.assertEqual((off["context"], absent["records"]), ("", []))
        self.assertFalse(absent["receipt"]["store_read"])
        cases = {
            "on": (True, True, True),
            "retrieval_off": (True, False, False),
            "delivery_off": (True, True, False),
            "association_off": (True, True, True),
        }
        for mode, expected in cases.items():
            with self.subTest(mode=mode):
                result = self.read(mode=mode)
                r = result["receipt"]
                self.assertEqual(
                    (
                        r["store_read"],
                        r["retrieval_executed"],
                        bool(r["delivered_ids"]),
                    ),
                    expected,
                )
                self.assertTrue(verify_read_receipt(result))
        self.assertEqual(self.read()["receipt"]["association_status"], "unavailable")

    def test_real_callback_and_its_ablation_do_not_mutate_evidence(self):
        calls = []

        def association(query, records):
            calls.append(query)
            records[0]["text"] = "Mutation attempt"
            return [r["record_id"] for r in reversed(records)]

        baseline = self.read(strategy="icl")
        associated = self.read(
            strategy="icl", association=association, association_id="b" * 64
        )
        self.assertEqual(associated["records"], list(reversed(baseline["records"])))
        self.assertTrue(verify_read_receipt(associated))
        self.assertEqual(calls, ["gate B12"])
        disabled = self.read(
            strategy="icl",
            mode="association_off",
            association=association,
            association_id="b" * 64,
        )
        self.assertEqual(disabled["records"], baseline["records"])
        self.assertEqual(calls, ["gate B12"])
        self.assertEqual(disabled["receipt"]["association_status"], "disabled")
        self.assertTrue(verify_read_receipt(disabled))
        with self.assertRaises(ValueError):
            self.read(association=lambda q, rows: ["unknown"], association_id="b" * 64)

    def test_uniform_replay_and_icl_are_bounded_deterministic_baselines(self):
        first = self.read(strategy="uniform_replay", seed=7, limit=1)
        second = self.read(strategy="uniform_replay", seed=7, limit=1)
        self.assertEqual(first["records"], second["records"])
        self.assertEqual(len(first["records"]), 1)
        self.assertEqual(self.read(strategy="icl")["records"], [self.gate, self.route])
        small = self.read(strategy="icl", max_context_bytes=1)
        self.assertEqual((small["records"], small["context"]), ([], ""))
        self.assertEqual(
            small["receipt"]["byte_dropped_ids"],
            [self.gate["record_id"], self.route["record_id"]],
        )
        self.assertTrue(verify_read_receipt(small))

    def test_ranking_cannot_deliver_a_fact_revoked_or_updated_during_the_read(self):
        for action in ("revoke", "update"):
            with self.subTest(action=action):
                self.store.put("s1", "race", "Old gate B12", provenance=provenance())

                def association(query, records):
                    if action == "revoke":
                        self.store.revoke("s1", "race")
                    else:
                        self.store.put(
                            "s1", "race", "New gate C30", provenance=provenance()
                        )
                    return [r["record_id"] for r in records]

                with self.assertRaisesRegex(ValueError, "before context delivery"):
                    self.read(
                        strategy="exact_kv",
                        key="race",
                        association=association,
                        association_id="b" * 64,
                    )
                current = self.read(strategy="exact_kv", key="race")
                self.assertEqual(
                    [r["text"] for r in current["records"]],
                    [] if action == "revoke" else ["New gate C30"],
                )
                self.assertTrue(verify_read_receipt(current))

    def test_inflight_revocation_of_a_dependency_aborts_summary_delivery(self):
        dependent = self.store.put(
            "s1",
            "derived",
            "Follow the B12 route",
            provenance=provenance(),
            dependencies=[self.gate["record_id"]],
        )

        def association(query, records):
            self.assertEqual(records, (dependent,))
            self.store.revoke("s1", "gate")
            return [dependent["record_id"]]

        with self.assertRaisesRegex(ValueError, "before context delivery"):
            self.read(
                strategy="exact_kv",
                key="derived",
                association=association,
                association_id="b" * 64,
            )
        self.assertEqual(self.read(strategy="exact_kv", key="derived")["records"], [])

    def test_separate_writer_process_cannot_revoke_between_retrieval_and_delivery(self):
        snapshot = self.root / "inflight-before.json"
        self.store.export_snapshot(snapshot)
        original_bm25 = episodic_retrieval.bm25

        def retrieve_then_revoke(records, query, limit):
            selected = original_bm25(records, query, limit)
            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-c",
                    "import sys; "
                    "from scripts.ndu_real_runtime.episodic_memory import EpisodicStore; "
                    "s = EpisodicStore(sys.argv[1], namespace='n', create=False); "
                    "s.revoke('s1', 'gate')",
                    str(self.store.path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                timeout=20,
                check=True,
            )
            self.assertEqual((completed.stdout, completed.stderr), (b"", b""))
            return selected

        # Synchronize a real independent writer in the vulnerable interval;
        # retrieval and authority operations themselves remain the real paths.
        with patch.object(episodic_retrieval, "bm25", side_effect=retrieve_then_revoke):
            with self.assertRaisesRegex(ValueError, "before context delivery"):
                self.read(strategy="bm25", snapshot_path=snapshot)
        self.assertEqual(self.read(strategy="exact_kv", key="gate")["records"], [])

    def test_inflight_namespace_or_authority_replacement_aborts_delivery(self):
        def change_namespace(query, records):
            self.store.namespace = "foreign"
            return [r["record_id"] for r in records]

        try:
            with self.assertRaisesRegex(ValueError, "before context delivery"):
                self.read(association=change_namespace, association_id="b" * 64)
        finally:
            self.store.namespace = "n"

        other = EpisodicStore(self.root / "other.sqlite", namespace="n")
        for record in (self.gate, self.route, self.foreign):
            other.put(
                record["source_id"],
                record["key"],
                record["text"],
                provenance=record["provenance"],
            )
        self.assertEqual(
            self.store.view()["receipt"]["authority_generation"],
            other.view()["receipt"]["authority_generation"],
        )

        def replace_authority(query, records):
            os.replace(other.path, self.store.path)
            return [r["record_id"] for r in records]

        with self.assertRaisesRegex(ValueError, "before context delivery"):
            self.read(association=replace_authority, association_id="b" * 64)

    def test_callback_cannot_change_original_source_allowlist(self):
        allowed = ["s1"]

        def association(query, records):
            allowed[:] = ["s2"]
            return [r["record_id"] for r in records]

        result = self.read(
            source_ids=allowed,
            strategy="exact_kv",
            key="gate",
            association=association,
            association_id="b" * 64,
        )
        self.assertEqual(result["records"], [self.gate])
        self.assertEqual(result["receipt"]["source_ids"], ["s1"])
        self.assertTrue(verify_read_receipt(result))

    def test_suppressed_delivery_does_not_revalidate_or_emit_revoked_content(self):
        def association(query, records):
            self.store.revoke("s1", "gate")
            return [r["record_id"] for r in records]

        with patch.object(self.store, "view", wraps=self.store.view) as view:
            result = self.read(
                mode="delivery_off",
                association=association,
                association_id="b" * 64,
            )
            self.assertEqual(view.call_count, 1)
        self.assertEqual((result["records"], result["context"]), ([], ""))
        self.assertTrue(verify_read_receipt(result))
        for mode, reads in (("off", 0), ("retrieval_off", 1)):
            with self.subTest(mode=mode):
                with patch.object(self.store, "view", wraps=self.store.view) as view:
                    result = self.read(
                        mode=mode,
                        association=lambda *args: self.fail("unexpected ranking"),
                        association_id="b" * 64,
                    )
                    self.assertEqual(view.call_count, reads)
                self.assertEqual((result["records"], result["context"]), ([], ""))
                self.assertTrue(verify_read_receipt(result))

    def test_receipt_rejects_changed_context_records_or_audit_fields(self):
        result = self.read()
        for field in ("context", "records", "receipt"):
            changed = json.loads(canonical_bytes(result))
            if field == "context":
                changed[field] += "injected"
            elif field == "records":
                changed[field][0]["text"] = "injected"
            else:
                changed[field]["store_read"] = False
            self.assertFalse(verify_read_receipt(changed))

    def redigest(self, result, **changes):
        changed = json.loads(canonical_bytes(result))
        changed["receipt"].update(changes)
        changed["receipt"]["receipt_sha256"] = digest(
            {
                key: value
                for key, value in changed["receipt"].items()
                if key != "receipt_sha256"
            }
        )
        return changed

    def test_recomputed_digest_does_not_hide_contradictory_interventions(self):
        result = self.read()
        for field, value in (
            ("mode", "off"),
            ("mode", "retrieval_off"),
            ("mode", "delivery_off"),
            ("store_read", False),
            ("retrieval_executed", False),
            ("association_called", True),
            ("association_status", "applied"),
            ("association_id", "a" * 64),
            ("source_ids", ["s2"]),
            ("provenance", []),
            ("view_receipt", None),
            ("eligible_count", 0),
            ("source_dependency_rejections", 4096),
            ("scientific_acceptance", "PASS"),
            ("real_task_benefit_established", True),
            ("association_authentication_established", True),
        ):
            with self.subTest(field=field, value=value):
                self.assertFalse(
                    verify_read_receipt(self.redigest(result, **{field: value}))
                )
        off = self.read(mode="off")
        self.assertFalse(verify_read_receipt(self.redigest(off, eligible_count=1)))
        disabled = self.read(mode="association_off")
        self.assertFalse(
            verify_read_receipt(
                self.redigest(disabled, association_status="unavailable")
            )
        )

    def test_recomputed_digest_does_not_hide_roster_loss_duplication_or_reordering(
        self,
    ):
        result = self.read(strategy="icl")
        ids = result["receipt"]["retrieved_ids"]
        mutations = (
            {"retrieved_ids": ["a" * 64, ids[1]]},
            {"retrieved_ids": ids + ids[:1]},
            {"selected_ids": list(reversed(ids))},
            {"selected_ids": ids + ids[:1]},
            {"byte_dropped_ids": ids[:1]},
        )
        for fields in mutations:
            with self.subTest(fields=fields):
                self.assertFalse(verify_read_receipt(self.redigest(result, **fields)))
        dropped = self.read(strategy="icl", max_context_bytes=0)
        self.assertFalse(
            verify_read_receipt(self.redigest(dropped, byte_dropped_ids=[]))
        )
        self.assertFalse(
            verify_read_receipt(
                self.redigest(dropped, byte_dropped_ids=list(reversed(ids)))
            )
        )
        no_delivery = self.read(mode="delivery_off")
        self.assertFalse(
            verify_read_receipt(
                self.redigest(
                    no_delivery, byte_dropped_ids=no_delivery["receipt"]["selected_ids"]
                )
            )
        )

    def test_recomputed_receipts_reject_malformed_schema_bounds_and_authority(self):
        result = self.read()
        for field, value in (
            ("schema", "unrecognized"),
            ("strategy", "invented"),
            ("session_id", ""),
            ("mode", []),
            ("source_ids", "s1"),
            ("source_ids", ["s1", "s1"]),
            ("limit", True),
            ("limit", 129),
            ("replay_seed", -1),
            ("max_context_bytes", 65537),
            ("context_bytes", -1),
            ("decision_cpu_seconds", -1),
            ("decision_wall_seconds", True),
            ("query_sha256", "not-a-digest"),
            ("retrieved_ids", "not-a-list"),
            ("store_read", 1),
            ("association_called", 0),
            ("undeclared_field", True),
        ):
            with self.subTest(field=field, value=value):
                self.assertFalse(
                    verify_read_receipt(self.redigest(result, **{field: value}))
                )
        for field, value in (
            ("authority_id", "not-an-id"),
            ("authority_generation", True),
            ("resident_record_count", 0),
            ("snapshot_rejections", 1),
            ("frontier_sha256", "invalid"),
            ("malicious_owner_rollback_protected", True),
        ):
            with self.subTest(view_field=field):
                view = {**result["receipt"]["view_receipt"], field: value}
                self.assertFalse(
                    verify_read_receipt(self.redigest(result, view_receipt=view))
                )
        for malformed in (
            None,
            [],
            {},
            {**result, "records": None},
            {**result, "receipt": []},
            {**result, "context": None},
        ):
            with self.subTest(malformed=type(malformed).__name__):
                self.assertFalse(verify_read_receipt(malformed))
        nonfinite = self.redigest(result)
        nonfinite["receipt"]["decision_cpu_seconds"] = float("inf")
        self.assertFalse(verify_read_receipt(nonfinite))

    def test_receipts_allow_actual_empty_partial_and_disabled_callback_paths(self):
        first = self.read(strategy="icl", limit=1)
        partial = self.read(
            strategy="icl", max_context_bytes=first["receipt"]["context_bytes"]
        )
        self.assertEqual(partial["receipt"]["delivered_ids"], [self.gate["record_id"]])
        self.assertEqual(
            partial["receipt"]["byte_dropped_ids"], [self.route["record_id"]]
        )
        self.assertTrue(verify_read_receipt(partial))
        for mode in ("on", "off", "retrieval_off", "delivery_off", "association_off"):
            with self.subTest(mode=mode):
                result = self.read(
                    query="no matches",
                    mode=mode,
                    association=lambda q, rows: [],
                    association_id="b" * 64,
                )
                self.assertTrue(verify_read_receipt(result))
        # The pre-#5766 v1 wire format had no dependency-filter counter.
        legacy = self.read()
        del legacy["receipt"]["source_dependency_rejections"]
        self.assertTrue(verify_read_receipt(self.redigest(legacy)))

    def test_recomputed_record_and_receipt_reject_impossible_chronology(self):
        original = self.read(strategy="exact_kv", key="gate")
        generation = original["receipt"]["view_receipt"]["authority_generation"]
        for field, value in (
            ("write_sequence", generation + 1),
            ("version", original["records"][0]["write_sequence"] + 1),
        ):
            with self.subTest(field=field):
                changed = json.loads(canonical_bytes(original))
                record = changed["records"][0]
                record[field] = value
                record["record_id"] = digest(
                    {key: value for key, value in record.items() if key != "record_id"}
                )
                receipt = changed["receipt"]
                for ids in ("retrieved_ids", "selected_ids", "delivered_ids"):
                    receipt[ids] = [record["record_id"]]
                receipt["provenance"] = [
                    {"record_id": record["record_id"], **record["provenance"]}
                ]
                changed["context"], _, dropped = assemble_context(
                    [record], receipt["max_context_bytes"]
                )
                self.assertEqual(dropped, [])
                receipt["context_bytes"] = len(changed["context"].encode())
                receipt["context_sha256"] = hashlib_sha(changed["context"])
                self.assertFalse(verify_read_receipt(self.redigest(changed)))

    def test_new_process_cli_reads_then_rejects_revoked_snapshot(self):
        root = Path(__file__).resolve().parents[2]
        snapshot = self.root / "before.json"
        self.store.export_snapshot(snapshot)
        command = [
            sys.executable,
            "-m",
            "scripts.ndu_real_runtime.episodic_retrieval",
            "--store",
            str(self.store.path),
            "--namespace",
            "n",
            "--session",
            "new-process",
            "--source",
            "s1",
            "--strategy",
            "exact_kv",
            "--key",
            "gate",
            "--snapshot",
            str(snapshot),
        ]

        def run(args):
            return json.loads(
                subprocess.run(
                    args,
                    cwd=root,
                    text=True,
                    capture_output=True,
                    timeout=20,
                    check=True,
                ).stdout
            )

        before = run(command)
        self.assertEqual(before["records"], [self.gate])
        self.assertTrue(verify_read_receipt(before))
        self.store.revoke("s1", "gate")
        after = run(command)
        self.assertEqual(after["records"], [])
        self.assertEqual(after["receipt"]["view_receipt"]["snapshot_rejections"], 1)
        off = run(
            [
                sys.executable,
                "-m",
                "scripts.ndu_real_runtime.episodic_retrieval",
                "--namespace",
                "n",
                "--session",
                "fresh-off",
                "--source",
                "s1",
                "--mode",
                "off",
            ]
        )
        self.assertEqual(off["records"], [])
        self.assertFalse(off["receipt"]["store_read"])


if __name__ == "__main__":
    unittest.main()
