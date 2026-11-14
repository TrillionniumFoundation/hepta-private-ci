"""Synthetic receipt identity controls; no training or historical attestation."""
import base64
import gzip
import hashlib
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from . import audit_regime_results as subject


def encoded(value):
    return json.dumps(value, sort_keys=True).encode()


def fixture(directory):
    prefix = Path(directory) / "synthetic"
    receipt_dir = Path(str(prefix) + "_receipts")
    receipt_dir.mkdir()
    rows = []
    for seed in range(501, 509):
        panel = dict(prediction=[0.5] * 768, brier=0.25, accuracy=0.0, nll=math.log(2))
        arm = dict(training=dict(parameters=609, updates=1,
                                 training_and_feature_cpu_seconds=2.01),
                   iid=panel, ood=panel)
        rows.append(dict(seed=seed, iid_labels=[0] * 768, ood_labels=[0] * 768,
                         arms=dict(ordinary=arm, call_put_margin_risk=arm)))
    protocol = (Path(subject.__file__).parent / "PROTOCOL_20261031.json").read_bytes()
    seal = hashlib.sha256(protocol).hexdigest()
    raw = encoded(dict(rows=rows, protocol_sha256=seal))
    summary = dict(raw_sha256=hashlib.sha256(raw).hexdigest(), protocol_sha256=seal,
                   per_seed_receipt_sha256={}, exact_two_sided_signflip_p_ood=1.0,
                   mean_ood_brier_improvement=0.0, mean_iid_brier_improvement=0.0)
    for row in rows:
        data = encoded(row)
        (receipt_dir / f"{row['seed']}.json").write_bytes(data)
        summary["per_seed_receipt_sha256"][str(row["seed"])] = hashlib.sha256(data).hexdigest()
    Path(str(prefix) + ".json.gz.b64").write_bytes(base64.b64encode(gzip.compress(raw)))
    Path(str(prefix) + ".json").write_bytes(encoded(summary))
    return prefix, rows, summary


class ReceiptSnapshotTests(unittest.TestCase):
    def test_consistent_synthetic_receipts_keep_gates_closed(self):
        with TemporaryDirectory() as directory:
            prefix, _, _ = fixture(directory)
            result = subject.verify(prefix)
            self.assertEqual(result["seed_count"], 8)
            self.assertEqual(result["audited_predictions"], 8 * 2 * 2 * 768)
            self.assertFalse(result["p1_closed"])
            self.assertFalse(result["p0_p6_closed"])

    def test_path_replacement_cannot_hash_one_receipt_and_parse_another(self):
        with TemporaryDirectory() as directory:
            prefix, rows, summary = fixture(directory)
            target = Path(str(prefix) + "_receipts") / "501.json"
            sealed = encoded({**rows[0], "sealed_only_marker": "different receipt"})
            target.write_bytes(sealed)
            summary["per_seed_receipt_sha256"]["501"] = hashlib.sha256(sealed).hexdigest()
            Path(str(prefix) + ".json").write_bytes(encoded(summary))
            real_read = Path.read_bytes
            reads = []

            def replace_after_read(path):
                data = real_read(path)
                if path == target:
                    reads.append(data)
                    target.write_bytes(encoded(rows[0]))
                return data

            with patch.object(Path, "read_bytes", replace_after_read):
                with self.assertRaises(subject.AuditRefusal):
                    subject.verify(prefix)
            self.assertEqual(reads, [sealed])


if __name__ == "__main__":
    unittest.main()
