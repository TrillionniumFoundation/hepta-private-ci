#!/usr/bin/env python3
"""Read only the fixed d274 packet: 119 originals, one exact small source-bundle exception, no ELF."""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tarfile

R = Path('/home/qian-qi/work/hepta-cell-s0-records-20261108-898e')
P = Path('/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/d274-negative-native-retention-history-v1')
PREP = Path('/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/d274-negative-native-retention-history-preparation-v1')
OUTER = Path('/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/d274-negative-native-history-seal-outer-v1')
OUT = R / 'd274-negative-native-history-independent-v1'
PACKET = 'd274-negative-native-retention-history-v1'
SOURCE = 'd27431b69195a2a6331a77d19e22ebeb4cf910c7'
TREE = 'b1cf50c33f5ec9101217ae3f6a7ff987e3aba973'
BUNDLE = Path('/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-d27431b-desktop-negative-v1/source-increment-original.bundle')
BUNDLE_PIN = (1800, '0e753e10409b9619c7ddff22cd36f00bcfb74f248f5bbb09dadbc989222a6f5e')
FIXED = {
    Path('/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/d274-negative-native-retention-history-v1/RESULT.json'): (3566, 'd48e94bc28aac4d4186db502bf16ef0eb217459522ff771426a0575c4bfb4a1d'),
    Path('/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/d274-negative-native-retention-history-preparation-v1/INPUTS.json'): (129017, '9ec09e219d452ccd7fa8fa6a9e01680db8651b61d51a4fbff22f86b473cb424e'),
    Path('/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/archive-d274-negative-native-retention-history-v1.py'): (29511, 'fc48e5c90afe5e91c4156438f983554b85337933bd91e366f65c4f58273bba4e'),
    Path('/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/d274-negative-native-history-seal-outer-v1/EXECUTION.json'): (1520, 'cc68349f0a4828ee57625e673513353fbc57fc9fbd02367cee59fda90ec51825'),
    Path('/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/d274-negative-native-retention-history-v1/MANIFEST.json'): (89944, 'f6ed2cff3c7a1799f116e910d88ca404c87a1d196e83982ee91fc6c43eacff11'),
    Path('/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/d274-negative-native-retention-history-v1/SCOPE.json'): (14199, 'c908b8e270a1a604b10bfb689b446b8be9bc9f33e72134dcd49fca1e56ca3124'),
    Path('/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/d274-negative-native-retention-history-v1/COUNT_BINDINGS.json'): (978, 'b5a2ed6dc20487d31e754c4309488425e6323f89a234e43631f4b975b4d59346'),
    Path('/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/d274-negative-native-retention-history-v1/d274-negative-native-retention-history.tar.xz'): (1342472, 'bde9c3428f6261268f02c82e3383ca85a1e476498941d655343d7a25ddd90700'),
    Path('/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/d274-negative-native-history-seal-outer-v1/REQUEST.json'): (699, '9520d636c4e01eac61e687a9e9e3dc9fae9d0d59fe02db8a1696d9fe7f942efe'),
    Path('/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/d274-negative-native-history-seal-outer-v1/stdout.log'): (595, '0448221c89055b86a4399626e18c8ebbfd8614a0c2344cb23d30e16fc2ae733c'),
    Path('/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/d274-negative-native-history-seal-outer-v1/stderr.log'): (0, 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'),
    Path('/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/d274-negative-native-retention-history-preparation-v1/RESULT.json'): (1034, '21c2c1d21127e03fe601cf2643511917fcc26cc8424bec31880540d4e62a0052'),
    Path('/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/prepare-d274-negative-native-history-v1.py'): (17788, '5393bd869ae17441f65cea3007bce4ad7cf40c781230fe865c3f71eacac47d0e'),
    Path('/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/d274-negative-native-history-prepare-outer-v1/EXECUTION.json'): (1534, '54e6f9162701a8a7e1a0e3531a6d4f327d5a88b01dc903d45683097f7794ef48'),
    Path('/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/d274-negative-native-history-prepare-outer-v1/REQUEST.json'): (684, 'baa1a502f62669a426e7b9207e44d245bc30c6810a45fc7612016ceeb8a2c06c'),
    Path('/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/d274-negative-native-history-prepare-outer-v1/stdout.log'): (588, '84c2928d0fdc58f84739f0511e23e941de8c4695277e569c6519acf255756475'),
    Path('/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/d274-negative-native-history-prepare-outer-v1/stderr.log'): (0, 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'),
}
STAT = ("st_dev", "st_ino", "st_size", "st_mode", "st_uid", "st_gid", "st_mtime_ns", "st_ctime_ns", "st_nlink")


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
        "path": str(path), "bytes": len(data), "uid": before.st_uid, "gid": before.st_gid,
        "sha256": sha(data), "mode": stat.S_IMODE(before.st_mode), "device": before.st_dev,
        "inode": before.st_ino, "nlink": before.st_nlink, "mtime_ns": before.st_mtime_ns,
        "ctime_ns": before.st_ctime_ns,
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
              "target_access": False, "append_commit_push": False, "full_workspace_passed": False,
              "original_native_status": "FAIL", "original_native_returncode": 1, "scientific_acceptance": False,
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
        require(manifest["payload_member_count"] == 129 and manifest["archive_member_count"] == 130
                and sealed["member_count"] == 130 and sealed["original_record_file_count"] == 119,
                "actual sealed counts differ")
        expected_members = {r["path"]: r for r in manifest["files"]}
        require(len(expected_members) == len(manifest["files"]) == 129, "manifest duplicate or count mismatch")
        originals = {r["path"]: r for r in inputs["files"]}
        require(len(originals) == len(inputs["files"]) == inputs["file_count"] == 119,
                "original 119-file whitelist differs")
        require(inputs["payload_bytes"] == 37973446, "original payload byte count differs")
        generated = {
            "metadata/INPUTS.json": payload[PREP / "INPUTS.json"],
            "metadata/SCOPE.json": payload[P / "SCOPE.json"],
            "metadata/COUNT_BINDINGS.json": payload[P / "COUNT_BINDINGS.json"],
            "metadata/ARCHIVER.py": payload[R / "archive-d274-negative-native-retention-history-v1.py"],
            'metadata/INPUT_PREPARATION_RESULT.json': payload[Path('/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/d274-negative-native-retention-history-preparation-v1/RESULT.json')],
            'metadata/INPUT_PREPARATION_DRIVER.py': payload[Path('/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/prepare-d274-negative-native-history-v1.py')],
            'metadata/INPUT_PREPARATION_OUTER.json': payload[Path('/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/d274-negative-native-history-prepare-outer-v1/EXECUTION.json')],
            'metadata/INPUT_PREPARATION_REQUEST.json': payload[Path('/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/d274-negative-native-history-prepare-outer-v1/REQUEST.json')],
            'metadata/INPUT_PREPARATION_STDOUT.log': payload[Path('/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/d274-negative-native-history-prepare-outer-v1/stdout.log')],
            'metadata/INPUT_PREPARATION_STDERR.log': payload[Path('/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/d274-negative-native-history-prepare-outer-v1/stderr.log')],
        }
        original_names = {"originals/" + str(Path(p).relative_to(R)) for p in originals}
        require(set(expected_members) == original_names | set(generated), "exact original/generated member set differs")
        archive = payload[P / "d274-negative-native-retention-history.tar.xz"]
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:xz") as tf:
            members = tf.getmembers()
            names = [m.name for m in members]
            require(len(names) == len(set(names)) == 130
                    and set(names) == set(expected_members) | {"MANIFEST.json"}, "tar exact member set differs")
            for member in members:
                safe_name(member.name)
                require(member.isfile() and not member.issym() and not member.islnk(), "special tar member")
                require(member.uid == member.gid == 0 and member.mtime == 0, "tar normalized ownership/time differs")
                data = tf.extractfile(member).read()
                if member.name == 'originals/' + str(BUNDLE.relative_to(R)):
                    require((len(data), sha(data)) == BUNDLE_PIN, 'only the exact 1800-byte Git bundle is nontext')
                else:
                    data.decode('utf-8')
                    require(b'\0' not in data, 'unexpected NUL outside the sole exact source-bundle exception')
                if member.name == "MANIFEST.json":
                    require(data == payload[P / "MANIFEST.json"] and member.mode == 0o644, "embedded manifest differs")
                else:
                    row = expected_members[member.name]
                    require((member.size, member.mode, sha(data)) == (row["bytes"], row["mode"], row["sha256"]),
                            "original tar member bytes/mode/SHA differ: " + member.name)
                    if member.name.startswith("originals/"):
                        path = R / member.name.removeprefix("originals/")
                        require(row["original_input"] == {k: originals[str(path)][k] for k in row["original_input"]}, "member-to-original pin differs")
                        current, pin = read(path)
                        require(current == data and pin == row["original_input"], "original input changed after seal")
                        before[str(path)] = pin
                    else:
                        require(data == generated[member.name] and row["original_input"] is None, "generated original bytes differ")
                verified.append({"path": member.name, "bytes": len(data), "mode": member.mode, "sha256": sha(data)})
        expected_case = {'status': 'FAIL', 'driver_returncode': 1, 'test_returncode': 100,
                         'collector_returncode': 1, 'unique_executed': 1, 'passed': 0, 'failed': 1,
                         'failure_exit_code': 101, 'filtered_outside_selection': 2447,
                         'selected_ignored': 0, 'retries': 0}
        require(counts['original_native'] == sealed['original_case_counts'] == expected_case,
                'original native FAIL1/test100/collector1/count boundary changed')
        require(counts['retention'] == {'returncode': 0, 'copied_paths': 1,
                                      'host_only_payload_bytes': 453757728, 'copied_executables_in_archive': 0}
                and counts['independent_readback'] == {'returncode': 0, 'original_records': 68,
                                                      'new_native_executions': 0},
                'retention/readback scope or executable exclusion changed')
        require(counts['expected_failure_does_not_change_test_outcome_to_PASS'] is True
                and scope['original_native']['status'] == 'FAIL'
                and scope['all_68_original_input_records_included'] is True
                and scope['source_target_or_executable_access_by_sealer'] is False
                and scope['retention']['binary_bytes_read_or_archived_by_sealer'] is False
                and scope['full_workspace_passed'] is False and scope['scientific_acceptance'] is False,
                'original failure or records-only archive scope was upgraded')
        require(len(inputs['independent_bound_records']) == 68
                and all(path in originals for path in inputs['independent_bound_records']),
                'not all original68 records are represented')
        bundle_name = 'originals/' + str(BUNDLE.relative_to(R))
        require(bundle_name in expected_members and expected_members[bundle_name]['bytes'] == BUNDLE_PIN[0]
                and expected_members[bundle_name]['sha256'] == BUNDLE_PIN[1], 'source bundle omitted or changed')
        result.update(member_count=130, payload_member_count=129, original_record_file_count=119,
                      original_record_bytes=37973446, all_members_bytes_mode_sha_verified=True,
                      original_records_equal_archive=True, original_native_FAIL1_test100_collector1_preserved=True,
                      all_68_original_bound_inputs_included=True, source_bundle_exact_exception_verified=True,
                      copied_ELF_payload_access_or_archiving=False, count_bindings=counts,
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
                      status="ALL_130_ORIGINAL_MEMBERS_VERIFIED_NEGATIVE_FAIL_PRESERVED" if code == 0 else "INDEPENDENT_READBACK_INCOMPLETE")
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
