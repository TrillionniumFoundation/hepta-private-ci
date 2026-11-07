"""Check every selected Windows source and observation byte in memory."""

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
PACKAGE = ROOT / "round3_native/access_terminal_evidence_20261107"


def need(value, message):
    if not value:
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
    found = [
        ast.literal_eval(n.value)
        for n in ast.parse(raw).body
        if isinstance(n, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "EXPECTED_INDEX_SHA256"
            for t in n.targets
        )
    ]
    need(len(found) == 1, "one fixed reader seal")
    return found[0]


def main():
    need(
        sys.flags.optimize == 1 and sys.dont_write_bytecode,
        "optimized no-bytecode review",
    )
    publication = (
        ROOT / "round3_native/ACCESS_TERMINAL_CHECKPOINT_PUBLICATION_MANIFEST.json"
    )
    publication_raw = publication.read_bytes()
    need(
        identity(publication_raw)["sha256"]
        == "f49c0004b01ec64af48d640a5f9a29987d08f1571093c18a4d779a4f8eb8f140",
        "frozen publication manifest",
    )
    manifest = json.loads(publication_raw)
    need(
        len(manifest["files"]) == len({r["path"] for r in manifest["files"]}) == 7,
        "seven exact publication members",
    )
    for row in manifest["files"]:
        path = Path(row["local_path"])
        need(
            path.parent == PACKAGE
            and path.is_file()
            and not path.is_symlink()
            and stat.S_IMODE(path.stat().st_mode) == 0o644
            and row["mode"] == "100644"
            and row["path"] == manifest["repo_directory"] + "/" + path.name,
            "exact publication location and mode",
        )
        need(
            identity(path.read_bytes())
            == {
                "bytes": row["bytes"],
                "sha256": row["sha256"],
                "git_blob": row["git_blob_sha"],
            },
            "publication original bytes",
        )
    template = ROOT / "round3_native/sdk_product_evidence_20261106/restore.py"
    template_raw = template.read_bytes()
    need(
        identity(template_raw)["sha256"]
        == "af61744d776034fb41dac291fbca63d30082c6ec15df821824b49df4678c8d3d",
        "canonical qualified reader",
    )
    source_api = json.loads((HERE / "SOURCE_API.json").read_bytes())
    need(len(source_api["leaves"]) == 1, "one canonical source leaf")
    leaf = next(iter(source_api["leaves"].values()))
    need(
        leaf["sha"] == identity(template_raw)["git_blob"]
        and leaf["mode"] == "100644"
        and leaf["size"] == len(template_raw),
        "fresh canonical source binding",
    )
    reader = PACKAGE / "restore.py"
    reader_raw = reader.read_bytes()
    need(
        template_raw.count(seal(template_raw).encode()) == 1
        and template_raw.replace(
            seal(template_raw).encode(), seal(reader_raw).encode(), 1
        )
        == reader_raw,
        "only fixed seal changed",
    )
    need(
        not any(isinstance(n, ast.Assert) for n in ast.walk(ast.parse(reader_raw))),
        "gates retained under optimization",
    )
    module = runpy.run_path(str(reader), run_name="fixed_safe_packet_reader")
    index, recovered = module["read_package"](PACKAGE)
    index_identity = identity((PACKAGE / "INDEX.json").read_bytes())
    need(
        index_identity["sha256"]
        == seal(reader_raw)
        == manifest["index_sha256"]
        == "7c21dcf9aff97e344d9a58fdfee8a414ee7f4338d74ec3dbbaedd5994e6f06b9",
        "fixed sealed index",
    )
    rows = {r["path"]: r for r in index["files"]}
    need(
        len(rows) == len(index["files"]) == len(recovered) == 157
        and set(rows) == set(recovered),
        "complete exact original inventory",
    )
    need(sum(len(v) for v in recovered.values()) == 3002691, "original total bytes")
    for name, raw in recovered.items():
        original = ROOT / name
        row = rows[name]
        need(
            raw == original.read_bytes()
            and len(raw) == row["bytes"]
            and identity(raw)["sha256"] == row["sha256"],
            "every selected byte equals original",
        )
        mode = original.lstat().st_mode
        need(
            stat.S_ISREG(mode)
            and format(stat.S_IMODE(mode), "04o") == row["source_permission_bits"]
            and format(mode, "06o") == row["source_stat_mode"],
            "all source mode records retained",
        )
    excluded_hashes = {
        "4f753690d4a13386eaac9a295ac7093e416291757fafc9befeaec09938bda65b",
        "c6a96e31a6f462097d1f70fc3946f00902ab46eb36f16a4ddfa8ae0c5b4c5fbf",
    }
    need(
        all(
            r["sha256"] not in excluded_hashes
            and "metadata_target/" not in p
            and not p.endswith(("job_128266606525.log", "job_128283641857.log"))
            for p, r in rows.items()
        ),
        "private consoles and build output excluded under all names",
    )
    root39 = json.loads(
        recovered["round3_local_qualification/authority5214_root/ROOT_REVIEW.json"]
    )
    root40_raw = recovered[
        "round3_local_qualification/authority5228_root/ROOT_REVIEW.json"
    ]
    need(
        identity(root40_raw)["sha256"]
        == "f9076789729ff1ea02899c2139d75de20c79316b7b290c21042ef54bfc820eae",
        "current complete root native audit",
    )
    root40 = json.loads(root40_raw)
    need(
        root39["product_P0_closed"] is False
        and root39["f3_actual_failure_cause"] == "UNKNOWN"
        and root40["production_P0_closed"] is False
        and root40["root_parsed_original_fixed_records"] == 300
        and root40["f3_unique_failure_cause"] == "UNKNOWN",
        "negative evidence and missing causal explanation retained",
    )
    roundtrip = json.loads((PACKAGE / "ROUNDTRIP.json").read_bytes())
    need(
        roundtrip["actual_restore_process_exit_code"] == 0
        and len(roundtrip["negative_probes"]) == 9
        and all(r["rejected"] is True for r in roundtrip["negative_probes"]),
        "owner reader qualification recorded",
    )
    need(
        json.loads((PACKAGE / "CODESPELL.json").read_bytes())["exit_code"] == 0
        and all(
            r["exit_code"] == 0
            for r in json.loads((PACKAGE / "READER_CHECK.json").read_bytes())["checks"]
        ),
        "owner static gates",
    )
    output = HERE / "ROOT_REVIEW.json"
    need(not output.exists(), "new immutable receipt")
    report = {
        "observed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scope": "Root canonical reader and complete in-memory Windows access terminal packet verification",
        "reviewer": identity(Path(__file__).read_bytes()),
        "publication": identity(publication_raw),
        "index": index_identity,
        "canonical_source_API": identity((HERE / "SOURCE_API.json").read_bytes()),
        "original_files": 157,
        "original_bytes": 3002691,
        "every_original_byte_and_mode_equal": True,
        "reader_only_seal_changed": True,
        "actual_in_memory_read_package_completed": True,
        "expanded_disk_restore": False,
        "archived_sources_executed": False,
        "private_consoles_exported": False,
        "root40_complete_native_review": identity(root40_raw),
        "root40_parsed_records": 300,
        "both_native_targets": "FAILED",
        "f3_unique_failure_cause": "UNKNOWN",
        "production_P0_closed": False,
        "new_native_execution": False,
    }
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(identity(output.read_bytes())))


if __name__ == "__main__":
    main()
