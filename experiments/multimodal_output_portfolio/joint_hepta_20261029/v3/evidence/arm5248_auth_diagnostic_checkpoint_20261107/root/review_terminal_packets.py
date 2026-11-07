"""Verify two fixed terminal packets against retained original bytes in memory."""

import argparse
import ast
import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace
import zipfile

BASE = Path("/workspace/scratch/3f6a885bb83c")
HERE = Path("/dev/shm/ndu_root_continuation_20261107")
CANONICAL = BASE / "round3_native/sdk_product_evidence_20261106/restore.py"
CANONICAL_SHA = "af61744d776034fb41dac291fbca63d30082c6ec15df821824b49df4678c8d3d"
PART = "native-evidence.tar.xz.part000.gz"
CASES = {
    "arm5248": {
        "folder": "/dev/shm/ndu_arm5248_auth_checkpoint_20261107",
        "package": "packet",
        "manifest": "PUBLICATION_MANIFEST.json",
        "manifest_sha": "f0276f93fe15e56841308b06138224200c7ab4c09ca61b98969ac51823c4f877",
        "index_sha": "862f4e4d75c75cd19013d036cdc5db60c42c5fc527a63d5669dee8bf25752c4e",
        "members": 50,
        "bytes": 1058948,
        "files": 7,
    },
    "core35": {
        "folder": "/dev/shm/ndu_core35_checkpoint_20261107",
        "package": "package",
        "manifest": "CORE35_CHECKPOINT_PUBLICATION_MANIFEST.json",
        "manifest_sha": "84ffd1a667ac8c9f91842a22161171cbf9f7a65aa3b03ce30ab5cc5eee70ed1e",
        "index_sha": "5420fc0737aa3b81ff14c262fb73f85d738e23af09785bb6ccaf310c0c6303d9",
        "members": 276,
        "bytes": 2265045,
        "files": 11,
    },
}


def require(value, reason):
    if not value:
        raise ValueError(reason)


def identity(raw):
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "git_blob": hashlib.sha1(
            b"blob " + str(len(raw)).encode() + b"\0" + raw
        ).hexdigest(),
    }


def unique(pairs):
    result = {}
    for name, value in pairs:
        require(name not in result, "duplicate JSON key")
        result[name] = value
    return result


def decode(raw):
    return json.loads(raw, object_pairs_hook=unique)


def stamp(value):
    return {
        name: getattr(value, name)
        for name in (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_nlink",
            "st_uid",
            "st_gid",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
    }


def read_original(path):
    path = Path(path)
    require(
        path.is_absolute() and str(path) == os.path.normpath(str(path)),
        "absolute physical source",
    )
    for component in [path.parent, *path.parent.parents]:
        require(
            not component.is_symlink() and component.is_dir(), "no symlink ancestor"
        )
    before = path.lstat()
    require(
        stat.S_ISREG(before.st_mode)
        and before.st_nlink == 1
        and stat.S_IMODE(before.st_mode) in (0o600, 0o644)
        and 0 <= before.st_size <= 4 * 1024 * 1024,
        "bounded regular source",
    )
    descriptor = os.open(
        path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    )
    with os.fdopen(descriptor, "rb") as stream:
        require(stamp(os.fstat(stream.fileno())) == stamp(before), "opened identity")
        raw = stream.read(before.st_size + 1)
        require(stamp(os.fstat(stream.fileno())) == stamp(before), "read identity")
    require(
        stamp(path.lstat()) == stamp(before) and len(raw) == before.st_size,
        "final source identity",
    )
    return raw, {"identity": identity(raw), "stat": stamp(before)}


def seal(raw):
    parsed = ast.parse(raw)
    values = [
        ast.literal_eval(node.value)
        for node in parsed.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "EXPECTED_INDEX_SHA256"
            for target in node.targets
        )
    ]
    require(
        len(values) == 1 and isinstance(values[0], str) and len(values[0]) == 64,
        "one fixed canonical seal",
    )
    return values[0]


