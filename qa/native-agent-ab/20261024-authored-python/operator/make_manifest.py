"""Create a review-draft file manifest; no model execution or final admission."""

from pathlib import Path

import pack


def main():
    output = pack.ROOT / "PACK_MANIFEST.draft.json"
    if output.exists():
        raise ValueError("refusing to overwrite draft manifest")
    files = []
    for path in sorted(pack.ROOT.rglob("*")):
        if path.is_symlink():
            raise ValueError("symlink in task pack")
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        raw = path.read_bytes()
        files.append({"path": path.relative_to(pack.ROOT).as_posix(), "bytes": len(raw), "sha256": pack.digest(raw)})
    manifest = {"schema": "hepta.native-ab.pack-manifest.v1", "status": "draft_root_review_required",
                "files": files, "model_invocations": 0,
                "actual_controller_owner_fault_runs": 0,
                "contains_private_expected_and_references": True,
                "never_mount_complete_pack_into_agent_or_candidate_sandbox": True}
    output.write_bytes(pack.canonical(manifest) + b"\n")
    print(pack.canonical({"path": str(output), "sha256": pack.digest(output.read_bytes()),
                          "files": len(files), "bytes_total": sum(f["bytes"] for f in files)}).decode())


if __name__ == "__main__":
    main()
