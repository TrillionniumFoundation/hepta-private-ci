"""Exercise real files and archive roundtrips without training a model."""

import copy
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

import numpy as np

import archive

RECORDS = []
ARCHIVES = {}


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True) + "\n")


def fixture(root, indexed=True):
    sealed = {}
    for i in range(12):
        folder = root / f"cell-{i}"
        folder.mkdir()
        history = []
        for step in (1, 2, 3):
            weights = folder / f"step{step}.pt"
            weights.write_bytes(f"engineering fixture weights {i} {step}".encode())
            history.append(dict(file=weights.name, sha256=archive.sha(weights)))
        write_json(
            folder / "progress.json", dict(optimization_wall=3150, history=history)
        )
        sealed[folder.name] = dict(
            best=history[2], gates={"4.1": history[0], "3.6": None}
        )
        index = {}
        scored = (history[2], history[0]) if indexed else (history[2],)
        for row in scored:
            arrays = dict(
                ids=np.array(["row-a", "row-b"]),
                y=np.array([0, 1]),
                scores=np.arange(4, dtype=np.float32).reshape(2, 2) + i,
            )
            if row == history[2]:
                arrays["no_wire_scores"] = arrays["scores"] / 2
            index[row["file"]] = archive.retain_cold_scores(
                folder, row, arrays, best=row == history[2]
            )
        if indexed:
            archive.retain_cold_index(folder, index)
        else:
            for row in index.values():
                (folder / row["file"]).unlink()
    for name in ("sessions.jsonl", "segments.jsonl", "events.jsonl"):
        (root / name).write_text("{}\n")
    write_json(root / "seal.json", sealed)
    terminal = dict(
        seal_sha256=archive.sha(root / "seal.json"), cells={key: {} for key in sealed}
    )
    if indexed:
        terminal["cold_evidence_schema"] = archive.COLD_SCHEMA
    write_json(root / "terminal.json", terminal)
    return sealed


