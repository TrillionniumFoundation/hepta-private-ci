#!/usr/bin/env python3
"""Freeze and package the final C4 appendix only after root publication completion."""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

OUT = Path(__file__).resolve().parent
SOURCE = OUT.parent
PREFIX = "qualification/r3-audit-repair-20261104/continuation-20261105/reviews/post-audit-execution-v3-final-appendix-20261106/"

def ident(data):
    return {"bytes": len(data), "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(), "sha256": hashlib.sha256(data).hexdigest()}

def put_json(path, value):
    assert not path.exists(), path
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--publication-complete", required=True, help="Exact root-confirmed new head SHA; never a ref name")
    parser.add_argument("--tree", required=True, help="Exact root-confirmed new tree")
    args = parser.parse_args()
    assert len(args.publication_complete) == len(args.tree) == 40
    assert all(c in "0123456789abcdef" for c in args.publication_complete + args.tree)
    publication = SOURCE / "integration-840-format-publication"
    assert (publication / "publication-verified.json").is_file(), "Root completion receipt required"
    selected = json.loads((OUT / "fixed-input-selection.json").read_bytes())
    rows = list(selected["files"])
    assert len(rows) == selected["file_count"] and sum(row["bytes"] for row in rows) == selected["total_bytes"]
    for path in sorted(publication.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            assert not path.is_symlink()
            rows.append({"source": str(path.relative_to(SOURCE)), "path": str(path.relative_to(SOURCE)), **ident(path.read_bytes())})
    for name in ("fixed-input-selection-01.json", "fixed-input-selection-02.json", "fixed-input-selection.json", "build_packet.py", "restore_packet.py", "verify_appendix.py", "README.zh-CN.md"):
        rows.append({"source": str((OUT / name).relative_to(SOURCE)), "path": "packet-tools/" + name, **ident((OUT / name).read_bytes())})
    assert len({row["path"] for row in rows}) == len(rows)
    stage = OUT / "root"
    assert not stage.exists(), "Use a new destination, retain previous histories"
    stage.mkdir()
    members = []
    for row in sorted(rows, key=lambda row: row["path"]):
        path = Path(row["path"])
        assert not path.is_absolute() and ".." not in path.parts
        body = (SOURCE / row["source"]).read_bytes()
        assert all(row[k] == v for k, v in ident(body).items()), row["source"]
        target = stage / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        members.append({"path": row["path"], **ident(body)})
    freeze = {
        "schema": "hepta-fourth-audit-final-appendix-freeze-v1",
        "files": members, "file_count": len(members), "total_bytes": sum(row["bytes"] for row in members),
        "expected_publication": {"head": args.publication_complete, "tree": args.tree, "parent": "840e8b5dbffca017753cdf87482ce325938f313c", "base": "63652be658ebed8d3052eb789b951793384fd5e4"},
        "scope": "Retained metadata, read-only PR increment, preparer validation history and actual format-successor publication identity. No final C4 report/index/config/plan or new native execution."
    }
    put_json(stage / "FREEZE.json", freeze)
    members.append({"path": "FREEZE.json", **ident((stage / "FREEZE.json").read_bytes())})
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for row in sorted(members, key=lambda row: row["path"]):
            item = zipfile.ZipInfo(row["path"], (2026, 11, 6, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            item.create_system = 3
            item.external_attr = 0o100644 << 16
            archive.writestr(item, (stage / row["path"]).read_bytes())
    raw = buffer.getvalue()
    assert not (OUT / "packet.zip").exists()
    (OUT / "packet.zip").write_bytes(raw)
    encoded = base64.b64encode(raw)
    parts = []
    for number, start in enumerate(range(0, len(encoded), 400000), 1):
        name = f"packet.zip.b64.part{number:02d}"
        body = encoded[start:start + 400000]
        (OUT / name).write_bytes(body)
        parts.append({"path": name, **ident(body)})
    manifest = {"schema": "hepta-fourth-audit-final-appendix-archive-v1", "archive": ident(raw), "parts": parts, "part_limit_bytes": 400000, "members": sorted(members, key=lambda row: row["path"]), "expected_publication": freeze["expected_publication"], "scope": freeze["scope"]}
    put_json(OUT / "archive.json", manifest)
    for source, target in {
        "FREEZE.json": "FREEZE.json",
        "pr4930-fa-increment-readonly-20261106/delta-review.json": "pr4930-delta-review.json",
        "integration-840-format-publication/publication-verified.json": "publication-verified.json",
        "fourth-audit-current-cut/METADATA-REVIEW.json": "METADATA-REVIEW.json",
    }.items():
        shutil.copyfile(stage / source, OUT / target)
    restored = OUT.parent / "fourth-audit-final-appendix-restored"
    command = [sys.executable, "-B", str(OUT / "restore_packet.py"), str(OUT), str(restored)]
    run = subprocess.run(command, capture_output=True)
    (OUT / "restore-01.stdout.json").write_bytes(run.stdout)
    (OUT / "restore-01.stderr.log").write_bytes(run.stderr)
    put_json(OUT / "restore-01.execution.json", {"argv": command, "exit_code": run.returncode, "stdout": ident(run.stdout), "stderr": ident(run.stderr), "native_or_qualification_execution": False})
    assert run.returncode == 0 and not run.stderr, "Preserved failed restore; do not overwrite"
    names = ["archive.json", "FREEZE.json", "README.zh-CN.md", "pr4930-delta-review.json", "publication-verified.json", "METADATA-REVIEW.json", "fixed-input-selection.json", "build_packet.py", "restore_packet.py", "verify_appendix.py", "restore-01.stdout.json", "restore-01.stderr.log", "restore-01.execution.json", *[row["path"] for row in parts]]
    objects = [{"local_path": str(OUT / name), "repo_path": PREFIX + name, "mode": "100644", "type": "blob", **ident((OUT / name).read_bytes())} for name in names]
    put_json(OUT / "registration-plan.json", {"schema": "hepta-fourth-audit-final-appendix-registration-plan-v1", "repository": "TrillionniumFoundation/hepta-private-ci", "prefix": PREFIX, "objects": objects})
    print(json.dumps({"members": len(members), "member_bytes": sum(row["bytes"] for row in members), "archive": ident(raw), "parts": len(parts), "objects": len(objects), "publication": freeze["expected_publication"], "restore_exit_code": run.returncode}, indent=2))

if __name__ == "__main__":
    main()
