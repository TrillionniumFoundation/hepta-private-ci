"""Validate readonly observations and retain only exact scanner-accepted bytes."""

import datetime
import json
import os
from pathlib import Path
import stat

from hepta_bwrap_inventory_contract import (
    DIRECTORIES,
    LIMIT,
    MAX_DIRECTORY_ENTRIES,
    PATHS,
    READS,
    SLOTS,
    STAT_FIELDS,
    private_dir,
    source_guard,
)
from hepta_core_selected_evidence import ProposalError, identity, read_regular, require


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def save(path, raw):
    require(len(raw) <= LIMIT, "OUTPUT_TOO_LARGE")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
    path.chmod(0o600)


def validate_stat(value):
    require(type(value) is dict and set(value) == set(STAT_FIELDS), "STAT_SCHEMA")
    require(all(type(item) is int for item in value.values()), "STAT_TYPES")
    require(
        all(
            value[key] >= 0
            for key in STAT_FIELDS
            if key not in {"mtime_ns", "ctime_ns"}
        ),
        "STAT_RANGE",
    )
    require(value["permissions"] == stat.S_IMODE(value["mode"]), "STAT_MODE")


def validate_snapshot(raw):
    value = json.loads(raw)
    require(set(value) == {"uid", "euid", "captured_utc", "paths"}, "SNAPSHOT_SCHEMA")
    require(
        type(value["uid"]) is int
        and value["uid"] > 0
        and value["euid"] == value["uid"],
        "CALLER_CHANGED",
    )
    stamp = datetime.datetime.fromisoformat(value["captured_utc"])
    require(stamp.utcoffset() == datetime.timedelta(0), "SNAPSHOT_TIME")
    require(
        type(value["paths"]) is dict and set(value["paths"]) == PATHS, "PATH_INVENTORY"
    )
    complete = True
    for name, row in value["paths"].items():
        require(
            set(row)
            == {
                "status",
                "errno",
                "stat",
                "entries",
                "entries_status",
                "entries_errno",
            },
            "PATH_SCHEMA",
        )
        require(
            row["status"]
            in {"REGULAR", "DIRECTORY", "SYMLINK", "OTHER", "ABSENT", "UNAVAILABLE"},
            "PATH_STATUS",
        )
        for key in ("errno", "entries_errno"):
            require(
                row[key] is None or type(row[key]) is int and row[key] > 0, "PATH_ERRNO"
            )
        if row["status"] in {"ABSENT", "UNAVAILABLE"}:
            require(
                row["stat"] is None and row["entries"] is None, "UNAVAILABLE_METADATA"
            )
            if row["status"] == "ABSENT":
                require(row["errno"] == 2, "ABSENCE_ERRNO")
            complete &= row["status"] == "ABSENT"
        else:
            validate_stat(row["stat"])
            mode = row["stat"]["mode"]
            kind = (
                "REGULAR"
                if stat.S_ISREG(mode)
                else "DIRECTORY"
                if stat.S_ISDIR(mode)
                else "SYMLINK"
                if stat.S_ISLNK(mode)
                else "OTHER"
            )
            require(row["status"] == kind and row["errno"] is None, "PATH_TYPE")
        if name in DIRECTORIES:
            require(
                row["entries_status"]
                in {"READ", "UNAVAILABLE", "TOO_MANY", "NOT_DIRECTORY", "CHANGED"},
                "DIRECTORY_STATUS",
            )
            if row["entries_status"] == "READ":
                entries = row["entries"]
                require(
                    row["status"] == "DIRECTORY"
                    and type(entries) is list
                    and all(
                        type(item) is str
                        and item not in {"", ".", ".."}
                        and "/" not in item
                        and "\0" not in item
                        for item in entries
                    )
                    and len(entries) <= MAX_DIRECTORY_ENTRIES
                    and entries == sorted(set(entries))
                    and row["entries_errno"] is None,
                    "DIRECTORY_ENTRIES",
                )
            else:
                require(row["entries"] is None, "INCOMPLETE_DIRECTORY_LIST")
                complete = False
        else:
            require(
                row["entries"] is None
                and row["entries_status"] == "NOT_REQUESTED"
                and row["entries_errno"] is None,
                "UNREQUESTED_DIRECTORY_LIST",
            )
    return value, complete


