"""Independent checks of original event boundaries and censored TRAIN labels."""

import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ensure_transition_loader as loader


ARCHIVE = Path(
    os.environ.get(
        "ACT_TEST_ARCHIVE",
        Path(__file__).resolve().parents[2]
        / "qualification/act2-learning-20261110/run2",
    )
)


class EnsureTransitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lines = gzip.decompress(
            (ARCHIVE / "training-trajectories.jsonl.gz").read_bytes()
        ).splitlines(keepends=True)
        cls.rows = [json.loads(line) for line in cls.lines]
        cls.tasks = json.loads((ARCHIVE / "FROZEN_MANIFEST.json").read_text())[
            "train_tasks"
        ]
        cls.dataset = loader.load_transitions(ARCHIVE)

    def test_original_apply_events_define_exact_transition_denominator_and_boundaries(
        self,
    ):
        records = {
            (r["task_id"], r["decision_index"]): r for r in self.dataset["records"]
        }
        expected_keys = set()
        for row, task in zip(self.rows, self.tasks):
            applies = [
                i for i, event in enumerate(row["events"]) if event["action"] == "apply"
            ]
            ensures = [
                i for i, action in enumerate(row["decisions"]) if action == "ensure"
            ]
            self.assertEqual(len(ensures), len(applies))
            for decision, apply in zip(ensures, applies):
                key = (task["id"], decision)
                expected_keys.add(key)
                record = records[key]
                prior = max(
                    i for i in range(apply) if row["events"][i]["action"] == "inspect"
                )
                observed = row["events"][prior]["observation"]
                start = apply if observed["staged"] else apply - 1
                self.assertEqual(record["initiation"]["index"], prior)
                self.assertEqual(record["initiation"]["event"], row["events"][prior])
                self.assertEqual(
                    [r["index"] for r in record["primitives"]],
                    list(range(start, apply + 1)),
                )
                self.assertEqual(
                    record["initiation_features"],
                    row["policy_visible_features"][decision],
                )
                self.assertEqual(
                    record["invocation_id"], task["id"] + ":" + str(observed["index"])
                )
                self.assertEqual(
                    record["goal_sha256"],
                    hashlib.sha256(
                        task["goals"][observed["index"]].encode()
                    ).hexdigest(),
                )
                first_read = row["events"][apply + 1]
                self.assertEqual(first_read["action"], "inspect")
                self.assertEqual(
                    record["measurements"]["event_start_gap_ns"],
                    first_read["at_ns"] - row["events"][start]["at_ns"],
                )
        self.assertEqual(set(records), expected_keys)
        self.assertEqual(len(records), 96)
        no_ensure = {
            row["task_id"] for row in self.rows if "ensure" not in row["decisions"]
        }
        self.assertEqual(
            {
                e["task_id"]
                for e in self.dataset["episodes"]
                if not e["ensure_decision_indices"]
            },
            no_ensure,
        )
        self.assertEqual(len(self.dataset["episodes"]), 80)

    def test_labels_follow_same_next_observed_readback_including_partial_task(self):
        rows = {row["task_id"]: row for row in self.rows}
        counts = {True: 0, False: 0, None: 0}
        for record in self.dataset["records"]:
            events = rows[record["task_id"]]["events"]
            witnesses = record["readbacks"]
            known = next(
                (w for w in witnesses if events[w["index"]]["observation"] is not None),
                None,
            )
            target = record["target"]
            counts[target["task_complete_on_readback"]] += 1
            if known is None:
                self.assertEqual(
                    target,
                    {
                        "goal_observed": None,
                        "task_complete_on_readback": None,
                        "censoring": "readback_unavailable",
                        "evidence_event_index": None,
                    },
                )
            else:
                actual = events[known["index"]]["observation"]
                key = record["initiation"]["event"]["observation"]["index"]
                self.assertEqual(
                    target,
                    {
                        "goal_observed": actual["index"] > key,
                        "task_complete_on_readback": actual["complete"],
                        "censoring": None,
                        "evidence_event_index": known["index"],
                    },
                )
        self.assertEqual(counts, {True: 56, False: 24, None: 16})
        # This is a forecast from entry, not a copy of an already complete input.
        self.assertTrue(
            all(r["initiation_features"][1] == 0 for r in self.dataset["records"])
        )

    def test_terminal_oracle_score_cannot_fill_unknown_or_change_observed_labels(self):
        score_fields = (
            "complete",
            "claimed_success",
            "unknown",
            "goal_label_available",
            "right_censored",
            "completion_ns",
            "partial",
            "applied_effects",
            "database_archive_member",
            "database_sha256",
            "independent_oracle_queries",
            "duration_ns",
        )
        oracle_completed_but_censored = 0
        for row, task in zip(self.rows, self.tasks):
            original = loader._episode(row, task, {})
            poisoned = copy.deepcopy(row)
            for key in score_fields:
                poisoned[key] = {
                    "forbidden_terminal_score": [
                        True,
                        False,
                        "not an actor observation",
                    ]
                }
            self.assertEqual(loader._episode(poisoned, task, {}), original)
            if row["complete"] and any(
                r["target"]["goal_observed"] is None for r in original
            ):
                oracle_completed_but_censored += 1
        self.assertGreater(oracle_completed_but_censored, 0)

    def test_exact_line_event_record_and_dataset_commitments(self):
        for record in self.dataset["records"]:
            line = self.lines[record["source"]["line_number"] - 1]
            self.assertEqual(
                record["source"]["line_sha256"], hashlib.sha256(line).hexdigest()
            )
            self.assertNotEqual(
                record["source"]["line_sha256"],
                hashlib.sha256(line.rstrip(b"\n")).hexdigest(),
            )
            for witness in [
                record["initiation"],
                *record["primitives"],
                *record["readbacks"],
            ]:
                event = json.loads(line)["events"][witness["index"]]
                self.assertEqual(witness["event"], event)
                self.assertEqual(
                    witness["sha256"],
                    hashlib.sha256(loader.canonical(event)).hexdigest(),
                )
            unhashed = {k: v for k, v in record.items() if k != "record_sha256"}
            self.assertEqual(
                record["record_sha256"],
                hashlib.sha256(loader.canonical(unhashed)).hexdigest(),
            )
        unhashed = {k: v for k, v in self.dataset.items() if k != "dataset_sha256"}
        self.assertEqual(
            self.dataset["dataset_sha256"],
            hashlib.sha256(loader.canonical(unhashed)).hexdigest(),
        )

    def test_public_loader_reads_no_confirmation_models_scores_or_destination(self):
        allowed = {str((ARCHIVE / name).resolve()) for name in loader.PINS}
        allowed.add(str(Path(loader.__file__).resolve()))
        opened = set()
        original_open = Path.open

        def guarded(path, *args, **kwargs):
            resolved = str(path.resolve())
            self.assertIn(resolved, allowed)
            opened.add(resolved)
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", guarded):
            actual = loader.load_transitions(ARCHIVE)
        self.assertEqual(actual, self.dataset)
        self.assertEqual(opened, allowed)

    def test_changed_archive_bytes_and_self_rehashed_rows_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            originals = {name: (ARCHIVE / name).read_bytes() for name in loader.PINS}
            for changed_name in originals:
                with self.subTest(file=changed_name):
                    for name, value in originals.items():
                        (path / name).write_bytes(
                            value + (b" " if name == changed_name else b"")
                        )
                    with self.assertRaisesRegex(
                        ValueError, "original archive pin differs"
                    ):
                        loader.load_transitions(path)
            for name, value in originals.items():
                (path / name).write_bytes(value)
            altered = copy.deepcopy(self.rows)
            altered[0]["events"][3]["observation"]["complete"] = False
            forged = gzip.compress(
                b"".join(loader.canonical(row) + b"\n" for row in altered), mtime=0
            )
            (path / "training-trajectories.jsonl.gz").write_bytes(forged)
            sums = json.loads(originals["SHA256SUMS.json"])
            sums["training-trajectories.jsonl.gz"] = hashlib.sha256(forged).hexdigest()
            (path / "SHA256SUMS.json").write_bytes(loader.canonical(sums))
            with self.assertRaisesRegex(ValueError, "original archive pin differs"):
                loader.load_transitions(path)

    def test_event_reordering_wrong_entry_features_and_foreign_identity_rejected(self):
        row, task = self.rows[0], self.tasks[0]
        changed = []
        r = copy.deepcopy(row)
        r["events"][1]["action"], r["events"][2]["action"] = "apply", "stage"
        changed.append(r)
        r = copy.deepcopy(row)
        r["policy_visible_features"][1] = r["policy_visible_features"][-1]
        changed.append(r)
        r = copy.deepcopy(row)
        r["task_id"] = self.tasks[1]["id"]
        changed.append(r)
        r = copy.deepcopy(row)
        r["events"][3]["at_ns"] = 0
        changed.append(r)
        r = copy.deepcopy(row)
        r["events"][3]["observation"]["complete"] = False
        changed.append(r)
        r = copy.deepcopy(row)
        r["events"].pop()
        r["primitive_calls"] -= 1
        changed.append(r)
        for i, mutated in enumerate(changed):
            with self.subTest(mutation=i), self.assertRaises(ValueError):
                loader._episode(mutated, task, {})

    def test_prestaged_partial_and_lost_ack_keep_original_entry_boundary(self):
        for row, task in zip(self.rows, self.tasks):
            records = loader._episode(row, task, {})
            if task["fault"] == "prestaged" and records:
                self.assertEqual(
                    [p["event"]["action"] for p in records[0]["primitives"]], ["apply"]
                )
            if task["fault"] == "already_partial" and len(task["goals"]) == 2:
                self.assertEqual(records[0]["invocation_id"], task["id"] + ":1")
            if task["fault"] == "lost_reply":
                decision = row["decisions"].index("ensure")
                poisoned = copy.deepcopy(row)
                poisoned["policy_visible_features"][decision + 1][0] = 1
                with self.assertRaisesRegex(ValueError, "original actor view"):
                    loader._episode(poisoned, task, {})
                self.assertTrue(records[0]["target"]["goal_observed"])

    def test_ambiguous_or_nonfinite_json_is_refused(self):
        for value in (
            b'{"task_id":"first","task_id":"second"}',
            b'{"at_ns":NaN}',
            b'{"at_ns":Infinity}',
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                loader.decode(value)


if __name__ == "__main__":
    unittest.main()
