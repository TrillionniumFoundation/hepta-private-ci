"""Check an actually fetched Git tree against old and newly published evidence.

GitHub retrieval is performed by the publishing client. This read-only checker
does not infer a remote tree from local files or publish a new commit.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from ..freeze import verify


PREFIX = "experiments/analytic_event_neuron/round4/"


def load(path):
    return json.loads(Path(path).read_text())


def git_sha(path):
    path = Path(path)
    value = hashlib.sha1(("blob " + str(path.stat().st_size) + "\0").encode())
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check(repo, run_dir, baseline_path, remote_path, state_path, output):
    frozen = verify(run_dir)
    baseline, remote, state = [load(p) for p in (baseline_path, remote_path, state_path)]
    if remote["head"] != state["head"] or remote["sha"] != state["tree"]:
        raise ValueError("Fetched branch head/tree differ from the completed publication")
    if not remote["fetched_from_github"] or remote.get("truncated", True):
        raise ValueError("A complete actual GitHub tree is required")
    old, current = baseline["blobs"], remote["blobs"]
    for path, value in old.items():
        if current.get(path) != value:
            raise ValueError("Historical Git blob changed: " + path)
    added = set(current) - set(old)
    if any(not path.startswith(PREFIX) for path in added):
        raise ValueError("Publication added a path outside Round 4")
    published = {}
    for path, value in state["blobs"].items():
        local = repo / path
        if not local.is_file() or git_sha(local) != value or current[path]["sha"] != value:
            raise ValueError("Published blob does not match local bytes and remote tree: " + path)
        if current[path]["mode"] != "100644" or current[path]["size"] != local.stat().st_size:
            raise ValueError("Published blob metadata differs: " + path)
        published[path] = {"git_sha": value, "sha256": sha(local), "bytes": local.stat().st_size}
    local_round4 = {str(p.relative_to(repo)) for p in (repo / PREFIX).rglob("*")
                    if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
                    and p.resolve() != output.resolve()}
    if local_round4 != added or added != set(published):
        raise ValueError("Local deliverables, new remote files, and publication index differ")
    for path in frozen["sources_sha256"]:
        if git_sha(repo / path) != current[path]["sha"]:
            raise ValueError("Frozen scientific source differs remotely: " + path)
    manifest_path = repo / PREFIX / "evidence/EVIDENCE_MANIFEST.json"
    manifest = load(manifest_path)
    archive_paths = []
    for row in manifest["archives"]:
        combined = hashlib.sha256()
        size = 0
        for part in row.get("parts", [row]):
            path = repo / part["path"]
            if sha(path) != part["sha256"] or path.stat().st_size != part["bytes"]:
                raise ValueError("Archive part differs: " + part["path"])
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    combined.update(block)
                    size += len(block)
            archive_paths.append(part["path"])
        if combined.hexdigest() != row["sha256"] or size != row["bytes"]:
            raise ValueError("Logical archive differs: " + row["name"])
    verify(run_dir)
    document = {
        "schema": "hepta.analytic-event.round4.final-publication-check.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(), "passed": True,
        "repository": "TrillionniumFoundation/hepta-private-ci",
        "branch": "research/analytic-event-neuron-20261027",
        "verified_commit": remote["head"], "verified_tree": remote["sha"],
        "baseline_commit": frozen["base_commit"], "baseline_tree": baseline["sha"],
        "baseline_blobs_unchanged": len(old), "all_added_paths_confined_to_round4": True,
        "source_commit": frozen["source_commit"], "frozen_source_files_exact": len(frozen["sources_sha256"]),
        "frozen_prepared_files_exact_locally_and_in_restored_archives": len(frozen["artifacts_sha256"]),
        "prepared_restoration_receipt_sha256": sha(repo / PREFIX / "evidence/PREPARED_RESTORATION.json"),
        "remote_published_blobs_exact": len(published), "new_remote_files": len(added),
        "all_local_deliverables_published": True, "archive_physical_blobs": len(archive_paths),
        "archive_logical_bundles": len(manifest["archives"]),
        "evidence_manifest_sha256": sha(manifest_path), "freeze_sha256": sha(run_dir / "FREEZE.json"),
        "readback_evidence": {"remote_tree_snapshot_sha256": sha(remote_path),
                              "baseline_tree_snapshot_sha256": sha(baseline_path),
                              "remote_tree_retrieved_utc": remote["retrieved_utc"]},
        "published_blobs": published,
        "receipt_publication": "This receipt is added in a later single-file commit; it cannot recursively hash itself. The publishing client then verifies that final commit and unchanged parent tree entries.",
        "production_promotion": False,
    }
    with output.open("x") as stream:
        json.dump(document, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    return document


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("repo", "run-dir", "baseline", "remote", "state", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    args = parser.parse_args()
    result = check(args.repo.resolve(), args.run_dir.resolve(), args.baseline, args.remote, args.state, args.output)
    print(json.dumps({k: result[k] for k in ("passed", "verified_commit", "baseline_blobs_unchanged",
                                            "remote_published_blobs_exact", "frozen_source_files_exact")}))
