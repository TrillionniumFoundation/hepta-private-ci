"""Verify the bounded Windows42 and Linux41 checkpoint members in memory."""

import ast
import datetime
import hashlib
import json
from pathlib import Path
import runpy
import stat
import sys

from review_core24b2 import BASE, identity, require


CASES = {
    "windows42": {
        "manifest": "WINDOWS42_TERMINAL_CHECKPOINT_PUBLICATION_MANIFEST.json",
        "manifest_sha": "2dc680db07d922d4f4c60b346dd9c384a59cf4419dafdb1866f616365a9ca231",
        "folder": "windows42_terminal_evidence_20261107",
        "index_sha": "ea80e9b69e99a2b1e6f6a1c6463cb00a50995f3a5f71f64d16ccda114e2b87b2",
        "files": 135,
        "bytes": 1980796,
        "private": {
            "d90bfcc1ee766e92d77e7395256a1bb0f603e5ff4bb2263d76f653c4b670d639",
        },
        "required": {
            "round3_local_qualification/windows42_terminal_root/ROOT_REVIEW.json": "04c18914ea329ef8f416e53f005b3ed76ac8d9de2fee5ddb7f510e4eaa6cf7c7",
            "round3_local_qualification/bwrap32_packet_windows42_checks/ROOT_CHECKS.json": "9ffc26c3e8944222038ca381313f08396251476f9b10d438f49df971a231bc39",
        },
        "status": "round3_native/windows42_safe_checkpoint_inputs/RUN_STATUS.json",
        "qualification": "Original owning target and all three cases failed; one complete 318-record block and its repeated 168-record suffix are preserved. Product P0 remains open.",
    },
    "linux41": {
        "manifest": "LINUX41_NATIVE_CHECKPOINT_PUBLICATION_MANIFEST.json",
        "manifest_sha": "514e1760eb8df8fa79c1657da9ad2bd1f35e625f4ee32ca662196dff96f707a9",
        "folder": "linux41_native_evidence_20261107",
        "index_sha": "25f190681d4f9ffea22e18ed232da9c77344eb05c61ba1e358ccaeec3bebdfde",
        "files": 138,
        "bytes": 2374166,
        "private": {
            "0aba67583aac0d0fde7e8024c5ed036211e24e804741b5d3024c19a08b2be64a",
            "a4de49cb7ba65beb6a5398aa485702bf5889fcba9281c17ad19e47def6bc7e47",
            "4275007c99e5c424dba07add420f05eed9b8fdeec63b293e35f621329f1fe22f",
            "8920348eb164fcf228ccb483b6cacd98aa45034f24635ddacd35e20017443d32",
        },
        "required": {
            "round3_local_qualification/linux41_native_root/ROOT_REVIEW.json": "df1a80792210af6f827a7eee76e2ed9e9f55c6cd8ba2d3bd876b96c52fb8b3cf",
            "round3_ci/independent_reviews/linux_delegation41_native/REVIEW.json": "44605d2a1f363f760e01c2d7bcb46226977511430b0769813f30d965862df4ed",
        },
        "status": "round3_native/linux41_safe_checkpoint_inputs/RUN_STATUS.json",
        "qualification": "Two job labels report the same noncached RBE target binary/action pass; both whole jobs failed. Direct case and scenario outcomes remain unknown, with production P0 open.",
    },
}


def seal(raw):
    found = [
        ast.literal_eval(node.value)
        for node in ast.parse(raw).body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "EXPECTED_INDEX_SHA256"
            for t in node.targets
        )
    ]
    require(len(found) == 1, "one index seal")
    return found[0]


def check_scope(name, result):
    require(
        result["attempt"] == 1
        and result["production_P0_closed"] is False
        and result["new_native_execution"] is False,
        "unchanged native scope",
    )
    if name == "windows42":
        require(
            result["source"] == "f5d64639c1bd8e327d48ac3c68593057915c3d0f"
            and result["run"] == 42340694993
            and result["job"] == 128308823747
            and result["job_conclusion"] == "failure"
            and len(result["original_cases"]) == 3
            and all(
                [v["result"] for v in rows] == ["FAILED"]
                for rows in result["original_cases"].values()
            )
            and result["fixed_records"] == 318
            and result["repeated_suffix_records"] == 168
            and result["repeated_suffix_is_independent"] is False
            and result["unique_filesystem_cause"] == "UNKNOWN"
            and result["windows43_included"] is False,
            "three original failures and one fixed observation block",
        )
    else:
        targets = result["targets"]
        require(
            result["source"] == "73e87c4c4dadc154c6b295d8935df2157f817951"
            and result["run"] == 42337376231
            and len(targets) == 2
            and {r["job"] for r in targets} == {128298273965, 128298273981}
            and all(r["status"] == "PASSED" and r["seconds"] == 9.7 for r in targets)
            and targets[0]["binary"] == targets[1]["binary"]
            and targets[0]["action_digest"] == targets[1]["action_digest"]
            and result["whole_jobs_pass"] is False
            and result["independent_GNU_musl_ABI_qualification"] is False
            and result["direct_case_outcomes"]
            == result["three_scenario_outcomes"]
            == "UNKNOWN",
            "same RBE target evidence with direct outcomes unavailable",
        )


