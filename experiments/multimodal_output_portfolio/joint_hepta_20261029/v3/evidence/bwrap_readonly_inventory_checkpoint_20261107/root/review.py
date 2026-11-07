"""Independently check the readonly inventory ZIP and its inert evidence packet."""

import datetime
import hashlib
import io
import json
from pathlib import Path
import re
import stat
import subprocess
import sys
import zipfile


ROOT = Path("/workspace/scratch/3f6a885bb83c")
OUT = ROOT / "round3_local_qualification/bwrap29_checkpoint_root"
PACKAGE = ROOT / "round3_core_ci/bwrap29_evidence_checkpoint"
NATIVE = (
    ROOT / "round3_core_ci/bwrap_input_inventory_29/native_observations/42324795586"
)
DESTINATION = ROOT / "round3_root_restore_bwrap29_20261107"


def require(value, message):
    if not value:
        raise ValueError(message)


def identity(data):
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "git_blob": hashlib.sha1(
            b"blob " + str(len(data)).encode() + b"\0" + data
        ).hexdigest(),
    }


def api(number):
    wrapper = json.loads((OUT / f"fresh_api_{number}.json").read_bytes())
    require(not wrapper.get("isError"), "successful primary API response")
    return json.loads(wrapper["structuredContent"]["content"])


