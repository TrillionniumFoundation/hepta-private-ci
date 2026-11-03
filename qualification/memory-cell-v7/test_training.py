"""Training worker boundaries with synthetic exports, not owner authority tests."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

from native_export import export_cell
from training import AssociativeCell, current_rows, train


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def fixture(count=12):
    rows = []
    for index in range(count):
        for kind, value in (
            ("event", index + 3),
            ("semantic", {"factor": index % 4 + 1, "label": f"kind-{index % 4}"}),
            ("procedure", {"opcode": ("affine", "multiply", "clamp")[index % 3], "bias": index % 3, "limit": 90}),
        ):
            rows.append({"source_id": digest(f"{kind}:{index}"), "owner_memory_id": f"owner:{kind}:{index}", "revision": 1,
                         "record": {"schema": "hepta.memory.cell-record.v1", "entity": f"fresh-cell-{index}", "kind": kind, "effective_at": 10, "value": value}})
    return {"schema": "hepta.memory.owner-snapshot.v1", "owner_agent_id": "synthetic-training-boundary-fixture", "scope": "scope:training-boundary", "owner_cut_digest": digest(f"cut:{count}"), "observed_at_unix_seconds": 100, "records": rows, "withdrawn_addresses": [], "current_source_ids": [row["source_id"] for row in rows]}


def request(export, mode="clean", parents=None):
    return {"schema": "hepta.memory.training-request.v1", "export": export, "configuration": {"mode": mode, "seed": 17, "steps": 120, "dimension": 32, "hidden": 16, "threshold": 0.9}, "parents": parents or {}}


class TrainingTests(unittest.TestCase):
    def test_real_training_retains_exact_sources_and_reads_new_values(self):
        export = fixture()
        result = train(request(export))
        for kind, rows in current_rows(export).items():
            original = result["artifacts"][kind]["original"].encode()
            cell = AssociativeCell.from_bytes(original)
            self.assertEqual(export_cell(original), result["artifacts"][kind]["native"].encode())
            self.assertNotEqual(cell.training_receipt["initial_parameters"], cell.parameters_digest())
            self.assertGreater(cell.training_receipt["initial_cross_entropy"], cell.training_receipt["final_cross_entropy"])
            self.assertEqual(cell.lineage_sources, sorted(row["source_id"] for row in rows))
            self.assertEqual([cell.read(row["record"]["entity"])["value"] for row in rows], [row["record"]["value"] for row in rows])
            self.assertEqual(cell.read("unwritten-entity")["support_ids"], [])
        self.assertEqual(result["receipt"]["fit_calls"], 2)

    def test_replay_retains_old_values_and_correction_requires_clean_parameters(self):
        first = train(request(fixture(8)))
        parents = {kind: {"payload": first["artifacts"][kind]["original"], "native_digest": first["receipt"]["types"][kind]["native_digest"]} for kind in ("semantic", "procedure")}
        export = fixture(12)
        replay = train(request(export, "replay", parents))
        for kind, rows in current_rows(export).items():
            cell = AssociativeCell.from_bytes(replay["artifacts"][kind]["original"].encode())
            self.assertEqual([cell.read(row["record"]["entity"])["value"] for row in rows], [row["record"]["value"] for row in rows])
            self.assertEqual(cell.training_receipt["examples_seen"], len(rows) * 120)
        changed = deepcopy(export)
        row = next(row for row in changed["records"] if row["record"]["kind"] == "semantic")
        old_source = row["source_id"]
        row["source_id"], row["revision"] = digest("corrected-source"), 2
        row["record"]["value"] = {"factor": 19, "label": "corrected"}
        changed["current_source_ids"].remove(old_source)
        changed["current_source_ids"].append(row["source_id"])
        with self.assertRaisesRegex(ValueError, "ancestry"):
            train(request(changed, "replay", parents))
        clean = train(request(changed))
        repeat = train(request(changed))
        for kind in ("semantic", "procedure"):
            self.assertEqual(clean["receipt"]["types"][kind]["parameter_digest"], repeat["receipt"]["types"][kind]["parameter_digest"])
            self.assertIsNone(clean["receipt"]["types"][kind]["training"]["parent_parameters"])
        self.assertNotIn(old_source, clean["receipt"]["types"]["semantic"]["current_source_ids"])

    def test_tombstone_future_head_and_duplicate_sources_cannot_enter_training(self):
        export = fixture(2)
        row = next(row for row in export["records"] if row["record"]["kind"] == "semantic")
        export["withdrawn_addresses"].append({"entity": row["record"]["entity"], "kind": "semantic", "effective_at": 20})
        with self.assertRaisesRegex(ValueError, "tombstones"):
            current_rows(export)
        export["current_source_ids"].remove(row["source_id"])
        self.assertEqual(len(current_rows(export)["semantic"]), 1)
        export["records"].append(deepcopy(row))
        with self.assertRaisesRegex(ValueError, "duplicate source"):
            current_rows(export)
        future = fixture(1)
        future["records"][0]["record"]["effective_at"] = 200
        with self.assertRaisesRegex(ValueError, "time"):
            current_rows(future)

    def test_process_binds_exact_input_and_rejects_duplicate_json(self):
        worker = Path(__file__).with_name("training_worker.py")
        raw = json.dumps(request(fixture(3)), ensure_ascii=False).encode()
        process = subprocess.run([sys.executable, str(worker)], input=raw, capture_output=True, timeout=20)
        self.assertEqual(process.returncode, 0, process.stderr.decode())
        result = json.loads(process.stdout)
        self.assertEqual(result["request_digest"], hashlib.sha256(raw).hexdigest())
        invalid = subprocess.run([sys.executable, str(worker)], input=b'{"schema":1,"schema":2}', capture_output=True, timeout=10)
        self.assertEqual((invalid.returncode, invalid.stdout), (2, b""))


if __name__ == "__main__":
    unittest.main()
