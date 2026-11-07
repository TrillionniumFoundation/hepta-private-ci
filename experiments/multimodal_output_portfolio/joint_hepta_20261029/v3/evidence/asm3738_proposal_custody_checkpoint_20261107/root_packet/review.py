"""Verify the frozen safe packet in memory, without expanding private evidence."""

import ast
import datetime
import hashlib
import json
from pathlib import Path
import runpy
import stat
import sys


ROOT = Path("/workspace/scratch/3f6a885bb83c")
HERE = Path(__file__).resolve().parent
PACKAGE = ROOT / "round3_ci/asm3738_proposal_custody_checkpoint_20261107"


def need(condition, message):
    if not condition:
        raise ValueError(message)


def identity(raw):
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "git_blob": hashlib.sha1(
            b"blob " + str(len(raw)).encode() + b"\0" + raw
        ).hexdigest(),
    }


def seal(raw):
    values = [
        ast.literal_eval(n.value)
        for n in ast.parse(raw).body
        if isinstance(n, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "EXPECTED_INDEX_SHA256"
            for t in n.targets
        )
    ]
    need(len(values) == 1, "one fixed seal")
    return values[0]


def main():
    need(
        sys.flags.optimize == 1 and sys.dont_write_bytecode,
        "optimized no-bytecode review",
    )
    publication = ROOT / "round3_ci/ASM3738_PROPOSAL_CUSTODY_EVIDENCE_PUBLICATION.json"
    raw = publication.read_bytes()
    need(
        identity(raw)["sha256"]
        == "99ec6cf48d8b23332481c79a35b1070de7c7cd95ee1a22822eee1444c1a1aafa",
        "frozen publication manifest",
    )
    manifest = json.loads(raw)
    need(
        len(manifest["files"]) == len({r["path"] for r in manifest["files"]}) == 12
        and manifest["publication_file_count"] == 12,
        "complete publication set",
    )
    need(
        sum(r["bytes"] for r in manifest["files"])
        == manifest["publication_bytes"]
        == 3742322,
        "publication byte count",
    )
    for row in manifest["files"]:
        path = Path(row["source_file"])
        need(
            path == PACKAGE / row["path"]
            and path.is_file()
            and not path.is_symlink()
            and stat.S_IMODE(path.stat().st_mode) == 0o644
            and row["mode"] == "100644",
            "ordinary exact publication file",
        )
        need(
            identity(path.read_bytes())
            == {key: row[key] for key in ("bytes", "sha256", "git_blob")},
            "publication bytes",
        )
    template = ROOT / "round3_native/sdk_product_evidence_20261106/restore.py"
    template_raw = template.read_bytes()
    need(
        identity(template_raw)["sha256"]
        == "af61744d776034fb41dac291fbca63d30082c6ec15df821824b49df4678c8d3d",
        "canonical qualified reader bytes",
    )
    source_api = json.loads((HERE / "SOURCE_API.json").read_bytes())
    need(len(source_api["leaves"]) == 1, "one canonical reader leaf")
    leaf = next(iter(source_api["leaves"].values()))
    need(
        (leaf["sha"], leaf["size"], leaf["mode"])
        == (identity(template_raw)["git_blob"], len(template_raw), "100644"),
        "fresh canonical reader source",
    )
    reader = PACKAGE / "restore.py"
    reader_raw = reader.read_bytes()
    need(
        template_raw.count(seal(template_raw).encode()) == 1
        and template_raw.replace(
            seal(template_raw).encode(), seal(reader_raw).encode(), 1
        )
        == reader_raw,
        "only index seal changes",
    )
    need(
        not any(isinstance(n, ast.Assert) for n in ast.walk(ast.parse(reader_raw))),
        "gates retained under optimization",
    )
    module = runpy.run_path(str(reader), run_name="fixed_safe_packet_reader")
    index, recovered = module["read_package"](PACKAGE)
    need(
        identity((PACKAGE / "INDEX.json").read_bytes()) == manifest["index"]
        and manifest["index"]["sha256"] == seal(reader_raw),
        "sealed index identity",
    )
    rows = {r["path"]: r for r in index["files"]}
    need(
        len(rows)
        == len(index["files"])
        == len(recovered)
        == manifest["source_file_count"]
        == 397
        and set(rows) == set(recovered),
        "complete original inventory",
    )
    need(
        sum(len(v) for v in recovered.values())
        == manifest["raw_source_bytes"]
        == 12359701,
        "original total bytes",
    )
    for name, data in recovered.items():
        original = ROOT / name
        row = rows[name]
        need(
            data == original.read_bytes()
            and identity(data)
            == {key: row[key] for key in ("bytes", "sha256", "git_blob")},
            "every original byte identity",
        )
        need(
            stat.S_ISREG(original.lstat().st_mode)
            and format(stat.S_IMODE(original.stat().st_mode), "04o")
            == row["original_mode"],
            "original source mode",
        )
    excluded = [
        "round3_ci/arm_sha256_asm37/local_manifest_metadata/stdout.json",
        "round3_ci/arm_sha256_asm37/local_manifest_metadata/stderr.log",
        "round3_ci/arm_sha256_asm37/runs/42327609941/job-128266432617.log",
        "round3_ci/arm_sha256_custody38/runs/42331975252/job-128280323713.log",
    ]
    need(not set(excluded) & set(rows), "private originals excluded")
    need(
        all(
            r["sha256"]
            not in {
                "97a2a2eb9a94e790c8ed5ea76fe430f3d4a8f4fb0c197f60f9f3bf1c034e76a4",
                "12887ac1c31fd479986abbd3466ac38f5b961783079715370d68019d8bfb470f",
            }
            for r in rows.values()
        ),
        "native private consoles absent under all member names",
    )
    root37 = json.loads(
        recovered["round3_local_qualification/asm37_terminal_root/ROOT_REVIEW.json"]
    )
    root38_path = (
        ROOT / "round3_local_qualification/asm38_terminal_root/ROOT_REVIEW.json"
    )
    root38_raw = root38_path.read_bytes()
    need(
        identity(root38_raw)["sha256"]
        == "6fdf9aa4f41ac6657a63695af3b053fcb612be4c894f1dbf29eea72ff6d951a3",
        "external root terminal receipt",
    )
    root38 = json.loads(root38_raw)
    native38 = json.loads(
        recovered[
            "round3_ci/arm_sha256_custody38/runs/42331975252/SAFE_NATIVE_TERMINAL_OBSERVATIONS.json"
        ]
    )
    need(
        root37["failed_stat_operand"] == "UNKNOWN"
        and root37["artifact_count"] == 0
        and root37["complete_evidence_qualified"] is False,
        "old failure remains unknown",
    )
    need(
        native38["fixed_file_stat_observations"]
        == root38["registered_stat_observations"]
        and native38["original_command_exit_records"] == root38["original_commands"],
        "new terminal independently agrees",
    )
    need(
        native38["accepted_artifact_count"] == root38["artifact_count"] == 0
        and native38["qualification"] is root38["complete_evidence_qualified"] is False,
        "no accepted ASM output",
    )
    need(
        manifest["publication_ready"] is True
        and manifest["old_packets_modified"] is False
        and manifest["codespell"]["exit_code"] == 0
        and all(c["exit_code"] == 0 for c in manifest["ruff"]["commands"]),
        "owner bounded checks",
    )
    result = {
        "observed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scope": "Root canonical reader and complete in-memory safe packet verification",
        "publication": identity(raw),
        "index": manifest["index"],
        "source_api": identity((HERE / "SOURCE_API.json").read_bytes()),
        "original_files": len(recovered),
        "original_bytes": sum(len(v) for v in recovered.values()),
        "all_original_bytes_and_modes_equal": True,
        "reader_only_seal_changed": True,
        "actual_in_memory_read_package_completed": True,
        "expanded_disk_restore": False,
        "archived_sources_executed": False,
        "private_native_consoles_published": False,
        "old37_operand": "UNKNOWN",
        "new38_operand": "size_at_most_64MiB",
        "new38_root_companion": identity(root38_raw),
        "old37_artifact_count": 0,
        "new38_artifact_count": 0,
        "asm_lock_or_graph_qualified": False,
        "new_native_run": False,
    }
    out = HERE / "ROOT_REVIEW.json"
    need(not out.exists(), "new receipt")
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(identity(out.read_bytes())))


if __name__ == "__main__":
    main()
