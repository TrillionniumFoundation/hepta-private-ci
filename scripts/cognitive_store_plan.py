#!/usr/bin/env python3
"""Strict, shared interpretation of the committed cognitive qualification plan.

All entries are validated before any command executes. The expanded command,
working directory, workload environment and limits are bound to its record.
This is a read-only plan parser, not an authority or an execution receipt.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from string import Template

SCHEMA = "hepta.cognitive-store-qualification-plan.v1"
MAX_PLAN_BYTES = 1024 * 1024
MAX_COMMANDS = 128
SPEC_ENV = "HEPTA_COGNITIVE_COMMAND_SPEC_SHA256"
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.json\Z")
WORKLOAD_ENV = re.compile(r"HEPTA_COGNITIVE_[A-Z0-9_]+\Z")


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate qualification JSON field: " + key)
        result[key] = value
    return result


def bounded_integer(value: object, minimum: int, maximum: int) -> int:
    require(type(value) is int and minimum <= value <= maximum, "invalid qualification integer")
    return value


def spec_sha256(spec: dict) -> str:
    return hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode("ascii")).hexdigest()


def expanded(value: object, environment: dict[str, str]) -> str:
    require(isinstance(value, str) and 0 < len(value) <= 16384 and "\0" not in value,
            "invalid qualification argument")
    result = Template(value).substitute(environment)
    require(0 < len(result) <= 16384 and "\0" not in result, "expanded argument exceeds bounds")
    return result


def resolve_plan(plan: dict, root: Path, environment: dict[str, str]) -> tuple[list[dict], list[str]]:
    require(isinstance(plan, dict) and set(plan) ==
            {"schema", "module", "commands", "evidence", "targetHostQualification"},
            "missing or unknown qualification plan field")
    require(plan["schema"] == SCHEMA and plan["module"] == "cognitive.store" and
            plan["targetHostQualification"] is False, "unsupported qualification plan or claim")
    root = root.resolve(strict=True)
    commands = plan["commands"]
    require(isinstance(commands, list) and 1 <= len(commands) <= MAX_COMMANDS,
            "missing or excessive qualification commands")
    result, seen = [], set()
    for item in commands:
        required = {"record", "command", "cwd", "minimumTests", "native", "timeoutSeconds"}
        require(isinstance(item, dict) and required <= set(item) <= required | {"env"},
                "missing or unknown command field")
        name = item["record"]
        require(isinstance(name, str) and NAME.fullmatch(name) is not None and
                len(name) <= 160 and name not in seen, "duplicate or unsafe qualification record")
        seen.add(name)
        relative = item["cwd"]
        require(isinstance(relative, str) and relative and not Path(relative).is_absolute() and
                ".." not in Path(relative).parts and "\\" not in relative and
                Path(relative).as_posix() == relative, "unsafe qualification working directory")
        cwd = root / relative
        resolved = cwd.resolve(strict=True)
        require(cwd == resolved and resolved.is_relative_to(root) and resolved.is_dir(),
                "qualification working directory escapes or redirects the checkout")
        minimum = bounded_integer(item["minimumTests"], 0, 1_000_000)
        timeout = bounded_integer(item["timeoutSeconds"], 1, 21600)
        require(type(item["native"]) is bool, "invalid native-preparation disposition")
        workload = item.get("env", {})
        require(isinstance(workload, dict) and len(workload) <= 32,
                "invalid workload environment")
        # Workload configuration cannot rewrite runner/candidate identity or the
        # spec binding. Values are expanded simultaneously, never order-dependently.
        for key in workload:
            require(isinstance(key, str) and WORKLOAD_ENV.fullmatch(key) is not None and
                    key != SPEC_ENV, "workload cannot replace qualification identity")
        assigned = {key: expanded(value, environment) for key, value in workload.items()}
        env = {**environment, **assigned}
        argv = item["command"]
        require(isinstance(argv, list) and 1 <= len(argv) <= 128, "invalid command argument count")
        argv = [expanded(value, env) for value in argv]
        require(sum(len(value) for value in argv) <= 65536, "command exceeds argument budget")
        result.append({"record": name, "command": argv, "working_directory": str(resolved),
                       "minimum_tests": minimum, "timeout_seconds": timeout,
                       "native": item["native"], "environment": assigned})
    evidence = plan["evidence"]
    require(isinstance(evidence, list) and len(evidence) <= MAX_COMMANDS,
            "invalid evidence inventory")
    paths, names = [], set()
    for value in evidence:
        path = Path(expanded(value, environment))
        require(path.is_absolute() and path.resolve() == path and
                not path.is_relative_to(root) and path.name not in names,
                "evidence must be unique, unredirected and outside the checkout")
        names.add(path.name)
        paths.append(str(path))
    return result, paths


def load_plan(path: Path, root: Path, environment: dict[str, str]) -> tuple[list[dict], list[str]]:
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_PLAN_BYTES,
            "missing, redirected or oversized qualification plan")
    with path.open("rb") as stream:
        data = stream.read(MAX_PLAN_BYTES + 1)
    require(len(data) <= MAX_PLAN_BYTES, "qualification plan exceeds byte budget")
    plan = json.loads(data, object_pairs_hook=no_duplicates)
    return resolve_plan(plan, root, environment)
