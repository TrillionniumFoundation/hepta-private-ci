"""Real pinned resident-process execution, not native product or efficacy evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from hepta_retrieval_wire import decode_reply, decode_request, encode_request
from laya_binary import OwnerDeadline
from laya_resident import ResidentLaya
from laya_retrieval import digest, encoded
from laya_smoke import binary_request


def run(root: Path) -> dict:
    prepared = json.loads((root / "run.json").read_text())
    tested = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], text=True).strip()
    if (not prepared["success"] or tested != prepared["tested_sha"]
            or tree != prepared["tested_tree"]
            or prepared["source_sha"] != os.environ.get("SOURCE_SHA", tested)):
        raise ValueError("prepared model evidence belongs to another candidate")
    pins = json.loads((root / "pins.json").read_text())
    report = {
        "schema": "hepta.laya.resident-smoke.v1", "success": False,
        "source_sha": prepared["source_sha"], "tested_sha": tested, "tested_tree": tree,
        "bundle_digest": digest(pins), "observations": [],
        "production_composition": False, "held_out_efficacy": False,
        "independent_acceptance": False, "artifact_adoption": False,
        "synthetic_task": True,
    }
    started = time.monotonic()
    session = ResidentLaya(root / "checkpoint", root / "pins.json", maximum_operations=4)
    try:
        for index in range(2):
            request = decode_request(binary_request(digest(pins), int(time.time() * 1000 + 60000)))
            request["operation_id"] = f"qualification.laya.resident.{index}"
            wire = encode_request(request)
            result = session.predict(wire, OwnerDeadline.start(request["deadline_ms"]))
            reply = decode_reply(result.wire, wire)
            if not result.observation["eligible_reply"] or reply["input_tokens"] <= 0 or reply["output_tokens"] != 0:
                raise ValueError("missing actual resident inference observation")
            report["observations"].append({
                "operation_id": request["operation_id"],
                "request_sha256": hashlib.sha256(wire).hexdigest(),
                "reply_sha256": hashlib.sha256(result.wire).hexdigest(),
                "decoded_reply": reply, "transport": result.observation,
            })
        first, second = report["observations"]
        if (first["transport"]["process_id"] != second["transport"]["process_id"]
                or second["transport"]["completed_exchanges"] != 2
                or first["request_sha256"] == second["request_sha256"]):
            raise ValueError("resident reuse or distinct-request evidence missing")
        report["close"] = session.close()
        if not report["close"]["direct_child_reaped"]:
            raise ValueError("resident leader cleanup unresolved")
        report["success"] = True
    except BaseException as error:
        report["error_type"] = type(error).__name__
        raise
    finally:
        # Finalizer faults must still retain the partial report and exact identity.
        try:
            report["close"] = session.close()
        except BaseException as error:
            report["success"] = False
            report["cleanup_error_type"] = type(error).__name__
            raise
        finally:
            report["total_seconds"] = time.monotonic() - started
            (root / "resident-report.json").write_bytes(encoded(report) + b"\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", required=True, type=Path)
    args = parser.parse_args()
    report = run(args.prepared.resolve())
    print(json.dumps({"success": report["success"], "resident_replies": len(report["observations"])}))


if __name__ == "__main__":
    main()
