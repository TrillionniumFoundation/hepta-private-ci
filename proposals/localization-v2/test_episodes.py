import csv
from datetime import datetime
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from data import LABELS, TAGS, sha
from episodes import load_development, prepare_episodes, read_episodes


class EpisodeTests(unittest.TestCase):
    def test_sealed_subject_is_excluded_before_label_coordinate_clock_parsing(self):
        calendar = (datetime(2026, 1, 1).toordinal() - 1) * 86400 * 10000000
        text = io.StringIO()
        writer = csv.writer(text)
        for subject in "ABCD":
            for i in range(1, 6):
                writer.writerow(
                    [
                        f"{subject}0{i}",
                        TAGS[0],
                        calendar,
                        "01.01.2026 02:00:00:000",
                        1,
                        2,
                        3,
                        LABELS[0],
                    ]
                )
        writer.writerow(
            [
                "E01",
                "invalid",
                "sealed",
                "sealed",
                "sealed",
                "sealed",
                "sealed",
                "sealed",
            ]
        )
        raw, description = text.getvalue().encode(), b"fixture"
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "fixture.zip"
            with ZipFile(archive, "w") as zipped:
                zipped.writestr("ConfLongDemo_JSI.txt", raw)
                zipped.writestr("dataSetDescription.names", description)
            with (
                patch("episodes.ARCHIVE_SHA", sha(archive.read_bytes())),
                patch("episodes.DATA_SHA", sha(raw)),
                patch("episodes.DESCRIPTION_SHA", sha(description)),
            ):
                groups = load_development(archive)
            self.assertEqual(
                set(groups), {f"{s}0{i}" for s in "ABCD" for i in range(1, 6)}
            )

    def test_subject_fit_full_coverage_boundary_gaps_and_tamper_rejection(self):
        groups = {
            f"{s}0{j}": [
                (
                    i * 100000,
                    i % 4,
                    float(i),
                    2.0,
                    3.0,
                    i % 11,
                    ((ord(s) - 65) * 5 + j) * 10000 + i + 1,
                )
                for i in range(800)
            ]
            for s in "ABCD"
            for j in range(1, 6)
        }
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("episodes.load_development", return_value=groups),
        ):
            root = Path(directory)
            prepare_episodes("unused", root / "first")
            original_frontend = (root / "first/frontend.json").read_bytes()
            for sequence in groups:
                if sequence.startswith("D"):
                    groups[sequence] = [
                        (r[0], r[1], 1e9, 1e9, 1e9, r[5], r[6])
                        for r in groups[sequence]
                    ]
            prepare_episodes("unused", root / "second")
            self.assertEqual(
                original_frontend, (root / "second/frontend.json").read_bytes()
            )
            prepared = root / "first"
            digest = sha((prepared / "data-manifest.json").read_bytes())
            episodes, _, manifest = read_episodes(prepared, digest)
            self.assertEqual(
                {p: len(v) for p, v in episodes.items()}, {"train": 45, "dev": 15}
            )
            for entries in episodes.values():
                all_rows = [row for entry in entries for row in entry["source_rows"]]
                self.assertEqual(len(all_rows), len(set(all_rows)))
                for entry in entries:
                    self.assertEqual(entry["dt"][0], 0.01 if entry["start"] else 0.0)
            first = prepared / manifest["episodes"][0]["path"]
            first.write_text(
                first.read_text().replace('"partition": "train"', '"partition": "dev"')
            )
            with self.assertRaisesRegex(ValueError, "changed after preparation"):
                read_episodes(prepared, digest)
            prepare_episodes("unused", root / "all", mode="all-development")
            selection = json.loads((root / "all/selection.json").read_text())
            selected = [row for entry in selection for row in entry["source_rows"]]
            self.assertEqual(
                sorted(selected),
                sorted(r[6] for entries in groups.values() for r in entries),
            )


if __name__ == "__main__":
    unittest.main()
