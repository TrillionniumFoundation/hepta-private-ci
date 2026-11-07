"""Retain scanner-accepted originals for one fixed read-only ACL observation."""

import json
import os

from hepta_bwrap_acl_checks import validate_command, validate_report, validate_runtime
from hepta_bwrap_acl_contract import LIMIT, SLOTS, private_dir, source_guard
from hepta_core_selected_evidence import ProposalError, identity, read_regular, require


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def save(path, raw):
    require(len(raw) <= LIMIT, "OUTPUT_TOO_LARGE")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
    path.chmod(0o600)


def collect():
    from hepta_bwrap_acl import scanner_gate

    scan = scanner_gate("collect")
    private = private_dir()
    current = source_guard()
    payload = private / "payload"
    require(payload.is_dir() and not payload.is_symlink(), "INVALID_PAYLOAD_DIR")
    entries = list(payload.rglob("*"))
    require(
        all(
            not path.is_symlink()
            and (path.is_file() or path.relative_to(payload).as_posix() == "logs")
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
        type(result) is dict
        and set(result)
        == {
            "commands",
            "files",
            "completed",
            "failure_stage",
            "failure_kind",
            "scope",
            "observation_verified",
            "mechanism_verified",
            "product_qualification",
            "policy_mutation_attempted",
        },
        "RESULT_SCHEMA",
    )
    require(
        type(result["completed"]) is bool
        and type(result["observation_verified"]) is bool
        and result["scope"] == "READONLY_ACL_INVENTORY"
        and result["mechanism_verified"]
        is result["product_qualification"]
        is result["policy_mutation_attempted"]
        is False,
        "RESULT_CLAIMS",
    )
    require(
        result["failure_stage"]
        in {None, "runtime_before", "read", "runtime_after", "verify", "source_after"}
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
    require(
        type(result["commands"]) is dict
        and set(result["commands"]) <= {"acl_inventory"},
        "COMMAND_INVENTORY",
    )
    command_ok = False
    if "acl_inventory" in result["commands"]:
        command_ok = validate_command(result["commands"]["acl_inventory"])
    logs = {"logs/acl_inventory.stdout.log", "logs/acl_inventory.stderr.log"}
    require(
        not (present & logs) or "acl_inventory" in result["commands"],
        "UNREGISTERED_LOGS",
    )
    runtime = {
        phase: validate_runtime(originals[f"acl-runtime.{phase}.json"])
        for phase in ("before", "after")
        if f"acl-runtime.{phase}.json" in originals
    }
    report_ok = False
    stdout = originals.get("logs/acl_inventory.stdout.log")
    if stdout:
        report_ok = validate_report(stdout)
    verified = (
        command_ok
        and report_ok
        and logs <= present
        and set(runtime) == {"before", "after"}
        and runtime["before"] == runtime["after"]
    )
    require(result["observation_verified"] == verified, "OBSERVATION_CHANGED")
    completed = (
        verified
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
    complete = completed and set(accepted) == SLOTS
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
            "Read-only fixed ACL observation; no permission change, parser, profile, or namespace operation.",
            "Matching captures do not prove an atomic history or historical subtree integrity.",
            "A complete observation does not approve changing the existing ACL refusal.",
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
            and (path.is_file() or path.relative_to(public).as_posix() == "logs")
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
