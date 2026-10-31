"""Package byte-verified raw audits and inventory the reviewable Git deliverable.

The original local audit directories remain intact. Archives contain every raw
member, including failed runs; publication keeps their small reports readable.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

from .experiment import archive_chunks

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
AUDITS = ("causal_audit", "causal_audit_attempt02", "direct_recovery_diagnostic01", "causal_audit_fixture")
SUMMARY_NAMES = {"REPORT.json", "FAILURE.json", "INPUTS.json", "PROVENANCE.json"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def pack_audits():
    evidence = HERE / "evidence"
    index_path = evidence / "AUDIT_ARCHIVE_INDEX.json"
    if index_path.exists():
        index = json.loads(index_path.read_text())
        for group in index["audits"].values():
            for archive, expected in group["archives"].items():
                if sha((evidence / archive).read_bytes()) != expected:
                    raise ValueError(("Archive changed", archive))
        return index
    index = dict(schema="hcsn.task.native.audit.archives.v1", audits={})
    for name in AUDITS:
        source = evidence / name
        work = evidence / "_work" / ("publication_" + name)
        work.parent.mkdir(exist_ok=True)
        shutil.copytree(source, work)
        archives, members = archive_chunks(evidence, work, "audit_archives/" + name)
        index["audits"][name] = dict(archives=archives, members=members,
                                    original_local_directory_retained=True)
    index_path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")
    return index


def files():
    selected = []
    for path in HERE.rglob("*"):
        relative = path.relative_to(HERE)
        if not path.is_file() or any(p in {"__pycache__", "_work"} for p in relative.parts):
            continue
        if relative.name in {"DELIVERY_MANIFEST.json", "REMOTE_VERIFICATION.json"}:
            continue
        if len(relative.parts) >= 2 and relative.parts[0] == "evidence" and relative.parts[1] in AUDITS:
            if len(relative.parts) != 3 or relative.name not in SUMMARY_NAMES:
                continue
        selected.append(path)
    selected += [REPO / "experiments/hcsn_hx_unified_v3" / name
                 for name in ("qvi_grid_independent.py", "test_qvi_grid_independent.py")]
    selected += [REPO / ".github/workflows/hcsn-task-native-loop.yml", REPO / ".codespellrc"]
    return sorted(selected)


def inventory():
    rows = []
    for path in files():
        data = path.read_bytes()
        if len(data) > 512000:
            raise ValueError(("Repository blob limit exceeded", path, len(data)))
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        rows.append(dict(path=str(path.relative_to(REPO)), bytes=len(data), sha256=sha(data), git_blob_sha=blob,
                         binary=path.name.endswith((".gz", ".bin", ".witness", ".journal"))))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-audits", action="store_true")
    parser.add_argument("--manifest", action="store_true")
    args = parser.parse_args()
    if args.pack_audits:
        packed = pack_audits()
        print(json.dumps({k: len(v["members"]) for k, v in packed["audits"].items()}))
    if args.manifest:
        rows = inventory()
        manifest = dict(schema="hcsn.task.native.delivery.v1",
            parent_commit="e7eaa5e0be835269636216c8fe8b1ae2f1a22361", files=rows,
            file_count=len(rows), total_bytes=sum(r["bytes"] for r in rows),
            max_blob_bytes=max(r["bytes"] for r in rows),
            self_and_remote_readback_excluded_to_avoid_circular_identity=True)
        (HERE / "DELIVERY_MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        print(json.dumps({k: v for k, v in manifest.items() if k != "files"}))


if __name__ == "__main__":
    main()