class MemoryFile:
    def __init__(self, raw):
        self.raw = raw

    def read_bytes(self):
        return self.raw

    def is_symlink(self):
        return False

    def is_file(self):
        return True

    def stat(self):
        return SimpleNamespace(st_size=len(self.raw))


class MemoryPackage:
    def __init__(self, files):
        self.files = files

    def __truediv__(self, name):
        require(name in {"INDEX.json", PART}, "canonical reader input scope")
        return MemoryFile(self.files[name])


def arm_scope(index, members):
    prefix = "round3_ci/arm5248_auth_checkpoint_inputs/"
    selection = decode(members[prefix + "INCLUSION_EXCLUSION.json"])
    status = decode(members[prefix + "RUN_STATUS.json"])
    root_raw = members[prefix + "root/arm5248_auth_root/ROOT_REVIEW.json"]
    require(
        identity(root_raw)["sha256"]
        == "d20aa76c9ca8e2d90056869ce38037df627a6d514fe81f9f258642aa94bad964",
        "original root auth qualification",
    )
    root = decode(root_raw)
    selected = {row["path"]: row for row in selection["files"]}
    indexed = {row["path"]: row for row in index["files"]}
    controls = set(selection["new_control_paths_bound_by_INDEX"])
    require(
        len(selected) == len(selection["files"]) == 46
        and len(controls) == 4
        and set(selected).isdisjoint(controls)
        and set(indexed) == set(selected) | controls,
        "exact safe originals and four new controls",
    )
    require(
        all(indexed[name] == row for name, row in selected.items()),
        "original selection unchanged",
    )
    require(
        index["excluded"] == selection["exclusions"],
        "complete exclusion records unchanged",
    )
    for key in [
        "run",
        "attempt",
        "job",
        "head",
        "tree",
        "original_just_exit",
        "original_just_wall_seconds",
        "failed_exact_testcases",
        "readiness_failure",
    ]:
        require(status[key] == root[key], "original observed fact unchanged")
    require(
        status["run"] == 42340445031
        and status["job"] == 128307995742
        and status["original_just_exit"] == 100
        and status["readiness_failure"] == "AGENT_B"
        and status["login_record_count"]
        == len(root["all_login_records_recomputed"])
        == 9
        and status["rc_login_address_rejections"] == 4
        and sum(row["status"] == 429 for row in root["all_login_records_recomputed"])
        == 4,
        "bounded original failure observations",
    )
    require(
        status["read_plus_validation_ms"]
        == root["hash_read_plus_validation_elapsed_ms"]
        and status["hashed_bytes"] == root["hash_bytes"]
        and status["observed_hash_spans"] == root["completed_hash_spans"] == 30,
        "read and validation spans not pure CPU",
    )
    require(
        all(
            status[key] is False
            for key in [
                "original_native_audits_fully_replayable_from_packet",
                "new_ARM42_run_qualified_by_this_packet",
                "latency_or_net_gain_claim",
                "business_qualified",
                "all_blockers_closed",
            ]
        ),
        "negative qualification scope retained",
    )
    primary = root["primary_source_files"]
    require(
        len(primary) == 23
        and all(
            any(
                identity(raw)["sha256"] == row["sha256"] and len(raw) == row["bytes"]
                for raw in members.values()
            )
            for row in primary
        ),
        "all twenty-three original primary source bytes present",
    )
    require(
        all(
            Path(name).suffix.lower() not in {".zip", ".gz", ".xml", ".raw"}
            and "/reviewed-diagnostics/" not in name
            for name in members
        ),
        "private raw payload and wrapper classes absent",
    )
    return {
        "run": status["run"],
        "job": status["job"],
        "attempt": 1,
        "original_just_exit": 100,
        "business_qualified": False,
        "new_ARM42_qualification": False,
        "primary_sources": 23,
        "private_native_audit_fully_replayable": False,
    }