class RetentionTests(unittest.TestCase):
    def test_complete_actual_file_archive_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            root.mkdir()
            fixture(root)
            files = archive.inventory(root, "run")
            originals = {str(p.relative_to(root)): archive.sha(p) for p in files}
            payload = io.BytesIO()
            with tarfile.open(fileobj=payload, mode="w:gz") as bundle:
                for path in files:
                    bundle.add(path, arcname=path.relative_to(root), recursive=False)
            restored = Path(tmp) / "restored"
            with tarfile.open(
                fileobj=io.BytesIO(payload.getvalue()), mode="r:gz"
            ) as bundle:
                bundle.extractall(restored, filter="data")
            observed = {
                str(p.relative_to(restored)): archive.sha(p)
                for p in archive.inventory(restored, "run")
            }
            self.assertEqual(observed, originals)
            ARCHIVES["roundtrip.tar.gz"] = payload.getvalue()
            RECORDS.append(
                dict(
                    control="archive_roundtrip",
                    members=len(originals),
                    archive_bytes=len(payload.getvalue()),
                    archive_sha256=hashlib.sha256(payload.getvalue()).hexdigest(),
                    member_sha256=originals,
                    mismatches=0,
                )
            )
            for i in range(12):
                folder = restored / f"cell-{i}"
                for step in (1, 2, 3):
                    self.assertTrue((folder / f"step{step}.pt").is_file())
                for step in (1, 3):
                    with np.load(
                        folder / f"cold-step{step}.npz", allow_pickle=False
                    ) as values:
                        np.testing.assert_array_equal(values["y"], [0, 1])
                        np.testing.assert_array_equal(
                            values["scores"], np.arange(4).reshape(2, 2) + i
                        )

    def test_missing_or_changed_sealed_objects_refuse(self):
        for change in (
            "missing_scores",
            "corrupt_scores",
            "missing_gate_index",
            "missing_whole_index",
            "removed_schema_and_index",
            "wrong_checkpoint",
        ):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                fixture(root)
                folder = root / "cell-0"
                index = archive.read(folder / "cold_index.json")
                if change == "missing_scores":
                    (folder / "cold-step1.npz").unlink()
                elif change == "corrupt_scores":
                    (folder / "cold-step1.npz").write_bytes(b"changed")
                elif change == "missing_gate_index":
                    del index["step1.pt"]
                    write_json(folder / "cold_index.json", index)
                elif change == "missing_whole_index":
                    (folder / "cold_index.json").unlink()
                elif change == "removed_schema_and_index":
                    (folder / "cold_index.json").unlink()
                    terminal = archive.read(root / "terminal.json")
                    del terminal["cold_evidence_schema"]
                    write_json(root / "terminal.json", terminal)
                else:
                    index["step1.pt"]["checkpoint_sha256"] = index["step3.pt"][
                        "checkpoint_sha256"
                    ]
                    write_json(folder / "cold_index.json", index)
                with self.assertRaises((ValueError, FileNotFoundError)) as refused:
                    archive.inventory(root, "run")
                RECORDS.append(dict(control=change, refusal=str(refused.exception)))

    def test_seal_cannot_select_a_checkpoint_outside_verified_history(self):
        for change in ("changed_gate_digest", "shadowed_best_digest"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                changed = copy.deepcopy(fixture(root))
                if change == "changed_gate_digest":
                    changed["cell-0"]["gates"]["4.1"]["sha256"] = "0" * 64
                else:
                    changed["cell-0"]["gates"]["4.1"] = copy.deepcopy(
                        changed["cell-0"]["best"]
                    )
                    changed["cell-0"]["best"]["sha256"] = "0" * 64
                    folder = root / "cell-0"
                    index = archive.read(folder / "cold_index.json")
                    del index["step1.pt"]
                    write_json(folder / "cold_index.json", index)
                write_json(root / "seal.json", changed)
                terminal = archive.read(root / "terminal.json")
                terminal["seal_sha256"] = archive.sha(root / "seal.json")
                write_json(root / "terminal.json", terminal)
                with self.assertRaisesRegex(ValueError, "verified history") as refused:
                    archive.inventory(root, "run")
                RECORDS.append(dict(control=change, refusal=str(refused.exception)))

    def test_legacy_keeps_originals_without_inventing_missing_scores(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root, indexed=False)
            with self.assertRaisesRegex(ValueError, "pinned collector"):
                archive.inventory(root, "run")
            recovery = archive.legacy_inventory(root)
            self.assertEqual(recovery["status"], "UNKNOWN")
            self.assertFalse(recovery["complete"])
            observed = {str(p.relative_to(root)) for p in recovery["files"]}
            for i in range(12):
                self.assertIn(f"cell-{i}/step1.pt", observed)
                self.assertIn(f"cell-{i}/step2.pt", observed)
                self.assertIn(f"cell-{i}/cold.npz", observed)
                self.assertFalse((root / f"cell-{i}/cold_index.json").exists())
                self.assertFalse((root / f"cell-{i}/cold-step1.npz").exists())
            RECORDS.append(
                dict(
                    control="legacy_recovery",
                    status=recovery["status"],
                    complete=recovery["complete"],
                    members=len(observed),
                    missing_gate_scores_created=False,
                )
            )

    def test_resume_is_idempotent_and_conflicting_bytes_survive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = dict(file="step7.pt", sha256="1" * 64)
            arrays = dict(scores=np.array([[0.2, 0.8]], dtype=np.float32))
            first = archive.retain_cold_scores(root, row, arrays, best=True)
            self.assertEqual(
                archive.retain_cold_scores(root, row, arrays, best=True), first
            )
            with self.assertRaisesRegex(ValueError, "bytes changed"):
                archive.retain_cold_scores(
                    root, row, dict(scores=np.array([[0.8, 0.2]]))
                )
            self.assertEqual(archive.sha(root / first["file"]), first["sha256"])
            self.assertEqual(archive.sha(root / "cold.npz"), first["sha256"])
            self.assertFalse(list(root.glob(".cold-*")))


if __name__ == "__main__":
    unittest.main()
