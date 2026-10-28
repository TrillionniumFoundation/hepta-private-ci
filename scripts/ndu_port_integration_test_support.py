"""Commit tiny synthetic candidate trees for integration guard behavior tests."""

import copy
import json
import shutil
import subprocess

import ndu_port_candidate_common as common


def git(root, *arguments):
    return subprocess.check_output(
        ["git", *arguments], cwd=root, stderr=subprocess.STDOUT
    )


def integrate_fixture(root, recipe, original, artifact):
    """Use real Git; fixture provenance never represents a Rust qualification."""
    git(root, "add", "--", *original["files"])
    entries = git(root, "ls-files", "--stage", "-z", "--", *original["files"])
    modes = {}
    for row in entries.decode().split("\0"):
        if row:
            header, name = row.split("\t", 1)
            mode, _blob, stage = header.split()
            if stage != "0":
                raise ValueError("Synthetic fixture index must be resolved")
            modes[name] = mode
    manifest = {
        "schema": "hepta.port-integration.v1",
        "origin": {
            "source_commit": original["source_commit"],
            "result_sha256": common.checksum(artifact / "RESULT.json"),
            "artifact_sha256": common.checksum(artifact / "candidate.patch"),
            "source_patch": original["artifacts"]["source.patch"],
            "candidate_patch": original["artifacts"]["candidate.patch"],
        },
        "recipe_path": common.RECIPE,
        "recipe_sha256": original["recipe_sha256"],
        "policy_inputs": original["policy_inputs"],
        "files": original["files"],
        "file_modes": modes,
        "promotion_allowed": False,
    }
    path = root / common.INTEGRATION
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    git(root, "add", "--", common.INTEGRATION)
    git(root, "commit", "-qm", "integrated synthetic candidate and exact manifest")
    record = copy.deepcopy(original)
    record.update(
        source_mode="integrated",
        source_commit=git(root, "rev-parse", "HEAD").decode().strip(),
        source_tree=git(root, "rev-parse", "HEAD^{tree}").decode().strip(),
        integration={
            "manifest_path": common.INTEGRATION,
            "manifest_sha256": common.checksum(path),
            "origin_result_sha256": manifest["origin"]["result_sha256"],
        },
        changed_paths=[],
    )
    shutil.copyfile(path, artifact / "integration.json")
    (artifact / "candidate.patch").write_bytes(b"")
    record["artifacts"].update(
        common.describe(artifact, ("integration.json", "candidate.patch"))
    )
    (artifact / "RESULT.json").write_text(json.dumps(record))
    return record, common.checksum(artifact / "RESULT.json")