def collect():
    from hepta_bwrap_inventory import scanner_gate

    scan = scanner_gate("collect")
    private = private_dir()
    current = source_guard()
    payload = private / "payload"
    require(payload.is_dir() and not payload.is_symlink(), "INVALID_PAYLOAD_DIR")
    entries = list(payload.rglob("*"))
    require(
        all(
            not path.is_symlink()
            and (path.is_file() or path.relative_to(payload).as_posix() == "reads")
            for path in entries
        ),
        "INVALID_EVIDENCE_ENTRY",
    )
    present = {
        path.relative_to(payload).as_posix() for path in entries if path.is_file()
    }
    require(present <= SLOTS, "UNKNOWN_EVIDENCE_PATH")
    originals = {name: read_regular(payload / name) for name in present}
    require(all(len(raw) <= LIMIT for raw in originals.values()), "EVIDENCE_LIMIT")
    require(json.loads(originals["source-before.json"]) == current, "SOURCE_CHANGED")
    if "source-after.json" in originals:
        require(json.loads(originals["source-after.json"]) == current, "SOURCE_CHANGED")
    if "readiness.json" in originals:
        require(
            json.loads(originals["readiness.json"])
            == {"head": current["head"], "scanner_ready_after_setup": True},
            "READINESS_CHANGED",
        )
    result = json.loads(originals["result.json"])
    require(
        set(result)
        == {
            "reads",
            "files",
            "completed",
            "failure_stage",
            "failure_kind",
            "scope",
            "mechanism_verified",
            "product_qualification",
            "policy_mutation_attempted",
        },
        "RESULT_SCHEMA",
    )
    require(
        type(result["completed"]) is bool
        and result["scope"] == "READONLY_INCLUDE_INVENTORY"
        and result["mechanism_verified"] is False
        and result["product_qualification"] is False
        and result["policy_mutation_attempted"] is False,
        "RESULT_CLAIMS",
    )
    require(
        result["failure_stage"] in {None, "before", "read", "after", "source_after"}
        and result["failure_kind"] in {None, "CONTRACT_REJECTED", "INTERNAL"}
        and ((result["failure_stage"] is None) == (result["failure_kind"] is None)),
        "FAILURE_SCHEMA",
    )
    require(
        type(result["files"]) is dict
        and set(result["files"])
        == present
        - {"source-before.json", "source-after.json", "readiness.json", "result.json"},
        "CAPTURE_INVENTORY",
    )
    require(
        all(
            value == identity(originals[name])
            for name, value in result["files"].items()
        ),
        "CAPTURE_BYTES_CHANGED",
    )
    snapshots = {}
    for phase in ("before", "after"):
        name = f"{phase}.paths.json"
        if name in originals:
            snapshots[phase] = validate_snapshot(originals[name])
    if set(snapshots) == {"before", "after"}:
        require(
            snapshots["before"][0]["uid"] == snapshots["after"][0]["uid"],
            "CALLER_CHANGED",
        )
    require(
        type(result["reads"]) is dict and set(result["reads"]) <= set(READS),
        "READ_INVENTORY",
    )
    for key, row in result["reads"].items():
        require(
            set(row)
            == {
                "path",
                "status",
                "errno",
                "reason",
                "before",
                "opened",
                "finished",
                "after",
                "identity",
                "parents",
            }
            and row["path"] == READS[key],
            "READ_SCHEMA",
        )
        require(
            row["status"] in {"READ", "ABSENT", "UNAVAILABLE", "REJECTED"}
            and row["reason"]
            in {
                None,
                "OS_ERROR",
                "INPUT_NOT_REGULAR",
                "INPUT_TOO_LARGE",
                "INPUT_CHANGED",
            },
            "READ_STATUS",
        )
        require(
            row["errno"] is None or type(row["errno"]) is int and row["errno"] > 0,
            "READ_ERRNO",
        )
        require(
            type(row["parents"]) is dict
            and set(row["parents"])
            <= {str(path) for path in Path(row["path"]).parents},
            "READ_PARENT_INVENTORY",
        )
        for value in [
            row[name] for name in ("before", "opened", "finished", "after")
        ] + list(row["parents"].values()):
            if value is not None:
                validate_stat(value)
        name = f"reads/{key}.raw"
        require((name in originals) == (row["status"] == "READ"), "READ_BYTES_MISMATCH")
        if row["status"] == "READ":
            require(
                row["errno"] is None
                and row["reason"] is None
                and row["identity"] == identity(originals[name])
                and row["before"] == row["opened"] == row["finished"] == row["after"]
                and row["before"] is not None
                and stat.S_ISREG(row["before"]["mode"])
                and row["before"]["size"] == len(originals[name]),
                "READ_IDENTITY",
            )
            require(
                set(row["parents"]) == {str(path) for path in Path(row["path"]).parents}
                and all(
                    stat.S_ISDIR(value["mode"]) for value in row["parents"].values()
                ),
                "READ_PARENT_TYPE",
            )
        else:
            require(
                row["identity"] is None and row["reason"] is not None,
                "FAILED_READ_IDENTITY",
            )
    require(
        {name for name in present if name.startswith("reads/")}
        == {
            f"reads/{key}.raw"
            for key, row in result["reads"].items()
            if row["status"] == "READ"
        },
        "RAW_READ_INVENTORY",
    )
    completed = (
        set(result["reads"]) == set(READS)
        and set(snapshots) == {"before", "after"}
        and "source-after.json" in originals
        and result["failure_stage"] is None
    )
    require(result["completed"] == completed, "COMPLETION_CHANGED")
    inventory, accepted = {}, {}
    for name in sorted(SLOTS):
        if name not in originals:
            inventory[name] = {
                "status": "MISSING",
                "identity": None,
                "rejection_code": None,
            }
            continue
        raw = originals[name]
        try:
            scan(raw)
            accepted[name] = raw
            inventory[name] = {
                "status": "ACCEPTED",
                "identity": identity(raw),
                "rejection_code": None,
            }
        except ProposalError as error:
            inventory[name] = {
                "status": "REJECTED",
                "identity": identity(raw),
                "rejection_code": str(error),
            }
    complete = (
        completed
        and set(accepted) == SLOTS
        and all(row["status"] == "READ" for row in result["reads"].values())
        and all(value[1] for value in snapshots.values())
    )
    manifest = {
        "source": current,
        "file_inventory": inventory,
        "observer_completed": completed,
        "diagnostic_evidence_complete": complete,
        "all_captured_originals_accepted": len(accepted) == len(originals),
        "mechanism_verified": False,
        "product_qualification": False,
        "policy_mutation_attempted": False,
        "raw_logs_rewritten": False,
        "raw_rejected_bytes_encoded_or_uploaded": False,
        "limits": [
            "Readonly input inventory only; no profile or namespace operation.",
            "Path snapshots and held descriptors do not prove an atomic path history.",
            "Unknown includes and writable-parent conditions are not approved by collection.",
        ],
    }
    raw_manifest = encoded(manifest)
    scan(raw_manifest)
    public = private / "public"
    require(not public.exists() and not public.is_symlink(), "PUBLIC_DIR_EXISTS")
    public.mkdir(mode=0o700)
    for name, raw in accepted.items():
        save(public / name, raw)
    save(public / "evidence-manifest.json", raw_manifest)
    public_entries = list(public.rglob("*"))
    require(
        not public.is_symlink()
        and all(
            not path.is_symlink()
            and (path.is_file() or path.relative_to(public).as_posix() == "reads")
            for path in public_entries
        ),
        "PUBLIC_ENTRY_CHANGED",
    )
    actual = {
        path.relative_to(public).as_posix(): path
        for path in public_entries
        if path.is_file()
    }
    expected = accepted | {"evidence-manifest.json": raw_manifest}
    require(
        set(actual) == set(expected)
        and all(read_regular(actual[name]) == raw for name, raw in expected.items()),
        "PUBLIC_BYTES_CHANGED",
    )
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(
            f"public_dir={public}\nsafe_for_upload=true\ndiagnostic_evidence_complete={str(complete).lower()}\n"
        )
