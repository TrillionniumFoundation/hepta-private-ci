"""Custody regressions for audit-only records; no generation-quality claims."""

import json
from pathlib import Path
import tempfile
import unittest

from .completed_owner_fixture import canonical, request_wire_digest, sha, verify_completed_replay


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical(value) + "\n")


def audit_fixture(root):
    run, output = root / "run", root / "owner"
    run.mkdir()
    (run / "caption.txt").write_bytes(b"original text")
    (run / "image.png").write_bytes(b"original bytes, audit fixture only")
    pins = {k: "a" * 64 for k in ("checkpoint_sha256", "snapshot_sha256", "parameters_sha256",
                                "config_sha256", "source_sha256", "python_sha256", "device_sha256")}
    pins.update(runtime_versions=["fixture"] * 4, hidden=96)
    request = {"schema": "hepta.inference.generation.v1", "request_id": "fixture.audit",
               "objective_sha256": "b" * 64, "input_source_sha256": "c" * 64, "model": pins,
               "required_modalities": 3, "pixels_f32": [0], "mask_f32": [0], "text_tokens": [0],
               "noise_seed": 1, "content_control": True, "actions": ["couple"]}
    row = {"seed": 17, "training": "terminal_entropic_ndu", "case_id": "future-0", "policy": "risk_aware_recursive",
           "snapshot_file_sha256": pins["checkpoint_sha256"], "snapshot_sha256": pins["snapshot_sha256"],
           "actions": request["actions"], "final_state_sha256": "d" * 64,
           "output_paths": {"image": "image.png", "text": "caption.txt"},
           "output_hashes": {"image": sha((run / "image.png").read_bytes()), "text": sha(b"original text")},
           "cost": {"wall_ns": 100}}
    row["receipt_sha256"] = sha(canonical(row).encode())
    (run / "rows.jsonl").write_text(canonical(row) + "\n")
    rows_pin = sha((run / "rows.jsonl").read_bytes())
    protocol = {"scope": "synthetic audit regression only"}
    summary = {"protocol_sha256": sha(canonical(protocol).encode()), "rows": 1,
               "checkpoint_files": {"seed-17-terminal_entropic_ndu": {"snapshot_file_sha256": pins["checkpoint_sha256"]}}}
    status = {"state": "completed", "rows": 1, "summary_sha256": sha(canonical(summary).encode())}
    for name, value in (("protocol", protocol), ("summary", summary), ("status", status)):
        write(run / f"{name}.json", value)
    provenance = {"source_run": str(run), "source_rows_sha256": rows_pin,
                  "source_row": row, "row_receipt_sha256": row["receipt_sha256"],
                  "summary_sha256": status["summary_sha256"], "protocol_sha256": summary["protocol_sha256"]}
    write(output / "provenance.json", provenance)
    write(output / "controlled/fixture.json", {"pins": pins, "request": request})
    execution = {"authority": "deny_all", "model": pins, "request_sha256": request_wire_digest(request),
                 "states": [{"backend_state_sha256": "0" * 64}, {"backend_state_sha256": row["final_state_sha256"]}],
                 "caption": "original text", "png": list((run / "image.png").read_bytes()),
                 "png_sha256": row["output_hashes"]["image"], "text_sha256": row["output_hashes"]["text"],
                 "wall_ns": 200, "cpu_ns": 190, "peak_rss_bytes": 1000}
    process = {"exit_code": 0, "timed_out": False, "stdout_truncated": False, "stderr_truncated": False,
               "authority": "deny_all", "model": pins, "execution": execution,
               "request_sha256": execution["request_sha256"], "stdout": list(canonical(execution).encode()), "host_wall_ns": 300}
    write(output / "controlled/owner-evidence-test/execution.json", process)
    return output, rows_pin


class CompletedOwnerAuditTests(unittest.TestCase):
    def test_original_membership_request_and_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            output, pin = audit_fixture(Path(directory))
            report = verify_completed_replay(output, pin)
            self.assertTrue(report["unique_original_row_membership_verified"])
            self.assertEqual(report["new_scientific_samples"], 0)

    def test_self_resealed_foreign_row_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            output, pin = audit_fixture(Path(directory))
            path = output / "provenance.json"
            value = json.loads(path.read_text())
            row = value["source_row"]
            row.pop("receipt_sha256")
            row["cost"]["wall_ns"] += 1
            row["receipt_sha256"] = sha(canonical(row).encode())
            value["row_receipt_sha256"] = row["receipt_sha256"]
            write(path, value)
            with self.assertRaisesRegex(ValueError, "Unique original row membership"):
                verify_completed_replay(output, pin)

    def test_changed_public_input_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            output, pin = audit_fixture(Path(directory))
            path = output / "controlled/fixture.json"
            value = json.loads(path.read_text())
            value["request"]["pixels_f32"][0] = 1
            write(path, value)
            with self.assertRaisesRegex(ValueError, "Complete request wire binding"):
                verify_completed_replay(output, pin)

    def test_independent_row_log_pin_cannot_be_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            output, _ = audit_fixture(Path(directory))
            with self.assertRaisesRegex(ValueError, "Independent completed rows pin"):
                verify_completed_replay(output, "f" * 64)


if __name__ == "__main__":
    unittest.main()
