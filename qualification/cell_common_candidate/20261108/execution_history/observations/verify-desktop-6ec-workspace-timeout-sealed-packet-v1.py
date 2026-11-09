#!/usr/bin/env python3
"""Read only the fixed completed timeout packet and its 140 text-record inputs."""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tarfile

R = Path("/home/qian-qi/work/hepta-cell-s0-records-20261108-898e")
P = R / "desktop-6ec-workspace-timeout-and-availability-history-v1"
PREP = R / "desktop-6ec-workspace-timeout-history-preparation-v1"
OUTER = R / "desktop-6ec-workspace-timeout-history-seal-outer-v1"
OUT = R / "desktop-6ec-workspace-timeout-history-independent-v1"
PACKET = "desktop-6ec-workspace-timeout-and-artifact-availability-history-v1"
SOURCE = "6ec5993fec3dcd6a3c569498a1d5b4c277f1c142"
TREE = "b0ddbe6b6f83dc42657260b266774f79c9d1ed90"
FIXED = {
    P / "RESULT.json": (3811, "9ae60f97bce3d7e0a9aa2504122bd1eb6e4c04cb800da8f1ac248003bf13bce4"),
    P / "MANIFEST.json": (115069, "e6c9f07efc6c706b9287f84f25f2e588eff1ed10a746f1c48082d3af119c81d3"),
    P / "SCOPE.json": (42761, "e9556d9f84e5e431ece41b36bc0fc283d21bd8d6f53834df4ee5b99178bd9922"),
    P / "COUNT_BINDINGS.json": (1485, "fc6940643f657ab70bae07b61864792675a06844ed1aaaf3f7879c2a1405e1ad"),
    P / "desktop-6ec-workspace-timeout-and-availability-history.tar.xz": (2599580, "b7c25e516550fa01423137c66bef6b6bf5099f1b4aff426d3a941534791e8d95"),
    PREP / "INPUTS.json": (82501, "32c09e1c22c65bbe36a3200271ff9a3505d01a382ff4db6c8f59dc758496b7e3"),
    PREP / "ARCHIVER_PREPARATION.json": (1424, "0aa66dff2febf28213fd325849583514968a8f2cbc3a1d5b76cb647310e4da7a"),
    R / "archive-desktop-6ec-workspace-timeout-history-v1.py": (29251, "4669c582e1d96fc9e755fb8ee26699a3027174fc3875e939d6ec7f1fca304f9a"),
    OUTER / "EXECUTION.json": (1289, "55e8aaf7d73ee77f2833557c1ee630f7deff4751fbe2cba19269b66dc3b96f22"),
    OUTER / "REQUEST.json": (1203, "1b2839330f20ec3ad63870efc2685461c608f6dda37d4f0225d6cdb89243fc94"),
    OUTER / "stdout.log": (637, "567c8c2416120dd6c1ba6acc80cc8a66ae11cfb49ca6ca80d0e0832aaf0db6ee"),
    OUTER / "stderr.log": (0, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
}
STAT = ("st_dev", "st_ino", "st_size", "st_mode", "st_mtime_ns", "st_ctime_ns", "st_nlink")


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    require(path.is_absolute() and path.is_relative_to(R) and ".." not in path.parts,
            "only the exact records scope is allowed")
    require(path.resolve(strict=True) == path, "aliased record path")
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, "regular single-link record required")
    require(before.st_size <= 128 * 1024**2, "record exceeds admitted size")
    data = path.read_bytes()
    after = path.lstat()
    require(all(getattr(before, k) == getattr(after, k) for k in STAT), "record changed during read")
    return data, {
        "path": str(path), "relative": str(path.relative_to(R)), "bytes": len(data),
        "sha256": sha(data), "mode": stat.S_IMODE(before.st_mode), "device": before.st_dev,
        "inode": before.st_ino, "nlink": before.st_nlink, "mtime_ns": before.st_mtime_ns,
        "ctime_ns": before.st_ctime_ns, "nul_count": data.count(b"\0"),
    }


