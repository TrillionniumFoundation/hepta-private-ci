"""Declare consecutive, closed joint output packets when disk space is limited.

This only writes an exact input specification. The sealer must verify a complete
packet before any separate reclaimer may remove its redundant expanded bytes.
Case ordering is fixed by registration and never selected using outcomes.
"""

import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-start", type=int, required=True)
    parser.add_argument("--case-end", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[3]
    phase = Path(__file__).resolve().parent
    raw = Path("/tmp/hepta-ndu-advance-joint")
    run = raw / "confirmation-001"
    protocol_path = phase / "joint/CONFIRMATION_PROTOCOL.json"
    protocol = json.loads(protocol_path.read_text())
    if not 0 <= args.case_start < args.case_end <= protocol["pair_count"]:
        raise ValueError("Packet must be a nonempty consecutive registered range")
    checked = json.loads((run / "CHECKED_RESULT.json").read_text())
    audit = json.loads((run / "COMPLETENESS_AUDIT.json").read_text())
    receipt = raw / "confirmation-001-process/receipt.json"
    if (not checked["audit_passed"] or not audit["passed"]
            or json.loads(receipt.read_text())["returncode"] != 0
            or checked["results_sha256"] != sha(run / "RESULTS.json")
            or checked["audit_sha256"] != sha(run / "COMPLETENESS_AUDIT.json")
            or audit["rows_sha256"] != sha(run / "ROWS.json")
            or audit["protocol_sha256"] != sha(protocol_path)):
        raise ValueError("Packet source is not the completed audited study")
    entries = []

    def add(path):
        if not path.is_file() or path.is_symlink():
            raise ValueError("Missing or symlinked packet input: " + str(path))
        prefix, root = ("raw/joint/", raw) if path.is_relative_to(raw) else ("repository/", repository)
        entries.append({"path": str(path), "name": prefix + path.relative_to(root).as_posix(),
                        "sha256": sha(path)})

    for case in range(args.case_start, args.case_end):
        for route in protocol["routes"]:
            for arm in protocol["arms"]:
                output = run / "raw" / f"case-{case:03}" / route / arm["name"] / "output"
                for name in ("caption.txt", "image.png", "audio.wav", "video.mp4"):
                    add(output / name)
    count = len(entries)
    for name in ("CHECKED_RESULT.json", "COMPLETENESS_AUDIT.json", "RESULTS.json",
                 "ROWS.json", "STARTED.json", "OBSERVER.json"):
        add(run / name)
    for path in sorted((raw / "confirmation-001-process").iterdir()):
        add(path)
    for side in ("before", "after"):
        add(raw / f"confirmation-001-resources-{side}.json")
    add(Path(__file__).resolve())
    value = {
        "study": f"advance-joint-output-cases-{args.case_start:03}-{args.case_end:03}-20261026",
        "description": "Exact generated output partition of a closed study, with complete checked-study receipts. Requires the remaining packets and final custody index for the full study.",
        "generated_output_partition": {"case_start": args.case_start, "case_end": args.case_end,
            "expected_generated_files": count, "total_cases": protocol["pair_count"],
            "selection": "Consecutive registered case indices; no outcome selection"},
        "additional_source_roots": [str(raw)], "trees": [], "files": entries,
        "protocols": [str(protocol_path)], "external_archives": [],
        "external_scope": "Models, remaining outputs, original inputs and prior development are retained separately and will be linked by the complete joint custody index. This packet alone is not the full experiment."
    }
    with args.output.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"specification": str(args.output), "sha256": sha(args.output),
                      "generated_files": count, "input_bytes": sum(Path(x["path"]).stat().st_size for x in entries)}))


if __name__ == "__main__":
    main()
