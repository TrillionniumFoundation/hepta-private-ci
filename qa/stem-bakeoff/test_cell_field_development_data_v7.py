"""Identity reconstruction and empirical-panel boundaries for V7 development."""

from collections import Counter
import csv
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from cell_field_data_v5 import sha
import cell_field_development_data_v7 as data


class DevelopmentDataTests(unittest.TestCase):
    def panels(self):
        sources, labels = [], {}
        for role, count in (("current_probe", 128), ("current_validation", 256), ("future_test", 512)):
            for label in range(4):
                for _ in range(count//4):
                    index = len(sources)
                    source_id = "source:"+str(index)
                    sources.append({"index": index, "source_id": source_id,
                        "component_id": "component:"+str(index), "role": role})
                    labels[source_id] = label
        return sources, labels

    def test_panels_are_balanced_complete_disjoint_and_order_stable(self):
        sources, labels = self.panels()
        panels = data.planning_indices(sources, labels, version="v5", task="agnews", domain="current")
        reversed_panels = data.planning_indices(list(reversed(sources)), labels,
            version="v5", task="agnews", domain="current")
        self.assertEqual([p.tolist() for p in panels], [p.tolist() for p in reversed_panels])
        self.assertEqual(sorted(np.concatenate(panels).tolist()), list(range(384)))
        self.assertEqual([Counter(labels[sources[i]["source_id"]] for i in p) for p in panels],
            [{c: 24 for c in range(4)}]*4)
        self.assertTrue(all(len(p) == 96 for p in panels))

    def test_component_overlap_or_role_leakage_fails(self):
        sources, labels = self.panels()
        sources[1]["component_id"] = sources[0]["component_id"]
        with self.assertRaisesRegex(ValueError, "unique balanced"):
            data.planning_indices(sources, labels, version="v6", task="dbpedia", domain="current")
        sources, labels = self.panels()
        sources[0]["role"] = "future_test"
        with self.assertRaisesRegex(ValueError, "unique balanced"):
            data.planning_indices(sources, labels, version="v6", task="dbpedia", domain="current")

    def archive(self, directory):
        path = Path(directory)/"source.tar.gz"
        values = {"train": [["1", "titleA", "bodyA"], ["4", "titleB", "bodyB"]],
                  "test": [["2", "titleC", "bodyC"]]}
        with tarfile.open(path, "w:gz") as bundle:
            for split, rows in values.items():
                stream = io.StringIO(newline="")
                csv.writer(stream).writerows(rows)
                content = stream.getvalue().encode()
                member = tarfile.TarInfo("fixture/"+split+".csv")
                member.size = len(content)
                bundle.addfile(member, io.BytesIO(content))
        spec = {"bytes": path.stat().st_size, "sha256": sha(path.read_bytes()),
            "prefix": "fixture", "class_count": 4, "train_rows": 2, "test_rows": 1}
        sources, expected = [], {}
        for split, rows in values.items():
            for number, row in enumerate(rows):
                digest = sha(row)
                source_id = "fixture:"+sha([split, number, digest])
                sources.append({"source_id": source_id, "source_row_sha256": digest, "official_split": split})
                expected[source_id] = int(row[0])-1
        return path, spec, sources, expected

    def test_labels_reconstruct_from_exact_source_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path, spec, sources, expected = self.archive(directory)
            with patch.dict(data.DATASETS, {"fixture": spec}):
                self.assertEqual(data.reconstruct_labels(path, "fixture", sources), expected)
                sources[0]["source_row_sha256"] = "0"*64
                with self.assertRaisesRegex(ValueError, "row commitment"):
                    data.reconstruct_labels(path, "fixture", sources)

    def test_changed_archive_or_missing_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path, spec, sources, _ = self.archive(directory)
            with patch.dict(data.DATASETS, {"fixture": spec}):
                sources[0]["source_id"] = "not-in-source"
                with self.assertRaisesRegex(ValueError, "membership"):
                    data.reconstruct_labels(path, "fixture", sources)
                path.write_bytes(path.read_bytes()+b"x")
                with self.assertRaisesRegex(ValueError, "archive identity"):
                    data.reconstruct_labels(path, "fixture", sources)


if __name__ == "__main__":
    unittest.main()