def main():
    publication = ROOT / "round3_core_ci/BWRAP29_CHECKPOINT_PUBLICATION_MANIFEST.json"
    require(
        identity(publication.read_bytes())["sha256"]
        == "c17c446336d4bc6c66448f2bd5bf9dd408ac58345b29b2802134f26f3d5b81cf",
        "frozen publication manifest",
    )
    manifest = json.loads(publication.read_bytes())
    require(
        len(manifest["files"]) == len({row["path"] for row in manifest["files"]}) == 14,
        "unique complete publication file set",
    )
    for row in manifest["files"]:
        path = Path(row["local_path"])
        require(
            identity(path.read_bytes())
            == {key: row[key] for key in ("bytes", "sha256", "git_blob")},
            "publication file identity",
        )
        require(
            not path.is_symlink()
            and stat.S_IMODE(path.stat().st_mode) == 0o644
            and row["mode"] == "100644",
            "ordinary publication mode",
        )
    index_raw = (PACKAGE / "INDEX.json").read_bytes()
    index = json.loads(index_raw)
    require(
        identity(index_raw)["sha256"]
        == manifest["index_sha256"]
        == "553c2c4ea354c62f2a5983c85ee12abb7a387089a698da59cff4ed39a3ea52ac",
        "fixed sealed index",
    )
    reader = (PACKAGE / "restore.py").read_bytes()
    template = (
        ROOT / "round3_native/sdk_product_evidence_20261106/restore.py"
    ).read_bytes()
    require(
        identity(template)["sha256"]
        == "af61744d776034fb41dac291fbca63d30082c6ec15df821824b49df4678c8d3d",
        "published reader template",
    )
    source_api = json.loads((OUT / "SOURCE_API.json").read_bytes())
    leaf = next(iter(source_api["reader"].values()))
    require(
        len(source_api["reader"]) == 1
        and leaf["sha"] == identity(template)["git_blob"]
        and leaf["size"] == len(template)
        and leaf["mode"] == "100644",
        "fresh canonical reader binding",
    )
    pattern = rb'EXPECTED_INDEX_SHA256 = \(\n    "([a-f0-9]{64})"\n\)'
    old, new = re.findall(pattern, template), re.findall(pattern, reader)
    require(
        len(old) == len(new) == 1
        and new[0].decode() == manifest["index_sha256"]
        and template.replace(old[0], new[0], 1) == reader,
        "only the reader seal changed",
    )
    require(not DESTINATION.exists(), "new inert restore directory")
    command = [
        sys.executable,
        "-B",
        "-O",
        str(PACKAGE / "restore.py"),
        str(DESTINATION),
    ]
    process = subprocess.run(command, capture_output=True)
    for suffix, data in (("stdout", process.stdout), ("stderr", process.stderr)):
        with (OUT / f"restore.{suffix}").open("xb") as stream:
            stream.write(data)
    require(
        process.returncode == 0 and process.stderr == b"",
        "actual optimized restore process",
    )
    totals = json.loads(process.stdout)
    require(
        totals["files"] == len(index["files"]) == manifest["original_files"] == 156
        and totals["bytes"] == manifest["original_bytes"] == 808481
        and not totals["executed_sources"],
        "complete member totals",
    )
    members = {row["path"]: row for row in index["files"]}
    require(
        len(members) == 156
        and set(members)
        == {
            str(path.relative_to(DESTINATION))
            for path in DESTINATION.rglob("*")
            if path.is_file()
        },
        "exact recovered path set",
    )
    for name, row in members.items():
        original, restored = ROOT / name, DESTINATION / name
        raw = restored.read_bytes()
        require(
            raw == original.read_bytes()
            and len(raw) == row["bytes"]
            and hashlib.sha256(raw).hexdigest() == row["sha256"],
            "all original bytes recovered",
        )
        require(
            stat.S_ISREG(restored.lstat().st_mode)
            and stat.S_IMODE(restored.stat().st_mode) == 0o644,
            "inert regular restored file",
        )
        require(
            format(stat.S_IMODE(original.stat().st_mode), "04o")
            == row["source_permission_bits"]
            and format(original.stat().st_mode, "06o") == row["source_stat_mode"],
            "original mode record",
        )
    run, jobs, artifacts, head = (api(number) for number in range(4))
    require(
        run["id"] == 42324795586
        and run["run_attempt"] == 1
        and run["status"] == "completed"
        and run["conclusion"] == "success",
        "original workflow terminal scope",
    )
    require(jobs["total_count"] == len(jobs["jobs"]) == 1, "complete single-job page")
    job = jobs["jobs"][0]
    require(
        job["id"] == 128257475236
        and job["run_id"] == run["id"]
        and job["status"] == "completed"
        and job["conclusion"] == "success",
        "original owning job terminal scope",
    )
    require(
        len(job["steps"]) == 12
        and all(row["conclusion"] == "success" for row in job["steps"]),
        "all original steps completed",
    )
    require(
        artifacts["total_count"] == len(artifacts["artifacts"]) == 1,
        "complete original artifact page",
    )
    artifact = artifacts["artifacts"][0]
    require(
        artifact["id"] == 13555621809
        and artifact["name"] == "bwrap-input-inventory-42324795586-1"
        and not artifact["expired"],
        "original artifact identity",
    )
    raw_zip = (NATIVE / "artifact.zip").read_bytes()
    zip_id = identity(raw_zip)
    require(
        zip_id["bytes"] == artifact["size_in_bytes"] == 6911
        and "sha256:" + zip_id["sha256"] == artifact["digest"]
        and zip_id["sha256"]
        == "45e25fe86bc849b991cd3b6c5d662a52469b9d3ea65bad50caab50149d520519",
        "official raw ZIP bytes",
    )
    slots = {
        "source-before.json",
        "source-after.json",
        "readiness.json",
        "before.paths.json",
        "after.paths.json",
        "result.json",
        "reads/include_01.raw",
        "reads/include_02.raw",
    }
    with zipfile.ZipFile(io.BytesIO(raw_zip)) as archive:
        require(
            archive.testzip() is None
            and len(archive.infolist()) == 9
            and set(archive.namelist()) == slots | {"evidence-manifest.json"},
            "all nine ZIP members CRC and exact inventory",
        )
        raw = {name: archive.read(name) for name in archive.namelist()}
    for name, data in raw.items():
        require(
            data == (NATIVE / "artifact_members" / name).read_bytes(),
            "retained original member bytes",
        )
    evidence = json.loads(raw["evidence-manifest.json"])
    require(set(evidence["file_inventory"]) == slots, "exact eight evidence slots")
    for name, row in evidence["file_inventory"].items():
        require(
            row["status"] == "ACCEPTED"
            and row["rejection_code"] is None
            and row["identity"] == identity(raw[name]),
            "every slot accepted with exact original identity",
        )
    require(
        evidence["all_captured_originals_accepted"]
        and evidence["diagnostic_evidence_complete"]
        and evidence["observer_completed"],
        "complete diagnostic observation",
    )
    source = json.loads(raw["source-before.json"])
    require(
        raw["source-before.json"] == raw["source-after.json"]
        and source == evidence["source"],
        "unchanged source guard observations",
    )
    require(
        source["head"]
        == run["head_sha"]
        == head["sha"]
        == "6b0cc9b9fcd98514ebd7ab1f1954c3d0b072d9a9"
        and source["tree"]
        == head["tree"]["sha"]
        == "62412b059d03f5f328019ca05a799887135cf4ec",
        "exact native source commit and tree",
    )
    require(
        [row["sha"] for row in head["parents"]] == [source["inputs_head"]]
        and source["inputs_head"] == "937c7a87099496aabbf59dcc28570a61e4c984b7",
        "strict stage A parent",
    )
    require(
        source["run_id"] == str(run["id"])
        and source["run_attempt"] == "1"
        and source["all_tracked_worktree_blobs_verified"] == 14936,
        "native source guard run scope",
    )
    require(
        set(source["only_additions"]) == set(source_api["native_source"])
        and len(source["only_additions"]) == 4,
        "exact four proposed tool paths",
    )
    for name, blob in source["only_additions"].items():
        require(
            source_api["native_source"][name]["sha"] == blob
            and source_api["native_source"][name]["mode"] == "100644",
            "fresh source tool identities",
        )
    readiness = json.loads(raw["readiness.json"])
    require(
        readiness["head"] == source["head"] and readiness["scanner_ready_after_setup"],
        "original scanner readiness",
    )
    before, after, result = (
        json.loads(raw[name])
        for name in ("before.paths.json", "after.paths.json", "result.json")
    )
    require(
        before["paths"] == after["paths"]
        and len(before["paths"]) == 13
        and before["uid"] == before["euid"] == after["uid"] == after["euid"] == 1001,
        "same thirteen observations on an unprivileged runner",
    )
    require(
        result["completed"]
        and result["failure_kind"] is None
        and result["failure_stage"] is None,
        "readonly program completed",
    )
    for name, record in result["files"].items():
        require(record == identity(raw[name]), "read results bind exact captured bytes")
    for document in (evidence, result):
        require(
            document["mechanism_verified"] is False
            and document["product_qualification"] is False
            and document["policy_mutation_attempted"] is False,
            "readonly observation has no policy or product promotion",
        )
    expected_includes = {
        "include_01": (
            "/etc/apparmor.d/tunables/home.d/ubuntu",
            337,
            "e1b3a24d2ffdcf2b02f8726941f3c6c32dee3c9222553959a335147494d74a2d",
        ),
        "include_02": (
            "/etc/apparmor.d/tunables/xdg-user-dirs.d/site.local",
            730,
            "d9705b1ab368e32f4cce94f2242c6947b8624985b9c6de2ab4ee01b398dc4703",
        ),
    }
    require(set(result["reads"]) == set(expected_includes), "only two fixed reads")
    for key, (path, size, sha) in expected_includes.items():
        read = result["reads"][key]
        data = raw["reads/" + key + ".raw"]
        require(
            read["path"] == path
            and read["status"] == "READ"
            and read["errno"] is None
            and read["identity"] == identity(data)
            and len(data) == size
            and hashlib.sha256(data).hexdigest() == sha,
            "complete original include bytes",
        )
        require(
            read["before"]
            == read["opened"]
            == read["finished"]
            == read["after"]
            == before["paths"][path]["stat"],
            "stable individual read identity",
        )
        metadata = read["opened"]
        require(
            metadata["uid"] == metadata["gid"] == 0
            and metadata["permissions"] == 0o644
            and metadata["nlink"] == 1
            and stat.S_ISREG(metadata["mode"]),
            "observed include ownership and mode",
        )
        lines = [
            line.strip() for line in data.decode("utf-8").splitlines() if line.strip()
        ]
        require(
            all(line.startswith("#") for line in lines)
            and not any(re.match(r"#\s*include\b", line) for line in lines),
            "observed lines are comments without include directives",
        )
    expected_directories = {
        "/etc/apparmor.d/tunables/home.d": ["site.local", "ubuntu"],
        "/etc/apparmor.d/tunables/multiarch.d": ["site.local"],
        "/etc/apparmor.d/tunables/xdg-user-dirs.d": ["site.local"],
    }
    for name, entries in expected_directories.items():
        row = before["paths"][name]
        require(
            row["entries_status"] == "READ"
            and row["entries_errno"] is None
            and row["entries"] == entries,
            "complete fixed directory list",
        )
    require(
        before["paths"]["/usr/share"]["stat"]["permissions"] == 0o777,
        "writable observed ancestor is retained",
    )
    for name in ("/usr/share/apparmor", "/usr/share/apparmor/extra-profiles"):
        row = before["paths"][name]
        require(
            row["status"] == "ABSENT" and row["errno"] == 2 and row["stat"] is None,
            "missing observed optional paths retained",
        )
    old_index_path = ROOT / "round3_core_ci/bwrap28_evidence_checkpoint_v2/INDEX.json"
    old_index = json.loads(old_index_path.read_bytes())
    require(
        not (set(members) & {row["path"] for row in old_index["files"]}),
        "no source-path overlap with the old failed-run packet",
    )
    receipt = {
        "observed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "publication": identity(publication.read_bytes()),
        "index": identity(index_raw),
        "canonical_reader": identity(template),
        "reader": identity(reader),
        "fresh_API_files": {
            path.name: identity(path.read_bytes())
            for path in sorted(OUT.glob("fresh_api_*.json"))
        },
        "fresh_source_API": identity((OUT / "SOURCE_API.json").read_bytes()),
        "restore_command": command,
        "restore_exit_code": process.returncode,
        "restored_files": 156,
        "restored_bytes": 808481,
        "complete_bytes_and_original_mode_records_equal": True,
        "all_restored_files_inert_0644": True,
        "native_run": run["id"],
        "native_attempt": 1,
        "native_job": job["id"],
        "native_workflow_and_job": "SUCCESS",
        "native_artifact": artifact["id"],
        "original_ZIP": zip_id,
        "ZIP_members_CRC_verified": 9,
        "accepted_original_slots": 8,
        "missing_or_rejected_slots": 0,
        "reported_native_tracked_source_blobs_verified": 14936,
        "snapshot_path_count": 13,
        "snapshots_equal": True,
        "observed_include_bytes": {
            key: value[1] for key, value in expected_includes.items()
        },
        "observed_nonblank_include_lines_are_comments_without_include_directives": True,
        "usr_share_mode": "0777",
        "apparmor_shared_paths": "ABSENT_ENOENT",
        "mechanism_verified": False,
        "product_qualification": False,
        "scanner_or_profile_commands_executed_by_root": False,
        "older_failed_packet": identity(old_index_path.read_bytes()),
        "limits": [
            "This complete observation belongs only to the new VM. It does not fill gaps in the older failed VM.",
            "Matching path snapshots do not establish an atomic history or approve the writable ancestor.",
            "Root checked original API and artifact bytes; the full native source guard count is the source-bound guard's report, not a second reconstruction of the remote worktree.",
            "No parser load, namespace execution, administrative mutation, mechanism or production success is established.",
            "Only the canonical restore program was executed; no archived observer or collected source was executed by this review.",
        ],
    }
    with (OUT / "ROOT_REVIEW.json").open("x") as stream:
        json.dump(receipt, stream, indent=2)
        stream.write("\n")
    print(
        json.dumps(
            {
                "root_review": identity((OUT / "ROOT_REVIEW.json").read_bytes()),
                "restored_files": 156,
                "original_accepted_slots": 8,
                "mechanism_verified": False,
            }
        )
    )


if __name__ == "__main__":
    main()
