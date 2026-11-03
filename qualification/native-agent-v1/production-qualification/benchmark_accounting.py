"""Source pinning and conservative accounting for every comparison attempt."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from process_metrics_v2 import CgroupScope

CODEX_VERSION = "0.166.0"
CODEX_TAG = "rust-v0.166.0"
CODEX_COMMIT = "6ff1e1ca3b30fc8b914720681fcf5fe62e95f856"
TOKEN_FIELDS = ("input_tokens", "output_tokens", "total_tokens")


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def object_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode()).hexdigest()


def verify_codex_build(path, codex, facade):
    path = Path(path).resolve()
    record = json.loads(path.read_bytes())
    if (record.get("schema") != "hepta.codex-build.v2"
            or record.get("release") != CODEX_VERSION or record.get("tag") != CODEX_TAG
            or record.get("source_commit") != CODEX_COMMIT
            or record.get("build_succeeded") is not True
            or record.get("initial_tracked_and_untracked_clean") is not True
            or record.get("external_lock_packages_unchanged") is not True):
        raise ValueError("comparison requires the actual pinned 0.166.0 build evidence")
    if not record.get("qualification_variant") or len(record.get("commands", [])) != 2:
        raise ValueError("missing original CLI/facade build commands or variant disclosure")
    for command in record["commands"]:
        if command.get("exit_code") != 0 or not command.get("log_sha256"):
            raise ValueError("a pinned build command did not complete")
    for name, executable in (("codex", codex), ("hepta_facade", facade)):
        bound = record.get("binaries", {}).get(name, {})
        if bound.get("sha256") != digest(executable) or bound.get("bytes") != Path(executable).stat().st_size:
            raise ValueError("binary does not match the observed pinned build: " + name)
    files = record.get("provenance_files", {})
    if set(files) != {"bootstrap-observability.patch", "hepta_facade.rs", "SOURCE_PIN.json", "lock-local-versions.patch"}:
        raise ValueError("missing original build provenance files")
    for name, expected in files.items():
        if digest(path.parent / name) != expected:
            raise ValueError("build provenance changed: " + name)
    pin = json.loads((path.parent / "SOURCE_PIN.json").read_bytes())
    if (pin.get("source_commit") != CODEX_COMMIT or pin.get("tag") != CODEX_TAG
            or pin.get("release") != CODEX_VERSION):
        raise ValueError("the original source pin identifies a different release")
    if any(files.get(name) != expected for name, expected in pin.get("qualification_sources_sha256", {}).items()):
        raise ValueError("the qualification adapter differs from the pinned build sources")
    for label, command in zip(("cli-build", "facade-build"), record["commands"]):
        if digest(path.parent / (label + ".log")) != command["log_sha256"]:
            raise ValueError("original build log changed")
    version = subprocess.run([str(codex), "--version"], capture_output=True, text=True,
        timeout=15, check=True).stdout.strip()
    if version != "codex-cli " + CODEX_VERSION or record.get("version_stdout", "").strip() != version:
        raise ValueError("the compared executable does not report the pinned release")
    return record


def _json_lines(path, errors):
    if not path.exists():
        return []
    rows = []
    for index, line in enumerate(path.read_text().splitlines(), 1):
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("ledger row is not an object")
            rows.append(row)
        except ValueError as error:
            errors.append({"file": path.name, "line": index, "error": str(error)})
    return rows


def _terminal_usage(path):
    """Accept a single observed provider terminal; missing usage stays unknown."""
    raw = path.read_bytes()
    terminals = []
    for frame in raw.replace(b"\r\n", b"\n").split(b"\n\n"):
        lines = [line[5:].lstrip(b" ") for line in frame.split(b"\n") if line.startswith(b"data:")]
        if not lines or b"\n".join(lines).strip() == b"[DONE]":
            continue
        try:
            event = json.loads(b"\n".join(lines))
        except (ValueError, UnicodeDecodeError):
            continue  # A truncated frame is not a zero-cost terminal.
        if event.get("type") in ("response.completed", "response.incomplete", "response.failed"):
            terminals.append(event.get("response"))
    if len(terminals) != 1 or not isinstance(terminals[0], dict):
        return {"usage": None, "usage_state": "unknown_missing_or_ambiguous_terminal"}
    terminal = terminals[0]
    usage = terminal.get("usage")
    known = isinstance(usage, dict) and all(type(usage.get(key)) is int and usage[key] >= 0 for key in TOKEN_FIELDS)
    if known and usage["total_tokens"] != usage["input_tokens"] + usage["output_tokens"]:
        known = False
    return {"response_id": terminal.get("id"), "response_model": terminal.get("model"),
        "response_status": terminal.get("status"), "provider_usage": usage,
        "usage": {key: usage[key] for key in TOKEN_FIELDS} if known else None,
        "usage_state": "observed_terminal_usage" if known else "unknown_missing_or_invalid_usage"}


def account_model_attempts(evidence, mode):
    errors = []
    starts = _json_lines(evidence / "model_attempts.jsonl", errors)
    finals = _json_lines(evidence / "model_requests.jsonl", errors)
    attempts = {}
    for started in starts:
        key = started.get("attempt")
        if type(key) is not int or key < 1 or key in attempts:
            errors.append({"error": "duplicate or invalid original model attempt"})
            continue
        attempts[key] = {**started, "capture_settled": False}
    for final in finals:
        key = final.get("attempt")
        if key not in attempts or attempts[key]["capture_settled"]:
            errors.append({"error": "model terminal has no unique started attempt"})
            continue
        attempts[key].update(final, capture_settled=True)
    known = {key: 0 for key in TOKEN_FIELDS}
    unknown = 0
    responses = set()
    for attempt in attempts.values():
        response_name = attempt.get("response_file")
        if (response_name and Path(response_name).name == response_name
                and (evidence / response_name).exists()):
            attempt.update(_terminal_usage(evidence / response_name))
            attempt["response_sha256"] = digest(evidence / response_name)
        else:
            attempt.update(usage=None, usage_state="unknown_no_response_capture")
        if attempt["capture_settled"] and attempt.get("dispatch_state") == "not_dispatched":
            attempt.update(usage={key: 0 for key in TOKEN_FIELDS}, usage_state="verified_not_dispatched")
        response_id = attempt.get("response_id")
        if response_id and response_id in responses:
            attempt.update(usage=None, usage_state="unknown_reused_response_identity")
        elif response_id:
            responses.add(response_id)
        if attempt["usage"] is None:
            unknown += 1
        else:
            for key in TOKEN_FIELDS:
                known[key] += attempt["usage"][key]
    # Files without a durable started row may predate this accounting contract
    # or reflect incomplete evidence. Never call an empty ledger zero cost.
    captured = {p.name for p in evidence.glob("*.request.json")}
    bound = {a.get("request_file") for a in attempts.values() if a.get("request_file")}
    unbound = sorted(captured - bound)
    if unbound:
        errors.append({"error": "request captures missing original attempt ledger", "files": unbound})
    complete = unknown == 0 and not errors and all(a["capture_settled"] for a in attempts.values())
    return {"schema": "hepta.all-model-attempts.v1", "observed_at_ns": time.time_ns(),
        "attempts": [attempts[key] for key in sorted(attempts)], "attempted_requests": len(attempts),
        "unknown_usage_attempts": unknown, "unbound_request_captures": unbound,
        "known_usage_subtotal": known, "exact_usage_total": known if complete else None,
        "complete": complete, "ledger_errors": errors, "usage_is_synthetic": mode == "replay",
        "limits": "Provider usage counts generation, including failed tasks; CPU/GPU compute and monetary cost are not inferred."}


def initial_conditions(evidence, prompt, instructions, tools):
    paths = sorted(evidence.glob("*.request.json"))
    if not paths:
        return {"observed": False, "error": "no initial model request was captured"}
    body = json.loads(paths[0].read_bytes())
    expected = sorted(tools or [], key=lambda item: item["name"])
    actual = body.get("tools", [])
    descriptors = [{key: item.get(key) for key in ("name", "description", "parameters")}
        for item in actual if item.get("type") == "function"]
    expected_descriptors = [{key: item.get(key) for key in ("name", "description", "parameters")}
        for item in expected]
    user_texts = []
    for item in body.get("input", []):
        if item.get("role") != "user":
            continue
        content = item.get("content")
        if isinstance(content, str):
            user_texts.append(content)
        elif isinstance(content, list):
            user_texts.extend(part.get("text") for part in content if part.get("type") == "input_text")
    comparison = {"model": body.get("model"), "instructions": body.get("instructions"),
        "input": body.get("input"), "tools": body.get("tools"),
        "reasoning": body.get("reasoning"), "text": body.get("text"),
        "parallel_tool_calls": body.get("parallel_tool_calls"), "tool_choice": body.get("tool_choice")}
    return {"observed": True, "request_sha256": digest(paths[0]),
        "provider_condition_sha256": object_digest(comparison),
        "instructions_exact": body.get("instructions") == instructions,
        "original_prompt_present": prompt in user_texts,
        "only_original_user_text": user_texts == [prompt],
        "tool_descriptors_exact": sorted(descriptors, key=lambda item: item["name"] or "") == expected_descriptors
            and len(descriptors) == len(actual),
        "requested_policy_sha256": object_digest({"prompt": prompt, "instructions": instructions, "tools": expected}),
        "field_sha256": {key: object_digest(value) for key, value in comparison.items()},
        "framework_added_context_is_recorded_not_rewritten": True}


def summarize(rows):
    by_lane = {}
    for row in rows:
        totals = by_lane.setdefault(row["lane"], {"attempted_tasks": 0, "passed_tasks": 0,
            "failed_tasks": 0, "attempt_wall_ms": 0.0, "known_usage_subtotal": {key: 0 for key in TOKEN_FIELDS},
            "unknown_usage_attempts": 0, "accounting_complete": True})
        totals["attempted_tasks"] += 1
        totals["passed_tasks" if row["status"] == "passed" else "failed_tasks"] += 1
        totals["attempt_wall_ms"] += row.get("attempt_wall_ms", 0.0)
        accounting = row.get("model_accounting", {})
        for key in TOKEN_FIELDS:
            totals["known_usage_subtotal"][key] += accounting.get("known_usage_subtotal", {}).get(key, 0)
        totals["unknown_usage_attempts"] += accounting.get("unknown_usage_attempts", 0)
        totals["accounting_complete"] &= accounting.get("complete") is True
    for totals in by_lane.values():
        totals["exact_usage_total"] = totals["known_usage_subtotal"] if totals["accounting_complete"] else None
    groups = {}
    for row in rows:
        groups.setdefault((row["repeat"], row["case"]), []).append(row)
    parity = []
    for (repeat, case), group in groups.items():
        conditions = [row.get("initial_conditions", {}) for row in group]
        observed = all(c.get("observed") for c in conditions)
        parity.append({"case": case, "repeat": repeat, "lanes": [row["lane"] for row in group],
            "all_initial_requests_observed": observed,
            "same_requested_task_policy": observed and len({c["requested_policy_sha256"] for c in conditions}) == 1,
            "exact_provider_conditions_equal": observed and len({c["provider_condition_sha256"] for c in conditions}) == 1,
            "all_original_prompts_present": observed and all(c["original_prompt_present"] for c in conditions),
            "all_tool_descriptors_exact": observed and all(c["tool_descriptors_exact"] for c in conditions)})
    return {"by_lane_including_failed_tasks": by_lane, "initial_condition_parity": parity,
        "all_original_attempts_included": True, "automatic_retries": 0,
        "resource_efficiency_or_p95_claim_supported": False}


class RuntimeGroups:
    """Only detached jobs admitted by this attempt's fresh controller registry."""
    def __init__(self, controller):
        self.controller = controller
        self.started_ms = time.time_ns() // 1_000_000
        self.known = {}
        self.errors = []

    def scopes(self):
        for path in (self.controller / "jobs").glob("*.json"):
            if path.name in self.known:
                continue
            try:
                record = json.loads(path.read_bytes())
                unit = record["unit"]
                if not unit.startswith("hepta-runtime-job-") or "/" in unit:
                    raise ValueError("unexpected runtime unit")
                group = (Path("/sys/fs/cgroup/user.slice") / f"user-{os.getuid()}.slice"
                    / f"user@{os.getuid()}.service" / "app.slice" / (unit + ".service"))
                self.known[path.name] = {"job_id": record["id"], "cgroup": str(group),
                    "created_during_attempt": record["created_unix_ms"] >= self.started_ms}
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.errors.append({"file": path.name, "error": str(error)})
        return [CgroupScope(Path(row["cgroup"]), new_since_start=row["created_during_attempt"])
            for row in self.known.values()]
