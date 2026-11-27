"""Verify the retained original evidence without replaying native commands."""
import importlib.util
import json
from pathlib import Path
import sys


def main(root):
    spec = importlib.util.spec_from_file_location("original_evidence_audit", root / "audit_original.py")
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    manifest = json.loads((root / "PACKAGE_MANIFEST.json").read_bytes())
    rows = manifest["members"]
    assert len(rows) == len({row["path"] for row in rows})
    for row in rows:
        path = Path(row["path"])
        assert not path.is_absolute() and ".." not in path.parts
        file = root / path
        assert file.is_file() and not file.is_symlink()
        assert reader.identity(file.read_bytes()) == {key: row[key] for key in ("bytes", "sha256", "git_blob")}
    audit = reader.audit(root)
    assert audit == json.loads((root / "OFFLINE_AUDIT.json").read_bytes())
    assert audit["qualification_passed"] is False and audit["job_conclusion"] == "failure"
    review = json.loads((root / "ACTUAL_CLIPPY_REVIEW.json").read_bytes())
    name = review["path"]
    before = (root / "source-before" / name).read_bytes()
    after = (root / "clippy-postimages" / name).read_bytes()
    assert reader.identity(before) == review["preimage"]
    assert reader.identity(after) == review["postimage"]
    assert reader.identity((root / "ACTUAL_CLIPPY.patch").read_bytes()) == review["patch"]
    old = b".map_or(std::ptr::null(), |path| path.as_ptr()),"
    new = b".map_or(std::ptr::null(), std::vec::Vec::as_ptr),"
    assert before.count(old) == 1 and before.replace(old, new) == after
    return {"status": "PASS_ORIGINAL_EVIDENCE_REPLAY_QUALIFICATION_REMAINS_FAILED", "outer_members": len(rows) + 1, "original_audit": audit, "mechanical_rewrite_equal": True, "native_commands_executed_by_verifier": 0}


if __name__ == "__main__":
    print(json.dumps(main(Path(sys.argv[1]).resolve()), indent=2, sort_keys=True))
