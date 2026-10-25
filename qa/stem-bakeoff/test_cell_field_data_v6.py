"""Exclude every prior component and retain authenticated V6 label separation."""

from collections import Counter
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from cell_field_data_v5 import COUNTS, DATASETS, select as prior_select, sha
from cell_field_data_v6 import data_plan, fresh_candidates, prepare, select
from prepare_news_cohorts import canonical


def fixture(task):
    rows = []
    for bucket, count in (("old", 800), ("current", 800), ("future", 400)):
        for label in range(4):
            for i in range(count):
                digest = sha([task, bucket, label, i])
                rows.append({"task_id": task, "source_id": task+":"+digest, "component_id": task+"-group:"+digest,
                    "bucket": bucket, "label": label, "official_split": "test" if bucket == "future" else "train",
                    "source_row_sha256": digest, "text": f"fixture {task} {bucket} {label} {i}"})
    return rows


class DataV6Tests(unittest.TestCase):
    def example(self):
        rows = {task: fixture(task) for task in DATASETS}
        prior = {task: prior_select(values, task)[0] for task, values in rows.items()}
        hashes = {task: sha(sorted(r["component_id"] for r in values)) for task, values in prior.items()}
        return rows, prior, hashes

    def test_exact_reconstructed_prior_identity_precedes_all_role_exclusion(self):
        rows, prior, hashes = self.example()
        with patch("cell_field_data_v6.candidates", return_value=(rows, {})), patch("cell_field_data_v6.V5_COMPONENTS", hashes):
            fresh, audit = fresh_candidates(None, None)
        self.assertEqual(audit["excluded_v5_components_total"], 4608)
        forbidden = {r["component_id"] for values in prior.values() for r in values}
        for task in DATASETS:
            chosen, _ = select(fresh[task], task)
            reverse, _ = select(list(reversed(fresh[task])), task)
            self.assertEqual(chosen, reverse)
            self.assertFalse(forbidden & {r["component_id"] for r in chosen})
            for role, n in COUNTS.items():
                members = [r for r in chosen if r["role"] == role]
                self.assertEqual(Counter(r["label"] for r in members), {c: n//4 for c in range(4)})
                self.assertEqual({r["official_split"] for r in members}, {"test" if role == "future_test" else "train"})
        hashes["agnews"] = "wrong prior cohort"
        with patch("cell_field_data_v6.candidates", return_value=(rows, {})), patch("cell_field_data_v6.V5_COMPONENTS", hashes):
            with self.assertRaisesRegex(ValueError, "reconstructed V5 selection differs"):
                fresh_candidates(None, None)

    def test_v6_encryption_has_no_plaintext_holdout_and_rejects_v5_key(self):
        rows, _, _ = self.example()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            protocol = root/"protocol.json"
            protocol.write_bytes(canonical({"data_plan": data_plan()}))
            with patch("cell_field_data_v6.fresh_candidates", return_value=(rows, {})):
                prepare(None, None, root/"cohorts", protocol, b"6"*32)
            for task in DATASETS:
                target = root/"cohorts"/task
                receipt = json.loads((target/"data_receipt.json").read_bytes())
                train = json.loads((target/"train_labels.json").read_bytes())
                self.assertEqual(set(train["roles"]), {"old_train", "old_probe", "current_train", "current_probe"})
                for access in ("validation", "final"):
                    self.assertFalse((target/(access+"_labels.json")).exists())
                    entry = receipt["sealed_labels"][access]
                    cipher = (target/entry["file"]).read_bytes()
                    plain = AESGCM(b"6"*32).decrypt(cipher[:12], cipher[12:], canonical(entry["aad"]))
                    self.assertEqual(sha(plain), entry["aad"]["plaintext_sha256"])
                    with self.assertRaises(InvalidTag):
                        AESGCM(b"5"*32).decrypt(cipher[:12], cipher[12:], canonical(entry["aad"]))


if __name__ == "__main__":
    unittest.main()
