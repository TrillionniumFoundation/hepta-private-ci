"""Retain only exact scanner-accepted originals; never qualify Core."""

import datetime
import json
import os

from hepta_bwrap_profile_contract import (
    COMMAND_IDS,
    PARSER_COMMANDS,
    PROFILE_SHA,
    READS,
    READ_SLOTS,
    SLOTS,
    expected_argv,
    private_dir,
    source_guard,
    validate_caller,
)
from hepta_bwrap_profile_checks import (
    baseline_observation,
    validate_after,
    validate_before,
    validate_loaded,
    validate_precompile,
)
from hepta_core_selected_evidence import ProposalError, identity, read_regular, require
from hepta_bwrap_share_checks import capture_caller, validate_share_mode


def save(path, raw):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(raw)
    path.chmod(0o600)


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def collect():
    from hepta_bwrap_profile import scanner_gate

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
    if "readiness.json" in originals:
        require(
            json.loads(originals["readiness.json"])
            == {"head": current["head"], "scanner_ready_after_setup": True},
            "READINESS_CHANGED",
        )
    require(
        set(result)
        == {
            "commands",
            "reads",
            "files",
            "checks",
            "baseline_association",
            "child_observation",
            "failure_stage",
            "failure_kind",
            "completed",
            "mechanism_verified",
            "policy_lifetime",
            "profile_add_status",
            "share_mode_status",
            "product_qualification",
            "host_read_chunk_bytes",
            "host_read_limit_bytes",
        },
        "RESULT_SCHEMA",
    )
    require(
        type(result["commands"]) is dict and set(result["commands"]) <= COMMAND_IDS,
        "COMMAND_INVENTORY",
    )
    require(
        type(result["reads"]) is dict and set(result["reads"]) <= READ_SLOTS,
        "READ_INVENTORY",
    )
    require(
        type(result["files"]) is dict
        and set(result["files"])
        == present
        - {"source-before.json", "source-after.json", "readiness.json", "result.json"},
        "CAPTURE_INVENTORY",
    )
    require(
        result["host_read_chunk_bytes"] == 4096
        and result["host_read_limit_bytes"] == 4 * 1024 * 1024,
        "READ_LIMIT_CHANGED",
    )
    require(
        result["product_qualification"] is False
        and result["policy_lifetime"] == "DISPOSABLE_HOSTED_VM_TEARDOWN_NOT_OBSERVED",
        "LIFETIME_OR_PRODUCT_CLAIM",
    )
    require(
        result["share_mode_status"]
        in {"NOT_STARTED", "FAILED_OR_UNKNOWN", "TIGHTENED_VERIFIED", "ALREADY_0755"},
        "SHARE_STATE",
    )
    require(
        (result["share_mode_status"] in {"TIGHTENED_VERIFIED", "ALREADY_0755"})
        == result["checks"]["share_mode"],
        "SHARE_STATE_CHECK",
    )
    require(
        result["failure_stage"] is None
        or result["failure_stage"]
        in {
            "share_mode",
            "before",
            "baseline",
            "precompile",
            "preload",
            "load",
            "loaded",
            "post",
            "after",
            "source_after",
        },
        "FAILURE_STAGE",
    )
    require(
        result["failure_kind"] in {None, "CONTRACT_REJECTED", "INTERNAL"}
        and ((result["failure_stage"] is None) == (result["failure_kind"] is None)),
        "FAILURE_KIND",
    )
    require(
        type(result["completed"]) is bool
        and type(result["mechanism_verified"]) is bool,
        "RESULT_FLAGS",
    )
    checks = result["checks"]
    require(
        type(checks) is dict
        and set(checks)
        == {"share_mode", "before", "baseline", "precompile", "loaded", "after"}
        and all(type(value) is bool for value in checks.values()),
        "CHECK_SCHEMA",
    )
    if "profile.raw" in originals:
        require(
            identity(originals["profile.raw"])["sha256"] == PROFILE_SHA,
            "PROFILE_CHANGED",
        )
    captured_logs = set()
    caller_uid = None
    current_caller = capture_caller()
    for phase in ("before", "after"):
        name = f"share-caller.{phase}.json"
        if name in originals:
            observed = json.loads(originals[name])
            observed_uid = validate_caller(observed)
            require(observed == current_caller, "CALLER_CHANGED")
            require(phase == "before" or caller_uid == observed_uid, "CALLER_ORDER")
            caller_uid = observed_uid
    for name, row in result["commands"].items():
        require(
            set(row)
            == {
                "argv",
                "stdin_identity",
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
        require(
            row["argv"]
            == expected_argv(name, result["commands"], caller_uid=caller_uid)
            and row["timeout_seconds"] == 20
            and row["status"] in {"EXITED", "TIMED_OUT", "OS_ERROR"},
            "COMMAND_CHANGED",
        )
        expected_stdin = (
            identity(originals["profile.raw"]) if name in PARSER_COMMANDS else None
        )
        require(row["stdin_identity"] == expected_stdin, "PARSER_STDIN_CHANGED")
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
                and row["errno"] is None
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
            and row["status"] in {"READ", "ABSENT", "UNAVAILABLE", "REJECTED_INPUT"},
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
    validators = {
        "share_mode": lambda: validate_share_mode(originals, result["commands"]),
        "before": lambda: validate_before(originals, result["commands"]),
        "baseline": lambda: baseline_observation(originals, result["commands"]),
        "precompile": lambda: validate_precompile(originals, result["commands"]),
        "loaded": lambda: validate_loaded(originals, result["commands"], "loaded"),
        "after": lambda: validate_after(originals, result["commands"]),
    }
    values = {}
    previous = True
    for key, validate in validators.items():
        require(not checks[key] or previous, "CHECK_ORDER")
        if checks[key]:
            values[key] = validate()
        previous = checks[key]
    require(
        result["baseline_association"] == values.get("baseline")
        and result["child_observation"] == values.get("after"),
        "OBSERVATION_CHANGED",
    )
    require(
        not checks["share_mode"] or result["share_mode_status"] == values["share_mode"],
        "SHARE_VERIFICATION_CHANGED",
    )
    require(
        result["share_mode_status"] != "NOT_STARTED"
        or "share_mode" not in result["commands"],
        "SHARE_COMMAND_STATE",
    )
    load = result["commands"].get("profile_add")
    expected_load = (
        "FAILED_OR_UNKNOWN"
        if result["failure_stage"] == "load"
        else "NOT_STARTED"
        if load is None
        else "ADDED_ENFORCE"
        if checks["loaded"]
        else "EXIT_ZERO_UNVERIFIED"
        if load["status"] == "EXITED"
        and load["exit_code"] == 0
        and load["cleanup_confirmed"]
        else "FAILED_OR_UNKNOWN"
    )
    require(result["profile_add_status"] == expected_load, "LOAD_STATUS_CHANGED")
    if load is not None:
        require(checks["precompile"], "LOAD_WITHOUT_PRECONDITIONS")
    if "post" in result["commands"]:
        require(checks["loaded"], "POST_WITHOUT_VERIFIED_LOAD")
    expected_completed = (
        set(result["commands"]) == COMMAND_IDS
        and set(result["reads"]) == READ_SLOTS
        and all(row["cleanup_confirmed"] for row in result["commands"].values())
        and "source-after.json" in originals
    )
    require(result["completed"] is expected_completed, "COMPLETION_CHANGED")
    verified = (
        expected_completed and all(checks.values()) and result["failure_stage"] is None
    )
    require(result["mechanism_verified"] is verified, "MECHANISM_RESULT_CHANGED")
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
    complete = expected_completed and set(accepted) == SLOTS
    manifest = {
        "source": current,
        "file_inventory": inventory,
        "all_captured_originals_accepted": set(accepted) == set(originals),
        "diagnostic_evidence_complete": complete,
        "mechanism_observed": verified,
        "mechanism_evidence_complete": complete and verified,
        "profile_add_status": expected_load,
        "share_mode_status": result["share_mode_status"],
        "product_qualification": False,
        "raw_logs_rewritten": False,
        "raw_rejected_bytes_encoded_or_uploaded": False,
        "limits": [
            "This one new VM intervention does not establish the old Guardian VM state or any Core case outcome.",
            "The baseline child PID relation is inferred from reviewed bwrap source, not a captured parent-PID trace.",
            "No profiles are replaced or removed. In-memory policy lifetime ends with provider VM teardown, which is not observed here.",
            "A partial or unknown add is never described as leaving the host unchanged.",
            "The fixed directory is kept at 0755 until VM disposal; existing subtree and runtime trust are not proved by that change.",
            "The new sudo/Python helper invocation does not alter the original parser arguments or the ambient scanner.",
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
            f"safe_for_upload=true\npublic_dir={public}\nmechanism_evidence_complete={str(complete and verified).lower()}\n"
        )
