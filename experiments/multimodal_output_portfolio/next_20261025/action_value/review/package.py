"""Complete rich action-value evidence, using the existing immutable packager."""

import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import time

from ....closure_20261025.package_evidence import file_sha, package


def run(repository, runs, archive):
    folder = repository / "experiments/multimodal_output_portfolio/next_20261025/action_value"
    manifest_path, receipt_path = folder / "EVIDENCE_MANIFEST.json", folder / "EVIDENCE_ARCHIVE.json"
    input_path, spec_path = folder / "EVIDENCE_INPUTS.json", folder / "PACKAGE_SPEC.json"
    if any(p.exists() for p in (archive, manifest_path, receipt_path, input_path, spec_path)):
        raise FileExistsError("Never overwrite an evidence package")
    protocol = json.loads((folder / "PROTOCOL.json").read_text())
    development = json.loads((folder / "DEVELOPMENT.json").read_text())
    if not (folder / "review/AUDIT.json").exists(): raise ValueError("Independent closed-result audit required")
    pinned = {**protocol["frozen_candidate_sha256"], **development["input_sha256"]}
    files, external = {}, {}
    helper = repository / "experiments/multimodal_output_portfolio/closure_20261025/package_evidence.py"
    files["repository/" + str(helper.relative_to(repository))] = helper
    for name, expected in pinned.items():
        path = Path(name)
        if file_sha(path) != expected: raise ValueError("Frozen input changed: " + name)
        if path.is_relative_to(repository): files["repository/" + str(path.relative_to(repository))] = path
        elif path.is_relative_to(runs): files["runs/" + str(path.relative_to(runs))] = path
        else: external[name] = {"sha256": expected, "bytes": path.stat().st_size}
    input_record = {"schema": "hepta.next.rich-value-external-input-custody.v1",
        "external_inputs_verified": external, "primary_protocol_sha256": file_sha(folder / "PROTOCOL.json"),
        "scope": "Original generators, teachers, sensors, observers and historical fit/selection tables are retained in the separately verified shared-inputs archive; their duplicate bytes are not included here.",
        "packager_sha256": file_sha(Path(__file__)), "packager_helper_sha256": file_sha(helper),
        "recorded_unix_ns": time.time_ns()}
    with input_path.open("x") as stream: json.dump(input_record, stream, sort_keys=True, indent=2); stream.write("\n")
    for path in folder.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts and path not in (manifest_path, receipt_path, spec_path):
            files["repository/" + str(path.relative_to(repository))] = path
    for root in runs.glob("action-value-*"):
        paths = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
        for path in paths:
            if "__pycache__" not in path.parts: files["runs/" + str(path.relative_to(runs))] = path
    spec = {"study": "next-rich-action-value-20261026",
        "description": "Both registered capacities and all saved source folds/backups, complete historical development and smoke, selected checkpoints, all new actual requests and finite H1 counterfactual media/journals/scores, unchanged protocol and closed-source code, independent audits, whole-process/resource receipts and full report. No failed or unadmitted candidate omitted.",
        "files": [{"path": str(path), "name": name, "sha256": file_sha(path)} for name, path in sorted(files.items())]}
    with spec_path.open("x") as stream: json.dump(spec, stream, sort_keys=True, indent=2); stream.write("\n")
    package(spec_path, archive)
    verified = set()
    with tarfile.open(archive, "r:gz") as packed:
        manifest_bytes = packed.extractfile("MANIFEST.json").read()
        manifest = json.loads(manifest_bytes)
        expected = {r["member"]: r for r in manifest["files"]}
        for member in packed.getmembers():
            if member.name == "MANIFEST.json": continue
            if not member.isfile() or member.name not in expected or member.name in verified:
                raise ValueError("Wrong or repeated archive member")
            value = hashlib.sha256()
            with packed.extractfile(member) as stream:
                while block := stream.read(1024 * 1024): value.update(block)
            if member.size != expected[member.name]["bytes"] or value.hexdigest() != expected[member.name]["sha256"]:
                raise ValueError("Archived bytes differ: " + member.name)
            verified.add(member.name)
    if verified != set(expected): raise ValueError("Missing archive member")
    with manifest_path.open("xb") as stream: stream.write(manifest_bytes)
    receipt = json.loads(archive.with_suffix(archive.suffix + ".receipt.json").read_text())
    if hashlib.sha256(manifest_bytes).hexdigest() != receipt["manifest_sha256"] or file_sha(archive) != receipt["archive_sha256"]:
        raise ValueError("Archive or internal manifest identity differs")
    receipt.update({"status": "passed", "verified_members_including_manifest": len(verified) + 1,
        "all_member_bytes_rehashed_after_archive_close": True, "original_files_retained": True,
        "external_frozen_input_count": len(external), "upload_performed": False, "completed_unix_ns": time.time_ns()})
    with receipt_path.open("x") as stream: json.dump(receipt, stream, sort_keys=True, indent=2); stream.write("\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repository", type=Path, required=True); p.add_argument("--runs", type=Path, required=True)
    p.add_argument("--archive", type=Path, required=True)
    a = p.parse_args(); run(a.repository.resolve(), a.runs.resolve(), a.archive.resolve())