def safe_name(name):
    p = PurePosixPath(name)
    require(bool(name) and str(p) == name and not p.is_absolute()
            and ".." not in p.parts and "\\" not in name, "unsafe tar name")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"status": "PREPARED_NOT_EXECUTED", "native_tests": 0}))
        return 0
    require(__debug__ and not os.environ.get("PYTHONOPTIMIZE"), "optimized Python refused")
    require(not os.path.lexists(OUT), "create-only independent output required")
    OUT.mkdir(mode=0o700)
    result = {"schema": 1, "status": "INDEPENDENT_READBACK_INCOMPLETE", "returncode": 1,
              "started_at": now(), "packet_id": PACKET, "source_sha": SOURCE, "source_tree": TREE,
              "native_tests_executed": 0, "executable_payload_access": False, "source_checkout_access": False,
              "target_access": False, "append_commit_push": False, "original_workspace_passed": False,
              "case_closure_verified": False, "verified_counts": None, "scientific_acceptance": False,
              "full_history_cost": None, "physical_cost": None,
              "stages": {f"S{i}": "HOLD" for i in range(6)}}
    before, payload, verified = {}, {}, []
    code = 1
    try:
        for path, expected in FIXED.items():
            data, pin = read(path)
            require((len(data), sha(data)) == expected, "fixed original pin differs: " + str(path))
            before[str(path)] = pin
            payload[path] = data
        manifest = json.loads(payload[P / "MANIFEST.json"])
        scope = json.loads(payload[P / "SCOPE.json"])
        counts = json.loads(payload[P / "COUNT_BINDINGS.json"])
        sealed = json.loads(payload[P / "RESULT.json"])
        inputs = json.loads(payload[PREP / "INPUTS.json"])
        outer = json.loads(payload[OUTER / "EXECUTION.json"])
        require(sealed["returncode"] == outer["child_returncode"] == 0
                and outer["status"] == "NATURALLY_COMPLETED"
                and outer["child_os_exit_code_directly_observed"] is True, "original seal execution did not complete")
        for key in ("request", "stdout", "stderr", "result"):
            row = outer[key]
            require((row["bytes"], row["sha256"]) == FIXED[Path(row["path"])], "outer original reference differs")
        for record in (sealed, manifest, scope):
            require(record["packet_id"] == PACKET and record["source_sha"] == SOURCE
                    and record["source_tree"] == TREE, "packet/source identity differs")
        require(manifest["payload_member_count"] == 145 and manifest["archive_member_count"] == 146
                and sealed["member_count"] == 146 and sealed["original_record_file_count"] == 140,
                "actual sealed counts differ")
        expected_members = {r["path"]: r for r in manifest["files"]}
        require(len(expected_members) == len(manifest["files"]) == 145, "manifest duplicate or count mismatch")
        originals = {r["path"]: r for r in inputs["files"]}
        require(len(originals) == len(inputs["files"]) == inputs["file_count"] == 140,
                "original 140-file whitelist differs")
        require(inputs["payload_bytes"] == 36523086, "original payload byte count differs")
        generated = {
            "metadata/INPUTS.json": payload[PREP / "INPUTS.json"],
            "metadata/SCOPE.json": payload[P / "SCOPE.json"],
            "metadata/COUNT_BINDINGS.json": payload[P / "COUNT_BINDINGS.json"],
            "metadata/ARCHIVER.py": payload[R / "archive-desktop-6ec-workspace-timeout-history-v1.py"],
            "metadata/ARCHIVER_PREPARATION.json": payload[PREP / "ARCHIVER_PREPARATION.json"],
        }
        original_names = {"originals/" + str(Path(p).relative_to(R)) for p in originals}
        require(set(expected_members) == original_names | set(generated), "exact original/generated member set differs")
        archive = payload[P / "desktop-6ec-workspace-timeout-and-availability-history.tar.xz"]
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:xz") as tf:
            members = tf.getmembers()
            names = [m.name for m in members]
            require(len(names) == len(set(names)) == 146
                    and set(names) == set(expected_members) | {"MANIFEST.json"}, "tar exact member set differs")
            for member in members:
                safe_name(member.name)
                require(member.isfile() and not member.issym() and not member.islnk(), "special tar member")
                require(member.uid == member.gid == 0 and member.mtime == 0, "tar normalized ownership/time differs")
                data = tf.extractfile(member).read()
                data.decode("utf-8")
                require(b"\0" not in data, "unexpected NUL in fixed text-only packet")
                if member.name == "MANIFEST.json":
                    require(data == payload[P / "MANIFEST.json"] and member.mode == 0o644, "embedded manifest differs")
                else:
                    row = expected_members[member.name]
                    require((member.size, member.mode, sha(data)) == (row["bytes"], row["mode"], row["sha256"]),
                            "original tar member bytes/mode/SHA differ: " + member.name)
                    if member.name.startswith("originals/"):
                        path = R / member.name.removeprefix("originals/")
                        require(row["original_input"] == originals[str(path)], "member-to-original pin differs")
                        current, pin = read(path)
                        require(current == data and pin == originals[str(path)], "original input changed after seal")
                        before[str(path)] = pin
                    else:
                        require(data == generated[member.name] and row["original_input"] is None, "generated original bytes differ")
                verified.append({"path": member.name, "bytes": len(data), "mode": member.mode, "sha256": sha(data)})
        v2 = counts["workspace_v2"]
        require(v2["test_wrapper_exit"] == 124 and v2["test_child_exit"] == -9
                and v2["timed_out"] is True and v2["verified_complete_counts"] is None
                and v2["case_closure_verified"] is False, "original timeout outcome changed")
        require(counts["forensic_retainer"]["returncode"] == 1
                and counts["forensic_retainer"]["copied_paths"] == 0
                and counts["partial_readback"]["raw_pass_shaped_unique_keys"] == 6821
                and counts["partial_readback"]["these_are_not_complete_run_counts"] is True,
                "original forensic/partial-readback boundary changed")
        require(scope["negative_control_preparation_cutoff"]["actual_negative_native_or_outer_output_is_excluded"] is True
                and scope["full_workspace_passed"] is False and scope["verified_counts"] is None,
                "packet scope was upgraded")
        result.update(member_count=146, payload_member_count=145, original_record_file_count=140,
                      original_record_bytes=36523086, all_members_bytes_mode_sha_verified=True,
                      original_text_records_equal_archive=True, original_timeout_and_missing_target_failure_preserved=True,
                      negative_native_terminal_outcome_excluded=True, count_bindings=counts,
                      archive_sha256=sha(archive), verified_members=verified)
        code = 0
    except Exception as error:
        result["error"] = type(error).__name__ + ": " + str(error)
    finally:
        try:
            for path, pin in before.items():
                require(read(Path(path))[1] == pin, "independent readback input drift")
            result["inputs_before_after_unchanged"] = True
        except Exception as error:
            result["final_error"] = type(error).__name__ + ": " + str(error)
            result["inputs_before_after_unchanged"] = False
            code = 1
        result.update(returncode=code, finished_at=now(), input_count=len(before), input_pins=before,
                      status="ALL_146_ORIGINAL_MEMBERS_VERIFIED_TIMEOUT_FAIL_PRESERVED" if code == 0 else "INDEPENDENT_READBACK_INCOMPLETE")
        raw = (json.dumps(result, indent=2) + "\n").encode()
        with (OUT / "RESULT.json").open("xb") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        print(json.dumps({"returncode": code, "status": result["status"], "member_count": result.get("member_count"),
                          "result": {"path": str(OUT / "RESULT.json"), "bytes": len(raw), "sha256": sha(raw)}}), flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
