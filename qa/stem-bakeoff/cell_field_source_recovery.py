"""Reconstruct only v1 source metadata and authenticate its published identity.

The original receipt contains runtime measurements that cannot be recreated.
This procedure never fabricates that receipt or reads either final-label file.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from cell_field_data import SCHEMA, build_cohorts, sha
from prepare_news_cohorts import COUNTS, _read_archive, canonical, normalized_title, select_rows


SEAL_SHA256 = "68c5b247fa399901fea32076e11ed0a4a5149cbd52ba3690ff1bdc09adf66549"
SOURCES = {"sha256": "d3d8c203c2fd88966fa937d0e0b5cf2826399f558a26dc1e256e47ab479a0482", "bytes": 315623}
RECEIPT = {"sha256": "57742ed6e70c5c33053e4092bc3f58d46f791e84ffedb2efe79fd187e2e707ea", "bytes": 4055}


def recover(archive, seal, output):
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=False)
    seal_bytes = Path(seal).read_bytes()
    saved = json.loads(seal_bytes)
    if (sha(seal_bytes) != SEAL_SHA256
            or saved["files"]["inputs/sources.json"] != SOURCES
            or saved["files"]["inputs/data_receipt.json"] != RECEIPT
            or saved.get("final_labels_opened") is not False):
        raise ValueError("published v1 seal is not the pinned source commitment")
    rows = _read_archive(archive)
    selected, audit = build_cohorts(rows, select_rows(rows, COUNTS))
    sources = []
    for index, item in enumerate(selected):
        row = item["row"]
        sources.append({"index": index, "source_id": "uci-news:" + row["source_id"],
            "raw_source_id": row["source_id"], "component_id": item["component_id"],
            "month": item["month"], "role": item["role"], "timestamp_ms": row["timestamp_ms"],
            "source_row_sha256": row["source_row_sha256"],
            "normalized_title_sha256": sha(normalized_title(row["text"]).encode()),
            "publisher_sha256": sha(normalized_title(row["publisher"]).encode()),
            "component_member_count": len(item["members"]), "component_members_sha256": sha(item["members"])})
    payload = canonical({"schema": SCHEMA, "rows": sources}) + b"\n"
    actual = {"sha256": sha(payload), "bytes": len(payload)}
    if actual != SOURCES or len(sources) != 512 or len({s["component_id"] for s in sources}) != 512:
        (destination / "reconstruction_failure.json").write_bytes(canonical({
            "expected": SOURCES, "actual": actual, "selected_rows": len(sources)}) + b"\n")
        raise ValueError("reconstructed source bytes differ from the original published commitment")
    (destination / "sources.json").write_bytes(payload)
    (destination / "pre_evaluation_seal.json").write_bytes(seal_bytes)
    report = {"schema": "hepta.cell-field-v1-source-recovery.v1",
        "at_utc": datetime.now(timezone.utc).isoformat(), "mode": "published_pre_evaluation_seal",
        "published_evidence_commit": "ff5baef731f36420370c5bcc049c50a567cda06a",
        "seal_sha256": SEAL_SHA256, "sources": SOURCES, "original_receipt_commitment": RECEIPT,
        "original_receipt_restored": False, "original_receipt_fabricated": False,
        "source_bytes_identical_to_published_commitment": True, "verified_components": 512,
        "reason": "runtime reset; binary archive unavailable through current connector; source-only exact reconstruction",
        "method": "pinned v1 cohort selection plus exact sources serialization; reject any SHA or size mismatch",
        "source_archive_sha256": sha(Path(archive).read_bytes()),
        "code_sha256": {name: sha(Path(__file__).with_name(name).read_bytes()) for name in
                        ("cell_field_source_recovery.py", "cell_field_data.py", "prepare_news_cohorts.py")},
        "raw_source_rows": audit["raw_rows"], "raw_source_components": audit["raw_components"],
        "final_label_file_opened": False, "model_outputs_observed": False}
    (destination / "reconstruction.json").write_bytes(canonical(report) + b"\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "seal", "output"):
        parser.add_argument("--" + name, required=True)
    print(json.dumps(recover(**vars(parser.parse_args())), indent=2))
