#!/usr/bin/env python3
"""Audit registered read consumers against one immutable Git tree; never claim execution."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess

CONSUMERS = (
    "compact.engine", "context.compiler", "memory.federation", "memory.retrieval",
    "neuron.runtime", "objective.compiler", "utility.ndu",
)
PORT_PREFIX = "ModulePort::cognitive.read::"
READ_API = re.compile(
    r"\b(?:read_ids_v1|ReadIdsRequestV1|PreparedReadSnapshotV1|ReadRequestV2|"
    r"ReadResultV2|ReadReceipt|AuthoritativeReadResultV1)\b"
)
COMPOSITION = (
    ("owner_acquisition", "codex-rs/hepta-memory/src/lane_c_snapshot.rs", "pub async fn lane_c_snapshot("),
    ("product_read", "codex-rs/hepta-agentd/src/cognitive_context.rs", "pub(crate) async fn read_with_retrieval_context_and_learning("),
    ("owner_cut_view", "codex-rs/hepta-agentd/src/cognitive_read_view.rs", "pub(super) struct OwnerCutReadView"),
    ("final_use", "codex-rs/hepta-agentd/src/cognitive_context.rs", "pub(crate) async fn revalidate_with_retrieval_context("),
    ("physical_consumer", "codex-rs/hepta-infer-worker-host/src/native_app_server.rs", "owner.revalidate_cognitive_context(snapshot).await"),
)


def registered_consumers(value: object) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        identity = value.get("id")
        if isinstance(identity, str) and identity.startswith(PORT_PREFIX):
            result.add(identity.removeprefix(PORT_PREFIX))
        for child in value.values():
            result.update(registered_consumers(child))
    elif isinstance(value, list):
        for child in value:
            result.update(registered_consumers(child))
    return result


def verify_registered(value: object) -> None:
    actual = registered_consumers(value)
    if actual != set(CONSUMERS):
        raise ValueError(f"registered cognitive.read consumer drift: {sorted(actual)}")


def safe_path(path: str) -> str:
    parsed = PurePosixPath(path)
    if not path or parsed.is_absolute() or ".." in parsed.parts or "\\" in path:
        raise ValueError(f"invalid repository path: {path}")
    return parsed.as_posix().rstrip("/")


def audit(root: Path, candidate: str) -> dict:
    if re.fullmatch(r"[0-9a-f]{40}", candidate) is None:
        raise ValueError("candidate must be a complete SHA")
    env = {key: val for key, val in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_NO_REPLACE_OBJECTS="1", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)

    def git(*args: str) -> str:
        return subprocess.check_output(["git", "--literal-pathspecs", *args], cwd=root, env=env, text=True).strip()

    if git("rev-parse", "HEAD") != candidate:
        raise ValueError("working tree is not the requested candidate")
    if git("status", "--porcelain", "--untracked-files=no"):
        raise ValueError("tracked working tree is dirty")
    objects = {}
    for line in git("ls-tree", "-r", candidate).splitlines():
        metadata, path = line.split("\t", 1)
        mode, kind, blob = metadata.split()
        if kind == "blob" and mode in {"100644", "100755"}:
            objects[path] = blob

    def text(path: str) -> str:
        path = safe_path(path)
        if path not in objects:
            raise ValueError(f"missing ordinary source file: {path}")
        return git("show", f"{candidate}:{path}")

    contracts_path = "docs/contracts/CONTRACTS.json"
    verify_registered(json.loads(text(contracts_path)))
    rows = []
    for consumer in CONSUMERS:
        map_path = f"docs/modules/{consumer}/IMPLEMENTATION_MAP.json"
        mapping = json.loads(text(map_path))
        roots = mapping.get("declaredRoots", mapping.get("sourceRoot", []))
        if isinstance(roots, str):
            roots = [roots]
        if not isinstance(roots, list) or not roots:
            raise ValueError(f"no declared roots for {consumer}")
        roots = [safe_path(item.removesuffix("/**")) for item in roots]
        sources = []
        for path, blob in sorted(objects.items()):
            if not path.endswith(".rs") or not any(path.startswith(item + "/") for item in roots):
                continue
            if "/tests/" in path or path.endswith("_tests.rs"):
                continue
            matches = sorted(set(READ_API.findall(text(path))))
            if matches:
                sources.append({"path": path, "blob": blob, "interfaces": matches,
                                "inspection": "lexical_reference_not_execution"})
        tests = sorted({test for operation in mapping.get("operations", [])
                        for test in operation.get("tests", []) if isinstance(test, str)})
        rows.append({
            "consumer": consumer, "contract": PORT_PREFIX + consumer,
            "implementation_map": {"path": map_path, "blob": objects[map_path]},
            "roots": roots, "read_source_references": sources,
            "mapped_tests": [{"path": path, "blob": objects.get(path), "present": path in objects} for path in tests],
            "final_use_responsibility": "consumer_and_existing_effect_owner; per-consumer execution not established",
            "error_mapping_state": "requires_consumer_specific_execution_evidence",
            "migration_state": "registered_source_inspected_execution_unproven",
            "product_execution_proved": False, "independent_acceptance": False,
        })
    composition = []
    for role, path, symbol in COMPOSITION:
        body = text(path)
        if symbol not in body:
            raise ValueError(f"product composition symbol missing: {role}")
        composition.append({"role": role, "path": path, "blob": objects[path], "symbol": symbol,
                            "state": "source_composed_execution_unproven"})
    return {"schema": "hepta.cognitive.read.consumer-audit.v1",
            "candidate": {"commit": candidate, "tree": git("rev-parse", "HEAD^{tree}")},
            "registry_blob": objects[contracts_path], "consumers": rows,
            "product_composition": composition, "activation": False,
            "claim_boundary": "source inspection does not establish build reachability or product migration"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if not output.is_relative_to(root / ".hepta-evidence"):
        raise SystemExit("consumer audit output must be under .hepta-evidence")
    result = audit(root, args.expected_sha)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS_CONSUMER_SOURCE_AUDIT", "consumers": len(result["consumers"]),
                      "product_execution_proved": False}))


if __name__ == "__main__":
    main()