def core_scope(index, members):
    approved = {
        "core35/native/core35-13565649343.zip": "30ce4c998331e487af3778b86b29ee7733890e1aeab8357627c530cd004c0e47",
        "core35/native/core35-profile-13565457834.zip": "a919385597f7493b5690d3d0dbf915f36cdcc621be758f5d83a847dcf4acdc13",
    }
    containers, archived = {}, set()
    for name, sha in approved.items():
        require(
            identity(members[name])["sha256"] == sha, "official approved ZIP unchanged"
        )
        with zipfile.ZipFile(io.BytesIO(members[name])) as original:
            require(
                original.testzip() is None
                and "logs/list.stderr.log" not in original.namelist(),
                "official ZIP CRC and rejected stream exclusion",
            )
            containers[sha] = {
                item: original.read(item) for item in original.namelist()
            }
    require(
        {name for name in members if name.endswith(".zip")} == set(approved),
        "only two approved ZIPs",
    )
    for row in index["files"]:
        if "source_container" in row:
            provenance = row["source_container"]
            key = (provenance["archive_sha256"], provenance["member"])
            require(
                key not in archived
                and key[0] in containers
                and key[1] in containers[key[0]]
                and members[row["path"]] == containers[key[0]][key[1]],
                "original ZIP member byte provenance",
            )
            archived.add(key)
    require(
        len(archived) == 166
        and archived
        == {(sha, name) for sha, data in containers.items() for name in data},
        "all 164 accepted originals and two manifests",
    )
    root_raw = members["core35/root_terminal/ROOT_REVIEW.json"]
    require(
        identity(root_raw)["sha256"]
        == "40c6cee412f87e2ecf02a8800211121f18803aa3ebf46cbbf08ef159d17a7db5",
        "original root Core terminal qualification",
    )
    root = decode(root_raw)
    require(
        root["core_direct_case_results"] == "ALL_PASS_ONCE"
        and root["profile_full_mechanism_gate"] == "PASS"
        and root["complete_Core_evidence_gate"] == root["whole_workflow"] == "FAIL"
        and root["rejected_stream_read_or_reconstructed"] is False,
        "original behavioral and completeness boundaries",
    )
    require(
        all(not name.endswith("/logs/list.stderr.log") for name in members)
        and index["excluded"][0]["bytes_read_or_copied"] is False
        and index["excluded"][0]["identity"]
        == root["sole_rejected_slot_identity_only"]["identity"],
        "rejected original identity only",
    )
    return {
        "run": root["run"],
        "job": root["job"],
        "attempt": 1,
        "core7": "PASS_ONCE",
        "profile146": "PASS",
        "complete19": "FAIL",
        "original_ZIP_member_proofs": 166,
        "private_console_included": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=CASES)
    kind = parser.parse_args().kind
    settings, protected = CASES[kind], {}

    def get(path, expected=None):
        raw, record = read_original(path)
        if expected is not None:
            require(
                record["identity"]["sha256"] == expected, "fixed original source hash"
            )
        name = str(path)
        require(
            name not in protected or protected[name] == record,
            "repeated original identity",
        )
        protected[name] = record
        return raw

    folder = Path(settings["folder"])
    package = folder / settings["package"]
    manifest_path = folder / settings["manifest"]
    manifest_raw = get(manifest_path, settings["manifest_sha"])
    manifest = decode(manifest_raw)
    require(
        len(manifest["files"]) == settings["files"]
        and manifest["remote_mutations_performed"] is False,
        "fixed publication scope",
    )
    published = {}
    for row in manifest["files"]:
        path = Path(row["local_path"])
        require(
            path.parent == package
            and row["path"] == manifest["repo_directory"] + "/" + path.name
            and row["mode"] == "100644"
            and path.name not in published,
            "exact publication path and mode",
        )
        raw = get(path, row["sha256"])
        require(
            len(raw) == row["bytes"]
            and identity(raw)["git_blob"]
            == row.get("git_blob", row.get("git_blob_sha")),
            "publication bytes",
        )
        published[path.name] = raw
    require(
        set(os.listdir(package)) == set(published), "complete publication directory"
    )
    canonical = get(CANONICAL, CANONICAL_SHA)
    api = decode(get(HERE / "arm5248_packet_canonical_api.json"))
    leaf = next(iter(api["leaves"].values()))
    require(
        api["head"] == "5de05c612c003114d16fa507285ccafdbd1ac8f9"
        and api["tree"] == "919e06699c053bf166d3c4e87ae60bd9245989e7"
        and len(api["leaves"]) == 1
        and leaf["sha"] == identity(canonical)["git_blob"]
        and leaf["mode"] == "100644"
        and leaf["size"] == 6899,
        "fresh canonical Git authority",
    )
    old_seal = seal(canonical)
    require(
        seal(published["restore.py"]) == settings["index_sha"]
        and canonical.count(old_seal.encode()) == 1
        and canonical.replace(old_seal.encode(), settings["index_sha"].encode(), 1)
        == published["restore.py"],
        "only canonical index-seal literal changed",
    )
    namespace = {
        "__name__": "qualified_canonical_memory_reader",
        "__file__": str(package / "restore.py"),
    }
    exec(compile(published["restore.py"], "<canonical reader only>", "exec"), namespace)
    index, members = namespace["read_package"](MemoryPackage(published))
    require(
        identity(published["INDEX.json"])["sha256"] == settings["index_sha"]
        and len(members) == len(index["files"]) == settings["members"]
        and sum(map(len, members.values())) == settings["bytes"],
        "complete packet identity and totals",
    )
    sources = set()
    for row in index["files"]:
        source = row.get("source_path", row.get("source_local_path"))
        require(
            source not in sources and isinstance(source, str), "distinct real sources"
        )
        sources.add(source)
        raw = get(Path(source), row["sha256"])
        require(
            raw == members[row["path"]]
            and len(raw) == row["bytes"]
            and identity(raw)["git_blob"]
            == row.get("git_blob", row.get("git_blob_sha")),
            "every index archive and original byte",
        )
        mode = protected[source]["stat"]["st_mode"]
        require(
            format(stat.S_IMODE(mode), "04o") == row["source_permission_bits"]
            and format(mode, "06o") == row["source_stat_mode"],
            "original permission record",
        )
    scope = (
        arm_scope(index, members) if kind == "arm5248" else core_scope(index, members)
    )
    for name, record in protected.items():
        require(
            read_original(Path(name))[1] == record, "every original input unchanged"
        )
    report = {
        "observed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "kind": kind,
        "scope": "Exact selected archive, canonical reader and retained result boundaries",
        "publication": identity(manifest_raw),
        "reviewer": identity(Path(__file__).read_bytes()),
        "canonical_template": identity(canonical),
        "canonical_API": protected[str(HERE / "arm5248_packet_canonical_api.json")][
            "identity"
        ],
        "index": identity(published["INDEX.json"]),
        "members": len(members),
        "member_bytes": sum(map(len, members.values())),
        "publication_files": len(published),
        "all_original_bytes_and_source_modes_equal": True,
        "all_original_inputs_unchanged": True,
        "canonical_reader_only_index_literal_changed": True,
        "expanded_copy_created": False,
        "archived_payload_or_native_executed": False,
        "private_rejected_originals_reconstructed": False,
        "observed_scope": scope,
        "all_blockers_closed": False,
    }
    output = HERE / (kind + "_packet_root")
    output.mkdir(exist_ok=False)
    path = output / "ROOT_REVIEW.json"
    with path.open("x") as stream:
        stream.write(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "review": identity(path.read_bytes()),
                "kind": kind,
                "members": len(members),
                "scope": scope,
            }
        )
    )


if __name__ == "__main__":
    main()
