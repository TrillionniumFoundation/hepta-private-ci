"""Generated fixtures test admission, never supply scientific task evidence."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from hepta_cells.stem_study_support import prepare, ROUTES


def fixture():
    records = []
    for group in range(7):
        document = hashlib.sha256(f"fixture-document-{group}".encode()).hexdigest()
        for route, name in enumerate(ROUTES):
            h = hashlib.sha256(f"fixture-{group}-{route}".encode()).hexdigest()
            records.append(
                dict(
                    source_group=f"fixture-{group}",
                    split="train" if group < 3 else "dev",
                    candidate_id=name,
                    task_id=name,
                    target=(group + route) % 2,
                    initial_latent=[group, 0],
                    candidate_latent=[group, route + 1],
                    observed_at_us=[100, 100 + (route + 1) * 100_000],
                    replay_exposure_us=[0, (route + 1) * 100_000],
                    receipt_sha256s=[document, h],
                    document_sha256=document,
                    feature_profile_sha256="f" * 64,
                )
            )
    return dict(
        schema="hepta.cell.cord-retained-replay.v1",
        feature_dim=2,
        records=records,
        fresh_confirmation=0,
        source_independence_verified=False,
        fixture_only=True,
    )


class StemStudySupportTests(unittest.TestCase):
    def load(self, value):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fixture.json"
            path.write_text(json.dumps(value))
            return prepare(path)

    def test_equal_information_encoding_and_source_disjointness(self):
        data, _, panels, episodes, flat, contract, normalizer = self.load(fixture())
        np.testing.assert_array_equal(
            flat,
            contract.episodes(episodes, [0] * len(episodes)).reshape(len(episodes), -1),
        )
        groups = [
            {data["records"][i]["source_group"] for i in panels[p]}
            for p in ("train", "B", "C")
        ]
        self.assertEqual([len(g) for g in groups], [3, 2, 2])
        self.assertFalse(
            groups[0] & groups[1] or groups[1] & groups[2] or groups[0] & groups[2]
        )
        changed = fixture()
        for row in changed["records"][9:]:
            row["initial_latent"] = [1000, 2000]
            row["candidate_latent"] = [-1000, -2000]
        self.assertEqual(normalizer, self.load(changed)[-1])

    def test_missing_provenance_changed_clock_and_split_leakage_rejected(self):
        for change in ("provenance", "receipt", "clock", "split"):
            value = copy.deepcopy(fixture())
            if change == "provenance":
                del value["source_independence_verified"]
            elif change == "receipt":
                value["records"][0]["receipt_sha256s"] = []
            elif change == "clock":
                value["records"][0]["replay_exposure_us"][1] += 1
            else:
                value["records"][0]["split"] = "dev"
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.load(value)

    def test_document_aliases_and_changed_initial_receipts_are_rejected(self):
        value = fixture()
        for row in value["records"][9:12]:
            row["document_sha256"] = value["records"][0]["document_sha256"]
        with self.assertRaisesRegex(ValueError, "document reused"):
            self.load(value)
        for key in ("initial_latent", "receipt_sha256s", "feature_profile_sha256"):
            value = fixture()
            value["records"][1][key] = {
                "initial_latent": [99, 99],
                "receipt_sha256s": ["e" * 64, "d" * 64],
                "feature_profile_sha256": "a" * 64,
            }[key]
            with (
                self.subTest(key=key),
                self.assertRaisesRegex(ValueError, "original initial"),
            ):
                self.load(value)


if __name__ == "__main__":
    unittest.main()
