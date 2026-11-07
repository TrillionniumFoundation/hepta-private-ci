"""Freeze an attachment inventory; no archive/gate result is inferred here."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def main():
    groups = [
        ("source53-r30-independent-closure", "reviews/differentiation"),
        ("source53-r30-root-review", "reviews/root"),
        ("source53-r30-independent-static-review", "reviews/project-static"),
        ("source53-r30-binding-independent-review", "reviews/project-binding"),
        ("source53-native-gates-preparation", "preparation/project"),
        ("source53-r30-binding", "preparation/project-binding"),
        ("r30-export-preparation", "preparation/export"),
        ("r30-export-binding", "preparation/export-binding"),
        ("r30-export-independent-static-review", "reviews/export-static"),
        ("r30-export-root-review", "reviews/export-root"),
        ("native-validation-results/r30-export-closed", "export-closure"),
    ]
    entries = []
    for directory, destination in groups:
        base = ROOT / directory
        assert base.is_dir() and not base.is_symlink(), directory
        for path in sorted(base.rglob("*")):
            assert not path.is_symlink(), str(path)
            if path.is_file():
                assert "__pycache__" not in path.parts and path.suffix != ".pyc"
                entries.append({"source": str(path.relative_to(ROOT)),
                                "destination": destination + "/" + str(path.relative_to(base)),
                                **pin(path.read_bytes())})
    for filename in ("LOCAL-READBACK.json", "R30-INPUT-PINS.json"):
        path = ROOT / "native-validation-results/r30-closed-input" / filename
        entries.append({"source": str(path.relative_to(ROOT)), "destination": "native-readback/" + filename,
                        **pin(path.read_bytes())})
    for path in sorted((ROOT / "native-validation-results/r30-closed-input/transport").glob("*.json")):
        entries.append({"source": str(path.relative_to(ROOT)), "destination": "transport/" + path.name,
                        **pin(path.read_bytes())})
    original_failure = ROOT / "hepta-cell/qualification/cell-unification-20261106/native-evidence/r29-workspace-checkpoint/original/failure-blocks/failure-1.txt"
    raw = original_failure.read_bytes()
    assert pin(raw)["sha256"] == "8ee31a66c57a0ab48bc30ccfe78cb9a475829bf5a31738863d19be45897b400c"
    entries.append({"source": str(original_failure.relative_to(ROOT)),
                    "destination": "historical-comparison/source52-r29-bedrock-failure.txt", **pin(raw)})
    assert len({entry["destination"] for entry in entries}) == len(entries)
    assert all("r31" not in entry["destination"].lower() for entry in entries)
    original_dir = ROOT / "native-validation-results/r30-closed-input/evidence"
    originals = [{"name": path.name, **pin(path.read_bytes())} for path in sorted(original_dir.iterdir()) if path.is_file()]
    assert len(originals) == 20
    result = {
        "schema": "hepta.source53-r30-formal-preparation-plan.v1",
        "classification": "PREPARATION_ONLY_ARCHIVE_LOCAL_VERIFICATION_PENDING",
        "formal_directory": "hepta-cell/qualification/cell-unification-20261106/native-evidence/r30-project-checkpoint",
        "source_commit": "f74be175de66a4b351cd239d39d98cd34fe9cc1b",
        "source_tree": "440d4a8e09af4009e4d9ea067388826308da8803",
        "source_count": 197,
        "gate_job_id": "1a1b25b399f-fc05-7daa",
        "diagnostic_only": True, "behavior_repair_claimed": False,
        "full_archive": None, "full_archive_locally_verified": False,
        "members_count": None, "index_rows_count": None,
        "static_inputs": sorted(entries, key=lambda entry: entry["destination"]),
        "static_input_count": len(entries), "static_input_bytes": sum(entry["bytes"] for entry in entries),
        "closed_original_pins": originals,
        "archive_policy": {
            "complete_archive_and_original_index_preserved": True,
            "all_non_source_members_copied_with_exact_source_mapping": True,
            "source_members_retained_in_full_archive_not_reduplicated_as_files": True,
            "large_utf8_copies_may_use_deterministic_gzip_with_exact_roundtrip": True,
            "raw_input_pins_retained_separately_from_compressed_copy_pins": True,
            "new_binary_plan_only_no_upload_or_ledger_registration": True
        },
        "remaining_inputs_before_assemble": [
            "Root's unique full archive download and exact archive bytes/SHA256/Git-blob pin.",
            "Root's actual archive custody/readback attachments, if supplied before seal."
        ],
        "r31_result_included": False, "workspace_pass_claimed": False,
        "science": "HOLD", "authority": "DENY_ALL",
        "canonical_reports_index_ledger_or_existing_formal_groups_modified": False,
        "native_rust_or_exporter_executed": False
    }
    raw = (json.dumps(result, indent=2, ensure_ascii=False) + "\n").encode()
    with (OUT / "PREPARATION-PLAN.json").open("xb") as stream:
        stream.write(raw)
    print(json.dumps({"path": "PREPARATION-PLAN.json", **pin(raw), "static_input_count": len(entries)}))


if __name__ == "__main__":
    main()
