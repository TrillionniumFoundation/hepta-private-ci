"""Keep exact accepted diagnostic originals; never qualify the product."""

import json
import os
import datetime

from hepta_bwrap_readonly_contract import (
    COMMAND_IDS,
    COMMANDS,
    MANDATORY,
    PROBE,
    READS,
    READ_SLOTS,
    SLOTS,
    child_observation,
    journal_argv,
    policy_snapshot_equal,
    private_dir,
    source_guard,
)
from hepta_core_selected_evidence import ProposalError, identity, read_regular, require


def save(path, raw):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(raw)
    path.chmod(0o600)


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def collect():
    from hepta_bwrap_readonly import scanner_gate

    scan = scanner_gate("collect")
    private = private_dir()
    payload = private / "payload"
    require(payload.is_dir() and not payload.is_symlink(), "INVALID_PAYLOAD_DIR")
    current = source_guard()
    entries = list(payload.rglob("*"))
    require(
        all(
            not path.is_symlink()
            and (
                path.is_file()
                or path.relative_to(payload).as_posix() in {"logs", "reads"}
            )
            for path in entries
        ),
        "INVALID_EVIDENCE_ENTRY",
    )
    present = {
        path.relative_to(payload).as_posix() for path in entries if path.is_file()
    }
    require(present <= SLOTS, "UNKNOWN_EVIDENCE_PATH")
    originals = {name: read_regular(payload / name) for name in present}
    result = json.loads(originals["result.json"])
    require(json.loads(originals["source-before.json"]) == current, "SOURCE_CHANGED")
    if "source-after.json" in originals:
        require(json.loads(originals["source-after.json"]) == current, "SOURCE_CHANGED")
    require(
        set(result)
        == {
            "commands",
            "reads",
            "files",
            "probe_interval",
            "namespace_observation",
            "completed",
            "internal_failure",
            "observed_policy_identity_stable",
            "child_validation",
        },
        "RESULT_SCHEMA",
    )
    require(
        type(result["commands"]) is dict
        and set(result["commands"]) <= COMMAND_IDS
        and type(result["reads"]) is dict
        and set(result["reads"]) <= READ_SLOTS,
        "RESULT_INVENTORY",
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
            type(result[key]) is bool
            for key in (
                "completed",
                "internal_failure",
                "observed_policy_identity_stable",
            )
        ),
        "RESULT_FLAGS",
    )
    require(
        result["child_validation"] is None or type(result["child_validation"]) is bool,
        "CHILD_VALIDATION",
    )
    require(
        result["namespace_observation"]
        in {"NOT_RUN", "EXITED", "TIMED_OUT", "OS_ERROR"},
        "PROBE_STATUS",
    )
    if "readiness.json" in originals:
        require(
            json.loads(originals["readiness.json"])
            == {"head": current["head"], "scanner_ready_after_setup": True},
            "READINESS_CHANGED",
        )
    captured_logs = set()
    for name, row in result["commands"].items():
        require(
            set(row)
            == {
                "argv",
                "started_utc",
                "finished_utc",
                "status",
                "exit_code",
                "pid",
                "errno",
                "timeout_seconds",
                "cleanup_confirmed",
            },
            "COMMAND_SCHEMA",
        )
        expected = (
            PROBE
            if name == "probe"
            else journal_argv(result["probe_interval"])
            if name == "kernel_journal"
            else COMMANDS[name.split(".", 1)[1]]
        )
        require(
            row["argv"] == expected
            and row["timeout_seconds"] == 20
            and row["status"] in {"EXITED", "TIMED_OUT", "OS_ERROR"},
            "COMMAND_CHANGED",
        )
        require(
            row["exit_code"] is None
            or type(row["exit_code"]) is int
            and -127 <= row["exit_code"] <= 255,
            "INVALID_EXIT",
        )
        require(
            row["pid"] is None or type(row["pid"]) is int and row["pid"] > 0,
            "INVALID_PID",
        )
        require(
            row["errno"] is None or type(row["errno"]) is int and row["errno"] > 0,
            "INVALID_ERRNO",
        )
        require(
            type(row["cleanup_confirmed"]) is bool
            and (
                row["status"] != "EXITED"
                or row["pid"] is not None
                and row["exit_code"] is not None
                and row["cleanup_confirmed"]
            ),
            "INVALID_PROCESS_RESULT",
        )
        start, finish = [
            datetime.datetime.fromisoformat(row[key])
            for key in ("started_utc", "finished_utc")
        ]
        require(
            start.utcoffset() == finish.utcoffset() == datetime.timedelta(0)
            and start <= finish,
            "INVALID_COMMAND_TIME",
        )
        captured_logs.update(
            f"logs/{name}.{stream}.log" for stream in ("stdout", "stderr")
        )
    require(
        captured_logs == {name for name in present if name.startswith("logs/")},
        "COMMAND_LOG_INVENTORY",
    )
    for name, row in result["reads"].items():
        require(set(row) == {"path", "status", "errno"}, "READ_SCHEMA")
        read_name = name.split(".", 1)[1].removesuffix(".raw")
        require(
            row["path"] == READS[read_name]
            and row["status"] in {"READ", "ABSENT", "UNAVAILABLE", "TOO_LARGE"},
            "READ_CHANGED",
        )
        require((name in originals) == (row["status"] == "READ"), "READ_BYTES_MISMATCH")
        require(
            row["errno"] is None or type(row["errno"]) is int and row["errno"] > 0,
            "READ_ERRNO",
        )
    require(
        {name for name in present if name.startswith("reads/")}
        == {name for name, row in result["reads"].items() if row["status"] == "READ"},
        "READ_INVENTORY",
    )
    if "probe" in result["commands"]:
        probe = result["commands"]["probe"]
        require(
            result["probe_interval"] == [probe["started_utc"], probe["finished_utc"]]
            and result["namespace_observation"] == probe["status"],
            "PROBE_RECORD_MISMATCH",
        )
    else:
        require(
            result["probe_interval"] is None
            and result["namespace_observation"] == "NOT_RUN",
            "UNSTARTED_PROBE_RECORD",
        )
    expected_completed = (
        not result["internal_failure"]
        and set(result["commands"]) == COMMAND_IDS
        and set(result["reads"]) == READ_SLOTS
        and result["commands"].get("probe", {}).get("pid") is not None
        and all(row["cleanup_confirmed"] for row in result["commands"].values())
        and "source-after.json" in originals
    )
    require(result["completed"] is expected_completed, "COMPLETION_RECORD_MISMATCH")
    if expected_completed:
        before = json.loads(originals["before.process.json"])
        after = json.loads(originals["after.process.json"])
        require(
            result["observed_policy_identity_stable"]
            is policy_snapshot_equal(result["reads"], result["files"], before, after),
            "POLICY_OBSERVATION_CHANGED",
        )
        probe = result["commands"]["probe"]
        expected_child = (
            child_observation(originals["logs/probe.stdout.log"], before["netns"])
            if probe["status"] == "EXITED" and probe["exit_code"] == 0
            else None
        )
        require(
            result["child_validation"] is expected_child, "CHILD_OBSERVATION_CHANGED"
        )
    for name, expected in result["files"].items():
        require(
            name in originals and identity(originals[name]) == expected,
            "CAPTURE_CHANGED",
        )
    accepted, inventory = {}, {}
    for name in sorted(SLOTS):
        raw = originals.get(name)
        row = {
            "identity": None if raw is None else identity(raw),
            "status": "MISSING",
            "rejection_code": None,
        }
        if raw is not None:
            try:
                scan(raw)
                row["status"] = "ACCEPTED"
                accepted[name] = raw
            except ProposalError as error:
                row["status"], row["rejection_code"] = "REJECTED", str(error)
        inventory[name] = row
    complete = bool(
        result["completed"]
        and not result["internal_failure"]
        and MANDATORY <= set(accepted)
        and set(accepted) == set(originals)
        and json.loads(originals["source-after.json"]) == current
    )
    manifest = {
        "source": current,
        "file_inventory": inventory,
        "all_captured_originals_accepted": set(accepted) == set(originals),
        "diagnostic_evidence_complete": complete,
        "host_file_evidence_fully_available": READ_SLOTS <= set(accepted),
        "namespace_observation": result["namespace_observation"],
        "child_validation": result["child_validation"],
        "observed_policy_identity_stable": result["observed_policy_identity_stable"],
        "product_qualification": False,
        "raw_logs_rewritten": False,
        "raw_rejected_bytes_encoded_or_uploaded": False,
        "limits": [
            "Missing host files or failed optional observation commands remain unknown.",
            "This single new VM observation does not establish the old VM policy or Core case outcome.",
            "The kernel journal is the exact bounded command output, capped to its last 2000 lines in the probe interval.",
        ],
    }
    raw_manifest = encoded(manifest)
    scan(raw_manifest)
    public = private / "public"
    require(not public.exists() and not public.is_symlink(), "PUBLIC_ALREADY_EXISTS")
    public.mkdir(mode=0o700)
    for name, raw in accepted.items():
        save(public / name, raw)
    save(public / "evidence-manifest.json", raw_manifest)
    expected = {**accepted, "evidence-manifest.json": raw_manifest}
    require(
        all(
            not path.is_symlink()
            and (
                path.is_file()
                or path.relative_to(public).as_posix() in {"logs", "reads"}
            )
            for path in public.rglob("*")
        ),
        "PUBLIC_ENTRY_CHANGED",
    )
    require(
        {
            path.relative_to(public).as_posix()
            for path in public.rglob("*")
            if path.is_file()
        }
        == set(expected),
        "PUBLIC_MEMBERS_CHANGED",
    )
    require(
        all(read_regular(public / name) == raw for name, raw in expected.items()),
        "PUBLIC_BYTES_CHANGED",
    )
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(
            f"safe_for_upload=true\npublic_dir={public}\ndiagnostic_evidence_complete={str(complete).lower()}\n"
        )
