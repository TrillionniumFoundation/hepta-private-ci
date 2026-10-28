"""Strict, versioned qualification contracts; declarations never grant capabilities."""

import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

SCHEMA = "hepta.production-qualification.v1"
LANES = ("app-server", "facade", "native")
SOURCES = ("benchmark_v2.py", "protocol_driver.py", "process_metrics.py",
           "process_metrics_v2.py", "model_gateway.py")
BUDGET = {"context_bytes": 65536, "output_tokens": 256, "model_calls": 4,
          "tool_calls": 3, "tool_output_bytes": 32768,
          "model_timeout_seconds": 120, "tool_timeout_seconds": 60}
CONTROLS = {"control_sum": "sum", "control_lines": "lines", "control_digest": "digest"}
CONTROL_ORACLES = {
    "control_sum": [
        "Read pinned fixture.txt as integers; independently sum all lines.",
        "Exactly one original tool operation and matching call-id feedback; no injected answer.",
    ],
    "control_lines": [
        "Independently count lines in pinned fixture.txt.",
        "Exactly one original tool operation and matching call-id feedback.",
    ],
    "control_digest": [
        "Independently SHA-256 the exact pinned fixture.txt bytes.",
        "Exactly one original tool operation and matching call-id feedback.",
    ],
}
# The pinned runner implements only these complete control contracts. Keeping
# the same prompt cannot authorize a different oracle, capability or fault.
CONTROL_CONTRACTS = {case_id: {
    "id": case_id,
    "capabilities": ["shared_readonly_probe"],
    "input": (f'Call hepta_probe exactly once with task="{task}". '
        "After the tool completes successfully, return exactly its stdout JSON object. "
        "Do not calculate the answer yourself. Do not add markdown, explanation or other text."),
    "oracle": CONTROL_ORACLES[case_id],
    "fault": None,
} for case_id, task in CONTROLS.items()}
REQUIRED = set(CONTROLS) | {"long_output", "pty", "edit", "repair", "multi_tool",
    "mcp_readonly", "third_party_readonly", "cancel", "recover_tool", "recover_process", "recover_model"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def object_keys(value, keys, name):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(f"{name}: expected exactly {sorted(keys)}")


def validate(plan, corpus):
    object_keys(plan, ("schema", "group", "mode", "model", "revisions", "repeats",
        "warmup", "timeout_seconds", "lane_order", "source_root", "source_hashes",
        "fixture", "binaries", "profiles", "optimization_notes", "upstream"), "plan")
    if plan["schema"] != SCHEMA or plan["group"] not in ("behavior_matched", "individually_optimized"):
        raise ValueError("unknown plan schema/group")
    if plan["mode"] not in ("live", "replay") or sorted(plan["lane_order"]) != sorted(LANES):
        raise ValueError("one mode and each lane exactly once are required")
    if type(plan["repeats"]) is not int or not 1 <= plan["repeats"] <= 1000:
        raise ValueError("repeats must be in 1..1000")
    if type(plan["warmup"]) is not bool or type(plan["timeout_seconds"]) is not int or plan["timeout_seconds"] <= 0:
        raise ValueError("invalid warmup/timeout")
    object_keys(plan["model"], ("id", "revision", "revision_evidence_sha256"), "model")
    if not isinstance(plan["model"]["id"], str) or not plan["model"]["id"]:
        raise ValueError("model id is required")
    if plan["model"]["revision"] is not None and not isinstance(plan["model"]["revision"], str):
        raise ValueError("model revision must be text or null")
    object_keys(plan["revisions"], ("private_ci", "runtime", "codex_upstream"), "revisions")
    for value in plan["revisions"].values():
        if value is not None and (not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value)):
            raise ValueError("revision must be a full SHA or null (held)")
    object_keys(plan["profiles"], LANES, "profiles")
    object_keys(plan["optimization_notes"], LANES, "optimization_notes")
    for profile in plan["profiles"].values():
        object_keys(profile, BUDGET, "budget")
        if any(type(v) is not int or v <= 0 for v in profile.values()):
            raise ValueError("positive integer ceilings required")
    if plan["group"] == "behavior_matched" and len({canonical(p) for p in plan["profiles"].values()}) != 1:
        raise ValueError("behavior_matched ceilings differ")
    if plan["group"] == "individually_optimized" and not all(
            isinstance(note, str) and note.strip() for note in plan["optimization_notes"].values()):
        raise ValueError("optimized lanes require nonempty text optimization descriptions")
    object_keys(plan["source_hashes"], SOURCES, "source hashes")
    object_keys(plan["fixture"], ("directory", "files"), "fixture")
    object_keys(plan["fixture"]["files"], ("fixture_tool.py", "fixture.txt"), "fixture files")
    object_keys(plan["binaries"], ("native", "codex", "facade"), "binaries")
    for binary in plan["binaries"].values():
        object_keys(binary, ("path", "sha256"), "binary")
    paths = [plan["source_root"], plan["fixture"]["directory"]] + [b["path"] for b in plan["binaries"].values()]
    if any(path is not None and not isinstance(path, str) for path in paths):
        raise ValueError("paths must be text or null")
    hashes = list(plan["source_hashes"].values()) + list(plan["fixture"]["files"].values())
    hashes += [b["sha256"] for b in plan["binaries"].values()] + [plan["model"]["revision_evidence_sha256"]]
    if any(value is not None and (not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)) for value in hashes):
        raise ValueError("SHA-256 must be 64 lowercase hex characters or null")
    if not isinstance(plan["upstream"], str):
        raise ValueError("upstream must be a URL")
    upstream = urlsplit(plan["upstream"])
    if upstream.scheme not in ("http", "https") or not upstream.hostname or upstream.username or upstream.password or upstream.query or upstream.fragment:
        raise ValueError("upstream must be HTTP(S) without credentials, query or fragment")
    object_keys(corpus, ("schema", "cases"), "corpus")
    ids = [case["id"] for case in corpus["cases"]]
    if corpus["schema"] != SCHEMA or set(ids) != REQUIRED or len(ids) != len(REQUIRED):
        raise ValueError("the complete unique representative corpus is required")
    for case in corpus["cases"]:
        object_keys(case, ("id", "capabilities", "input", "oracle", "fault"), "case")
        if not case["input"] or not case["oracle"] or not case["capabilities"]:
            raise ValueError("empty input/oracle/capability")
        if case["id"] in CONTROLS and case != CONTROL_CONTRACTS[case["id"]]:
            raise ValueError("fixture_v2 cannot execute a different registered control contract")


