"""Read the two original metadata ZIPs; no model or host execution occurs."""

import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
SOURCE = "cbe2539c02ea031352e874c53a106102dec32eed"
TREE = "befe4439388cc5537c37f9e27f78ec40e11b264d"
COMMAND = ["bwrap", "--unshare-user", "--unshare-net", "--ro-bind", "/", "/", "/bin/true"]
CASES = (
    ("26", 125927, "90a518e76bad8fcfb15778a6b8e68a5ce51f7714210a9092541c5cedb48f35d5", 0),
    ("24", 7961, "e4dbd67bdaf99070165ef30cc9ced7d19269212346f1e1c74cfa8e32e705f4f7", 1),
)


def main():
    results = []
    for host, size, digest, exit_code in CASES:
        path = ROOT / f"hepta-host{host}-cbe.zip"
        raw = path.read_bytes()
        assert len(raw) == size and hashlib.sha256(raw).hexdigest() == digest
        prefix = "hepta-original-sandbox-host/"
        with zipfile.ZipFile(path) as archive:
            assert archive.testzip() is None
            assert len(archive.namelist()) == len(set(archive.namelist()))
            members = {name: archive.read(name) for name in archive.namelist()}
        manifest = {}
        for line in members["hepta-original-sandbox-host.sha256"].decode().splitlines():
            expected, absolute = line.split("  ", 1)
            relative = prefix + Path(absolute).name
            assert relative not in manifest
            assert hashlib.sha256(members[relative]).hexdigest() == expected
            manifest[relative] = expected
        assert set(manifest) == set(members) - {"hepta-original-sandbox-host.sha256"}
        source = f"{SOURCE}\n{TREE}\n".encode()
        assert members[prefix + "source.txt"] == source
        assert members[prefix + "source-after.txt"] == source
        assert members[prefix + "source-status.txt"] == b""
        assert members[prefix + "source-status-after.txt"] == b""
        assert members[prefix + "apparmor-enabled.txt"] == b"Y\n"
        assert members[prefix + "apparmor_restrict_unprivileged_userns.txt"] == b"1\n"
        assert members[prefix + "uid.txt"].strip() != b"0"
        record = json.loads(members[prefix + "sandbox-host-capability.json"])
        assert record["command"] == COMMAND
        assert record["source_sha"] == record["tested_sha"] == SOURCE
        assert record["before"] == record["after"]
        assert record["before"]["commit"] == SOURCE
        assert record["before"]["tree"] == TREE
        assert record["before"]["dirty"] is False
        assert record["run_id"] == "40622113589"
        assert record["run_attempt"] == "1"
        assert record["timed_out"] is False
        assert record["output_limit_exceeded"] is False
        for key in ("returncode", "command_exit_code", "exit_code"):
            assert type(record[key]) is int and record[key] == exit_code
        assert record["status"] == ("passed" if exit_code == 0 else "failed")
        log = members[prefix + record["log_file"]]
        assert len(log) == record["log_bytes"]
        assert hashlib.sha256(log).hexdigest() == record["log_sha256"]
        assert log == (b"" if host == "26" else b"bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted\n")
        capacity = json.loads(members[prefix + "host.json"])
        assert capacity["physical_capacity_meets_12_gib"] is True
        assert capacity["observed_limit_excludes_12_gib"] is False
        assert capacity["resource_scope"] == "resource_limit_unknown"
        assert capacity["resource_capacity_qualified"] is False
        build_seconds = None
        if host == "26":
            build = json.loads(members[prefix + "cpython-build.json"])
            assert build["status"] == "passed"
            assert build["before"] == build["after"] == record["before"]
            assert build["command_exit_code"] == build["exit_code"] == build["returncode"] == 0
            assert build["timed_out"] is False and build["output_limit_exceeded"] is False
            build_log = members[prefix + build["log_file"]]
            assert len(build_log) == build["log_bytes"]
            assert hashlib.sha256(build_log).hexdigest() == build["log_sha256"]
            build_seconds = build["elapsed_seconds"]
            assert 0 < build_seconds < 420
            assert members[prefix + "built-python.txt"].startswith(b"3.12.3 ")
            source_pin = json.loads(members[prefix + "cpython-source.json"])
            assert source_pin["bytes"] == 20625068
            assert source_pin["sha256"] == "56bfef1fdfc1221ce6720e43a661e3eb41785dd914ce99698d8c7896af4bdaa1"
        results.append(dict(
            host="ubuntu-" + host + ".04", artifact_bytes=size, artifact_sha256=digest,
            members=len(members), all_crc_and_manifest_hashes_pass=True,
            source_before_after_equal=True, exit_code=exit_code, log_bytes=len(log),
            original_child_budget_seconds=0.5, owner_total_elapsed_seconds=record["elapsed_seconds"],
            elapsed_scope="includes full source identity checks; not child-only timing or hard real-time guarantee",
            apparmor_enabled=True, unprivileged_userns_restricted=True,
            physical_memory_bytes=capacity["physical_memory_bytes"],
            effective_resource_capacity_qualified=False, cpython_build_owner_seconds=build_seconds,
            image=members[prefix + "runner-image.txt"].decode().splitlines(),
            packages=members[prefix + "package-versions.txt"].decode().splitlines(),
        ))
    result = dict(schema="hepta-original-host-independent-readback-v1", cases=results,
                  whole_matrix_passed=False, ubuntu26_probe_passed=True,
                  native_rust_qualified=False, model_loop_qualified=False,
                  ordinary_installed_child=False, production_activated=False)
    (ROOT / "independent-readback.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