def main():
    require(
        sys.flags.optimize == 1 and sys.dont_write_bytecode, "optimized inert reader"
    )
    require(len(sys.argv) == 2 and sys.argv[1] in CASES, "one fixed packet")
    name, config = sys.argv[1], CASES[sys.argv[1]]
    publication = BASE / "round3_native" / config["manifest"]
    package = BASE / "round3_native" / config["folder"]
    api_path = BASE / "round3_win42_linux41_checkpoint_canonical_api.json"
    require(identity(publication)["sha256"] == config["manifest_sha"], "fixed manifest")
    manifest = json.loads(publication.read_bytes())
    require(
        len(manifest["files"]) == len({r["path"] for r in manifest["files"]}) == 7,
        "seven distinct publication files",
    )
    before = {}
    for row in manifest["files"]:
        source = Path(row["local_path"])
        require(
            source.parent == package
            and not source.is_symlink()
            and stat.S_IMODE(source.stat().st_mode) == 0o644
            and row["mode"] == "100644"
            and str(Path(manifest["repo_directory"]) / source.name) == row["path"],
            "ordinary publication source and destination",
        )
        expected = {
            "bytes": row["bytes"],
            "sha256": row["sha256"],
            "git_blob": row["git_blob_sha"],
        }
        require(identity(source) == expected, "every publication byte")
        before[str(source)] = expected
    template = BASE / "round3_native/sdk_product_evidence_20261106/restore.py"
    template_raw = template.read_bytes()
    require(
        identity(template)["sha256"]
        == "af61744d776034fb41dac291fbca63d30082c6ec15df821824b49df4678c8d3d",
        "qualified canonical reader",
    )
    api = json.loads(api_path.read_bytes())
    require(
        api["head"] == "33e32bd254f8d0aa73dd9add724d82869b5dfe62"
        and api["tree"] == "0491e25086ab3734181c2cdbbcf11d9eda0348c3"
        and len(api["leaves"]) == 1,
        "fresh canonical source binding",
    )
    leaf = next(iter(api["leaves"].values()))
    require(
        leaf["sha"] == identity(template)["git_blob"]
        and leaf["mode"] == "100644"
        and leaf["size"] == len(template_raw),
        "canonical source leaf",
    )
    reader = package / "restore.py"
    raw = reader.read_bytes()
    require(
        template_raw.count(seal(template_raw).encode()) == 1
        and template_raw.replace(seal(template_raw).encode(), seal(raw).encode(), 1)
        == raw
        and not any(isinstance(n, ast.Assert) for n in ast.walk(ast.parse(raw))),
        "only literal seal changes with active optimized checks",
    )
    module = runpy.run_path(str(reader), run_name="fixed_in_memory_reader")
    index, recovered = module["read_package"](package)
    require(
        identity(package / "INDEX.json")["sha256"]
        == seal(raw)
        == manifest["index_sha256"]
        == config["index_sha"],
        "sealed index",
    )
    rows = {row["path"]: row for row in index["files"]}
    require(
        len(rows) == len(index["files"]) == len(recovered) == config["files"]
        and set(rows) == set(recovered)
        and sum(map(len, recovered.values())) == config["bytes"],
        "complete selected original roster and bytes",
    )
    for member, data in recovered.items():
        source, row = BASE / member, rows[member]
        mode = source.lstat().st_mode
        require(
            stat.S_ISREG(mode)
            and not source.is_symlink()
            and data == source.read_bytes()
            and len(data) == row["bytes"]
            and hashlib.sha256(data).hexdigest() == row["sha256"]
            and format(stat.S_IMODE(mode), "04o")
            == row["source_permission_bits"]
            == "0644"
            and format(mode, "06o") == row["source_stat_mode"] == "100644",
            "every original byte and original source mode",
        )
        require(
            row["sha256"] not in config["private"]
            and source.suffix != ".zip"
            and not source.name.startswith("job-"),
            "private consoles and ZIPs absent",
        )
        if name == "windows42":
            require("windows_native_access_43" not in member, "43 history is separate")
    for member, digest in config["required"].items():
        require(
            member in recovered
            and hashlib.sha256(recovered[member]).hexdigest() == digest,
            "root native audit and original qualification companions retained",
        )
    status = json.loads(recovered[config["status"]])
    check_scope(name, status)
    roundtrip = json.loads((package / "ROUNDTRIP.json").read_bytes())
    require(
        roundtrip["optimized_verification"]["exit_code"] == 0
        and roundtrip["ordinary_reader_bytes_equal"] is True
        and roundtrip["no_extraction_copy_created"] is True
        and roundtrip["native_execution"] is False,
        "owner byte verification with bounded claims",
    )
    require(
        all(identity(Path(p)) == value for p, value in before.items()),
        "publication inputs unchanged",
    )
    proof = BASE / "round3_local_qualification" / (name + "_checkpoint_root")
    proof.mkdir(exist_ok=False)
    receipt = {
        "observed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scope": "Canonical reader and complete selected original bytes and source modes, in memory only",
        "publication": identity(publication),
        "index": identity(package / "INDEX.json"),
        "canonical_source_API": identity(api_path),
        "reader": identity(reader),
        "reader_only_seal_changed": True,
        "original_files": config["files"],
        "original_bytes": config["bytes"],
        "publication_files": 7,
        "every_selected_original_byte_and_source_mode_equal": True,
        "root_evidence_included": config["required"],
        "private_console_and_execution_ZIP_contents_excluded": True,
        "private_originals_reconstructable_from_this_packet": False,
        "archived_source_executed": False,
        "expanded_restore_written": False,
        "new_native_execution": False,
        "product_P0_closed": False,
        "qualification": config["qualification"],
        "reviewer": identity(Path(__file__)),
    }
    target = proof / "ROOT_REVIEW.json"
    with target.open("x") as stream:
        stream.write(json.dumps(receipt, indent=2) + "\n")
    print(
        json.dumps(
            {
                "packet": name,
                "review": identity(target),
                "files": config["files"],
                "bytes": config["bytes"],
            }
        )
    )


if __name__ == "__main__":
    main()