def preflight(plan):
    """Read-only file checks. Missing pins hold execution; mismatches cannot be bypassed."""
    errors = []
    for key, value in plan["revisions"].items():
        if value is None:
            errors.append(f"missing revision: {key}")
    files = []
    for root, entries in ((plan["source_root"], plan["source_hashes"]),
                          (plan["fixture"]["directory"], plan["fixture"]["files"])):
        files.extend((str(Path(root) / name) if root else None, sha) for name, sha in entries.items())
    files.extend((b["path"], b["sha256"]) for b in plan["binaries"].values())
    for name, expected in files:
        if not name or not Path(name).is_absolute() or not expected or not re.fullmatch(r"[0-9a-f]{64}", expected):
            errors.append(f"missing absolute path or SHA-256: {name}")
            continue
        try:
            if digest(name) != expected:
                errors.append(f"SHA-256 mismatch: {name}")
        except OSError as error:
            errors.append(f"unreadable: {name}: {type(error).__name__}")
    if plan["model"]["id"] != "qwen38-flash-next-uc":
        errors.append("fixture_v2 has a fixed model id; the adapter cannot apply this model")
    if any(profile != BUDGET for profile in plan["profiles"].values()):
        errors.append("fixture_v2 has fixed ceilings; requested profile is not implemented")
    return errors
