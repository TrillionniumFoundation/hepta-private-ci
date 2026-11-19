"""Fresh-role disjointness, transitive exclusions and encrypted-label boundary."""

from collections import Counter
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from cell_field_data_v5 import COUNTS, DATASETS, candidates, data_plan, identity_keys, prepare, select, sha
from prepare_news_cohorts import canonical


def fixture_rows(task):
    return [{"task_id": task, "source_id": f"{task}-{bucket}-{label}-{i}", "label": label,
        "component_id": f"{task}-component-{bucket}-{label}-{i}", "bucket": bucket,
        "official_split": "test" if bucket == "future" else "train", "source_row_sha256": sha([task, bucket, label, i]),
        "text": f"fixture source {task} {bucket} {label} {i}"}
        for bucket, n in (("old", 300), ("current", 180), ("future", 140)) for label in range(4) for i in range(n)]


class DataV5Tests(unittest.TestCase):
    def test_normalization_and_truncated_input_union(self):
        left = identity_keys("Ａlpha—Beta", "body one", "x"*6000+"end1")
        right = identity_keys("alpha beta", "body two", "x"*6000+"end2")
        self.assertIn(sha(b"alpha beta"), set(left)&set(right))
        self.assertIn(sha(("x"*6000).encode()), set(left)&set(right))

    def test_selection_is_order_invariant_disjoint_and_balanced(self):
        rows = fixture_rows("agnews")
        chosen, _ = select(rows, "agnews")
        reverse, _ = select(list(reversed(rows)), "agnews")
        self.assertEqual(chosen, reverse)
        self.assertEqual(len({r["component_id"] for r in chosen}), 2304)
        for role, n in COUNTS.items():
            members = [r for r in chosen if r["role"] == role]
            self.assertEqual(Counter(r["label"] for r in members), {i: n//4 for i in range(4)})
            self.assertTrue(all(r["bucket"] == role.split("_")[0] for r in members))

    def test_complete_graph_excludes_prior_cross_split_class_and_task(self):
        def row(i, key, task="agnews", split="train", label=0):
            return {"source_id": str(i), "edges": (key,), "task_id": task, "official_split": split,
                    "label": label, "short": False, "text": "fixture text"}
        corpus = {"agnews": [row(0, "split"), row(1, "split", split="test"), row(2, "class"),
            row(3, "class", label=1), row(4, "prior"), row(5, "task"), row(6, "valid")],
            "dbpedia": [row(7, "task", task="dbpedia")]}
        with patch("cell_field_data_v5.prior_identities", return_value=({"prior"}, {})), patch(
                "cell_field_data_v5.corpus_rows", side_effect=lambda _, task: corpus[task]):
            selected, audit = candidates(None, None)
        self.assertEqual([r["source_id"] for r in selected["agnews"]], ["6"])
        self.assertEqual(selected["dbpedia"], [])
        for reason in ("cross_official_split", "class_conflict", "any_prior_identity", "cross_task"):
            self.assertEqual(audit["excluded_counts"][reason], 1)

    def test_only_train_labels_plaintext_and_cipher_authenticates_protocol(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            protocol = root/"protocol.json"
            protocol.write_bytes(canonical({"data_plan": data_plan()}))
            key = b"k"*32
            with patch("cell_field_data_v5.candidates", return_value=({task: fixture_rows(task) for task in DATASETS}, {})):
                prepare(None, None, root/"cohorts", protocol, key)
            for task in DATASETS:
                target = root/"cohorts"/task
                receipt = json.loads((target/"data_receipt.json").read_bytes())
                sources = json.loads((target/"sources.json").read_bytes())["rows"]
                self.assertTrue(all("label" not in row and "text" not in row for row in sources))
                plain = json.loads((target/"train_labels.json").read_bytes())
                self.assertEqual(set(plain["roles"]), {"old_train", "old_probe", "current_train", "current_probe"})
                for access in ("validation", "final"):
                    self.assertFalse((target/(access+"_labels.json")).exists())
                    entry = receipt["sealed_labels"][access]
                    cipher = (target/entry["file"]).read_bytes()
                    aad = canonical(entry["aad"])
                    decoded = AESGCM(key).decrypt(cipher[:12], cipher[12:], aad)
                    self.assertEqual(sha(decoded), entry["aad"]["plaintext_sha256"])
                    self.assertEqual(sha(cipher), entry["sha256"])
                    with self.assertRaises(InvalidTag):
                        AESGCM(key).decrypt(cipher[:12], cipher[12:], aad+b"changed")
                    with self.assertRaises(InvalidTag):
                        AESGCM(b"w"*32).decrypt(cipher[:12], cipher[12:], aad)


if __name__ == "__main__":
    unittest.main()
