#!/usr/bin/env python3
"""Pin closed local originals for the new finalization formal group.

No native, network, Git, formatter, compiler or test command is run. The separate
assembler consumes the emitted complete map only after both deep readbacks exist.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
NATIVE = ROOT / "native-validation-results/source53-finalization-closed"
ARCHIVES = ROOT / "native-validation-results/source53-finalization-archives"


def require(value, message):
    if not value:
        raise ValueError(message)


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def read(path, expected=None):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "missing/nonregular " + str(path))
    raw = path.read_bytes()
    actual = pin(raw)
    if expected:
        require(all(actual[key] == expected[key] for key in actual if key in expected), "pin mismatch " + str(path))
    return raw


def safe(value):
    p = PurePosixPath(value)
    require(value and not p.is_absolute() and ".." not in p.parts and "\\" not in value and str(p) == value,
            "unsafe relative path " + str(value))
    return value


def record(path, expected=None):
    raw = read(path, expected)
    return {"path": str(path.relative_to(ROOT)), **pin(raw)}


def row_path(directory, row):
    name = safe(row["path"])
    direct = ROOT / name
    local = directory / name
    prefix = str(directory.relative_to(ROOT)) + "/"
    path = direct if name.startswith(prefix) else local
    require(path.is_relative_to(directory), "handoff escapes group")
    read(path, row)
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--peer-handoff", help="Exact full independent finalization readback handoff")
    parser.add_argument("--registration", help="Exact root post-format registration binding and file map")
    parser.add_argument("--output", default="KNOWN-SUPPORT-COPY-PLAN.json")
    args = parser.parse_args()
    output = HERE / safe(args.output)
    require(not output.exists(), "create-only output exists")
    config = json.loads(read(HERE / "FUTURE-BINDINGS.json"))
    config["native_complete_directory"] = str((NATIVE / "evidence").relative_to(ROOT))
    native_handoff_raw = read(NATIVE / "HANDOFF-MANIFEST.json", {"bytes": 14983,
        "sha256": "2e18c7983fab19f809f01e4764dcd140204ebdea6153bab1c546b9f275fa0c68"})
    handoff = json.loads(native_handoff_raw)
    for row in handoff["originals"]:
        read(NATIVE / safe(row["path"]), row)
    for key in ("readback", "warnings", "verifier"):
        read(NATIVE / safe(handoff[key]["path"]), handoff[key])
    evidence = [row for row in handoff["originals"] if row["path"].startswith("evidence/")]
    require(len(evidence) == handoff["native_evidence_files"] == 24, "actual evidence set mismatch")
    config["native_complete_directory_file_pins"] = [dict(row, path=row["path"].split("/", 1)[1]) for row in evidence]
    complete = json.loads(read(NATIVE / "evidence/complete.json"))
    config["archive_files"] = []
    for key, label in (("tested", "tested-pre-fix-source"), ("after_fix", "post-fix-source"),
                       ("after_format", "final-post-format-source")):
        path = ARCHIVES / label / (label + ".tar.gz")
        config["archive_files"].append({**record(path, complete[key]["archive"]), "output_name": path.name})
    for key, name in (("terminal", "terminal-process-status-original.json"),
                      ("controller_launch", "launch-original.json"),
                      ("controller_stdout", "original-stdout.log"),
                      ("controller_stderr", "original-stderr.log")):
        config[key] = record(NATIVE / "controller" / name)
    collections, group_summary = [], []

    def group(destination, directory, paths):
        unique = sorted(set(paths))
        rows = [{**record(path), "relative_destination": str(path.relative_to(directory))} for path in unique]
        require(rows, "empty support group " + destination)
        collections.append({"destination": destination, "files": rows})
        group_summary.append({"destination": destination, "file_count": len(rows), "bytes": sum(r["bytes"] for r in rows)})

    def from_handoff(name, destination):
        directory = ROOT / name
        source = directory / "HANDOFF-MANIFEST.json"
        manifest = json.loads(read(source))
        paths = [row_path(directory, row) for row in manifest["files"]]
        paths.append(source)
        group(destination, directory, paths)

    for name, destination in (
        ("source53-finalize-preparation", "support/template-preparation"),
        ("source53-finalizer-independent-static-review", "support/static-independent"),
        ("source53-finalize-binding", "support/actual-binding"),
        ("source53-finalizer-binding-independent-review", "support/binding-independent"),
        ("source53-final-scope-preparation", "support/fresh-scope"),
        ("source53-final-scope-independent-review", "support/scope-independent"),
        ("source53-formatter-inventory-actual-independent-review", "support/inventory-independent"),
    ):
        from_handoff(name, destination)
    for name, destination, selected in (
        ("source53-finalize-root-review", "support/root-authorization-and-binding",
         ["STATIC-REVIEW.json", "ACTUAL-BINDING-READBACK.json", "ACTUAL-SCOPE-UPLOAD-READBACK.json",
          "ROOT-SCOPE-UPLOAD-AUTHORIZATION.json", "ROOT-EXECUTION-AUTHORIZATION.json"]),
        ("source53-final-scope-root-review", "support/scope-root",
         ["ROOT-READBACK.json", "verify.py", "verify_v2.py", "PREPARATION-CORRECTION.json"]),
        ("source53-formatter-inventory-root-review", "support/inventory-root",
         ["STATIC-REVIEW.json", "BINDING-READBACK.json", "ROOT-EXECUTION-AUTHORIZATION.json", "ACTUAL-INVENTORY-READBACK.json"]),
        ("source53-finalization-root-review", "support/root-complete-readback",
         ["ROOT-COMPLETE-READBACK.json", "verify_complete.py"]),
    ):
        directory = ROOT / name
        group(destination, directory, [directory / path for path in selected])
    read(ROOT / "source53-finalization-root-review/ROOT-COMPLETE-READBACK.json",
         {"bytes": 7474, "sha256": "fe3dd7179578744282c26b94ea5e2a6a4882430f41b0ec1f52455a19451e952b"})
    for name, destination in (
        ("source53-formatter-tool-inventory-closed", "original/tool-inventory"),
        ("source53-finalizer-scope-upload-closed", "original/scope-upload"),
    ):
        directory = ROOT / "native-validation-results" / name
        local = directory / "LOCAL-READBACK.json"
        inventory = json.loads(read(local))
        rows = inventory["files"]
        paths = [row_path(directory, row) for row in rows]
        group(destination, directory, paths + [local])
    native_extra = [NATIVE / row["path"] for row in handoff["originals"] if not row["path"].startswith("evidence/")]
    native_extra += [NATIVE / "HANDOFF-MANIFEST.json", NATIVE / "LOCAL-READBACK.json", NATIVE / "WARNINGS-READBACK.json", NATIVE / "verify_closed.py"]
    group("original/native-custody", NATIVE, native_extra)
    transfers = [ARCHIVES / "ROOT-TRANSFER-READBACK.json", ARCHIVES / "EXPECTED-ARCHIVE-SPECS.json"]
    for label in ("tested-pre-fix-source", "post-fix-source", "final-post-format-source"):
        transfers += [ARCHIVES / label / "FILE-INFO-ORIGINAL.json", ARCHIVES / label / "TRANSFER-READBACK.json"]
    group("original/archive-transfer-readbacks", ARCHIVES, transfers)
    for gate in ("r30-project-checkpoint", "r31-workspace-checkpoint"):
        directory = ROOT / "hepta-cell/qualification/cell-unification-20261106/native-evidence" / gate
        group("support/prerequisite-gate-readback/" + gate, directory,
              [directory / name for name in ("CLOSURE.json", "INDEPENDENT-READBACK.json", "ATTACHMENT-MANIFEST.json")])
    publication_dir = ROOT / "r31-formal-root-preparation"
    publication = json.loads(read(publication_dir / "UPLOAD-CLOSED.json", {
        "bytes": 4350, "sha256": "a785d68054a90e830daad54c444d9014c257cf35e29375f2fe430420154014ae"}))
    require(publication["count"] == 329 and publication["batch_count"] == 42
            and publication["actual_create_responses"] == 162
            and publication["existing_actual_Git_object_reuses"] == 167,
            "R31 publication support is not the fixed requested snapshot")
    for key in ("combined_overlay", "ledger_before", "ledger_after"):
        read(ROOT / publication[key]["path"], publication[key])
    batches = sorted((publication_dir / "upload-batches").glob("batch-*.json"))
    require(len(batches) == 42, "fixed R31 batch receipt count mismatch")
    group("publication-support/R31", publication_dir, batches + [publication_dir / name for name in (
        "UPLOAD-CLOSED.json", "ROOT-UPLOAD-PLAN.json", "LEDGER-BEFORE-BINARY-REGISTRATION.json",
        "LEDGER-AFTER-BINARY-REGISTRATION.json", "COMBINED-STAGED-OVERLAY.json", "close_upload.py")])
    pending = []
    if args.peer_handoff:
        peer_path = ROOT / safe(args.peer_handoff)
        require(peer_path.name == "HANDOFF-MANIFEST.json", "explicit peer handoff required")
        from_handoff(str(peer_path.parent.relative_to(ROOT)), "support/independent-complete-readback")
    else:
        pending.append("independent full finalization readback HANDOFF")
    if args.registration:
        registration_path = ROOT / safe(args.registration)
        registration = json.loads(read(registration_path))
        config["root_code_registration"] = registration["registration"]
        directory = ROOT / safe(registration["directory"])
        paths = [row_path(directory, row) for row in registration["files"]]
        group("publication-support/source54", directory, paths)
        group("support/root-registration-binding", registration_path.parent, [registration_path])
    else:
        pending.append("actual root source54 commit/readback/fixed ledger")
    config["frozen"] = not pending
    config["success_result_not_yet_bound"] = bool(pending)
    config["collections"] = collections
    config["preparation_status"] = "ACTUAL_LOCAL_BINDINGS_COMPLETE" if config["frozen"] else "ACTUAL_NATIVE_OUTPUTS_BOUND_FINAL_SUPPORT_PENDING"
    config["pending"] = pending
    config["group_summary"] = group_summary
    config["copied_source_payloads_outside_original_three_archives"] = False
    config["per_chunk_transport_payloads_for_three_archives_copied"] = False
    config["archive_complete_hash_and_fixed_version_chunk_receipts_retained"] = True
    raw = (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode()
    with output.open("xb") as stream:
        stream.write(raw)
    print(json.dumps({"path": str(output.relative_to(ROOT)), **pin(raw), "frozen": config["frozen"],
                      "support_groups": len(collections), "support_files": sum(len(g["files"]) for g in collections),
                      "native_outputs": 24, "source_archives": 3, "pending": pending}, indent=2))


if __name__ == "__main__":
    main()
