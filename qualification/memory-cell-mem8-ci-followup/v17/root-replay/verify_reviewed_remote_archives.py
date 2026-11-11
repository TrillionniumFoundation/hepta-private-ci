"""Verify full remote candidate/original packets without executing their workloads."""
import base64
import difflib
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
REMOTE = HERE / "remote-reviewed"


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def extract(raw, relative, members):
    destination = HERE / "root-reviewed-extracted" / relative
    destination.mkdir(parents=True, exist_ok=False)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:xz") as source:
        items = source.getmembers()
        assert len(items) == len({item.name for item in items}) == members
        for item in items:
            path = PurePosixPath(item.name)
            assert item.isfile() and not path.is_absolute() and ".." not in path.parts
            target = destination / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.extractfile(item).read())
    return destination


def replay(script, root):
    result = subprocess.run([sys.executable, "-B", script], cwd=root, capture_output=True, check=True)
    assert not result.stderr
    return result.stdout, json.loads(result.stdout)


def main():
    proof = json.loads((HERE / "REVIEWED_REMOTE_OBJECT_READBACK.json").read_bytes())
    binary = {}
    for row in proof["objects"]:
        if row["encoding"] != "base64":
            continue
        relative = row["path"].split("/v17/", 1)[1]
        raw = base64.b64decode((REMOTE / (relative + ".b64")).read_text().strip(), validate=True)
        assert identity(raw) == {"bytes": row["bytes"], "sha256": row["sha256"], "git_blob": row["sha"]}
        binary[relative] = raw
    private = binary["private-c895/MEM_C895_PRIVATE_ORIGINAL.tar.xz"]
    assert private == (WORK / "mem-ci-c895-private-evidence-v1/MEM_C895_PRIVATE_ORIGINAL.tar.xz").read_bytes()
    p_root = extract(private, "private-c895", 27)
    output, p_result = replay("verify_private_original.py", p_root)
    assert p_result == json.loads((p_root / "AUDIT.json").read_bytes())
    (HERE / "ROOT_PRIVATE_OFFLINE_REPLAY.json").write_bytes(output)

    fixture = binary["subagent-v2-candidate/SUBAGENT_V2_FIXTURE_SAFE_SOURCE.tar.xz"]
    assert fixture == (WORK / "mem-subagent-matcher-route-c895-publication/SUBAGENT_V2_FIXTURE_SAFE_SOURCE.tar.xz").read_bytes()
    f_root = extract(fixture, "subagent-v2-candidate", 23)
    manifest = json.loads((WORK / "mem-subagent-matcher-route-c895-publication/MEMBER_MANIFEST.json").read_bytes())
    assert len(manifest["members"]) == 23
    assert {p.relative_to(f_root).as_posix() for p in f_root.rglob("*") if p.is_file()} == {row["path"] for row in manifest["members"]}
    for row in manifest["members"]:
        assert identity((f_root / row["path"]).read_bytes()) == {key: row[key] for key in ("bytes", "sha256", "git_blob")}
    meta = json.loads((f_root / "revision2/CANDIDATE_MANIFEST.json").read_bytes())
    path = meta["path"]
    before = (f_root / "source" / path).read_text()
    candidate = (f_root / "revision2/candidate" / path).read_text()
    transformed = before
    for case in dict.fromkeys(row["case"] for row in meta["edits"]):
        start = transformed.index("async fn " + case + "()")
        end = transformed.index("\n#[", start)
        block = transformed[start:end]
        for row in [r for r in meta["edits"] if r["case"] == case]:
            assert block.count(row["old"]) == 1
            block = block.replace(row["old"], row["new"], 1)
        transformed = transformed[:start] + block + transformed[end:]
    comment = meta["revision2_comment_edit"]
    assert transformed.count(comment["old"]) == 1
    transformed = transformed.replace(comment["old"], comment["new"], 1)
    assert transformed == candidate
    assert identity(candidate.encode()) == meta["after"]
    patch = "".join(difflib.unified_diff(before.splitlines(True), candidate.splitlines(True), fromfile="a/" + path, tofile="b/" + path))
    assert patch == (f_root / "revision2/CANDIDATE.patch").read_text()

    fence = b"".join(binary["fence013-feasibility/mem-fence013-feasibility-v1.tar.xz.part-0" + str(index)] for index in (1, 2))
    assert fence == (WORK / "mem-fence013-feasibility/mem-fence013-feasibility-v1.tar.xz").read_bytes()
    z_root = extract(fence, "fence013-feasibility", 72)
    output, z_result = replay("verify_review.py", z_root)
    assert z_result["binary_bytes_independently_read"] is False
    assert z_result["security_audit_of_entire_release"] is False
    assert z_result["original_subreason"] == "UNKNOWN"
    (HERE / "ROOT_FENCE_FEASIBILITY_OFFLINE_REPLAY.json").write_bytes(output)
    audit = {
        "schema": "mem8.v17.root-reviewed-archives.v1",
        "status": "PASS_FULL_REMOTE_PACKETS_AND_OFFLINE_REPLAYS",
        "immutable_commit": proof["immutable_commit"], "full_remote_objects": 43,
        "private": {"archive": identity(private), "members_verified": 27,
                    "full_original_offline_result_equal": True,
                    "distinct_selected_pass": 34, "additional_positive_control_executions": 2,
                    "mutant_executions": 4, "expected_mutant_failures": 2,
                    "signed_original_case_pass": 1, "source_before_after_clean": True},
        "fixture_candidate": {"archive": identity(fixture), "members_verified": 23,
                              "six_fixture_changes_plus_comment_reconstructed_from_full_bytes": True,
                              "complete_patch_recomputed_equal": True,
                              "postimage": meta["after"], "native_acceptance_established": False},
        "fence_feasibility": {"archive": identity(fence), "parts": 2, "members_verified": 72,
                              "original_offline_reader_replayed": True, "result": z_result,
                              "qualification_result_in_this_packet": False},
        "new_native_tests_builds_models_or_network_requests_by_replay": 0,
    }
    (HERE / "ROOT_REVIEWED_ARCHIVE_AUDIT.json").write_text(json.dumps(audit, indent=2) + "\n")
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
