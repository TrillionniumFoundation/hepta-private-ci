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
    "compact.engine",
    "context.compiler",
    "memory.federation",
    "memory.retrieval",
    "neuron.runtime",
    "objective.compiler",
    "utility.ndu",
)
PORT_PREFIX = "ModulePort::cognitive.read::"
POLICY_PATH = "docs/modules/cognitive.read/CONSUMER_POLICY.json"
POLICY_SCHEMA = "hepta.cognitive.read.consumer-policy.v1"
AUDIT_SCHEMA = "hepta.cognitive.read.consumer-audit.v2"
MIGRATION_CLASSES = {
    "registered_not_composed",
    "legacy_v1_composed_v2_pending",
    "source_composed_execution_pending",
    "source_composed_product_qualification_pending",
    "owner_source_compiled_lifecycle_pending",
    "authenticated_source_composed_activation_pending",
    "request_local_read_only_established_authenticated_owner_pending",
}
READ_API = re.compile(
    r"\b(?:read_ids_v1|ReadIdsRequestV1|PreparedReadSnapshotV1|ReadRequestV2|"
    r"ReadResultV2|ReadReceipt|AuthoritativeReadResultV1)\b"
)
COMPOSITION = (
    (
        "owner_acquisition",
        "codex-rs/hepta-memory/src/lane_c_selected_snapshot.rs",
        "pub async fn lane_c_snapshot_ids(",
    ),
    (
        "owner_revalidation",
        "codex-rs/hepta-memory/src/lane_c_selected_snapshot.rs",
        "pub async fn revalidate_lane_c_selection(",
    ),
    (
        "product_read",
        "codex-rs/hepta-agentd/src/cognitive_context.rs",
        "pub(crate) async fn read_prepared_with_retrieval_context_and_learning(",
    ),
    (
        "owner_cut_view",
        "codex-rs/hepta-agentd/src/cognitive_read_view.rs",
        "pub(super) struct OwnerCutReadView",
    ),
    (
        "final_use",
        "codex-rs/hepta-agentd/src/cognitive_context_final_use.rs",
        "pub(crate) async fn revalidate_with_retrieval_context(",
    ),
    (
        "physical_consumer",
        "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
        "owner.revalidate_cognitive_context(snapshot).await",
    ),
    (
        "delivery_observation",
        "codex-rs/hepta-infer-core/src/cognitive_delivery.rs",
        "pub fn cognitive_context_delivery(",
    ),
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
        raise ValueError(
            f"registered cognitive.read consumer drift: {sorted(actual)}"
        )


def safe_path(path: str) -> str:
    parsed = PurePosixPath(path)
    if (
        not path
        or parsed.is_absolute()
        or ".." in parsed.parts
        or "\\" in path
    ):
        raise ValueError(f"invalid repository path: {path}")
    return parsed.as_posix().rstrip("/")


def policy_by_consumer(value: object) -> dict[str, dict]:
    if not isinstance(value, dict) or value.get("schema") != POLICY_SCHEMA:
        raise ValueError(
            "cognitive.read consumer policy has the wrong schema"
        )
    rows = value.get("consumers")
    if not isinstance(rows, list):
        raise ValueError(
            "cognitive.read consumer policy must contain a consumer list"
        )
    policies: dict[str, dict] = {}
    required_text = (
        "expectedProductCallerState",
        "migrationClass",
        "adoptedReadBoundary",
        "finalUseResponsibility",
        "errorMappingRequirement",
    )
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("consumer policy rows must be objects")
        consumer = row.get("consumer")
        if (
            not isinstance(consumer, str)
            or consumer not in CONSUMERS
            or consumer in policies
        ):
            raise ValueError(
                f"invalid or duplicate consumer policy row: {consumer}"
            )
        for field in required_text:
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError(
                    f"{consumer}: missing policy field {field}"
                )
        if row["migrationClass"] not in MIGRATION_CLASSES:
            raise ValueError(
                f"{consumer}: unsupported migration class"
            )
        minimum = row.get("minimumMappedProductCallers")
        if type(minimum) is not int or minimum < 0:
            raise ValueError(
                f"{consumer}: invalid minimumMappedProductCallers"
            )
        required = row.get("requiredExecutionEvidence")
        if (
            not isinstance(required, list)
            or not required
            or any(
                not isinstance(item, str) or not item.strip()
                for item in required
            )
        ):
            raise ValueError(
                f"{consumer}: invalid requiredExecutionEvidence"
            )
        policies[consumer] = row
    if set(policies) != set(CONSUMERS):
        raise ValueError(
            f"consumer policy set drift: {sorted(policies)}"
        )
    return policies


def mapped_tests(
    mapping: dict,
    objects: dict[str, str],
) -> list[dict]:
    result = {}
    for operation in mapping.get("operations", []):
        for reference in operation.get("tests", []):
            path = (
                reference
                if isinstance(reference, str)
                else reference.get("path")
                if isinstance(reference, dict)
                else None
            )
            symbol = (
                reference.get("symbol")
                if isinstance(reference, dict)
                else None
            )
            if path is not None:
                path = safe_path(path)
            row = {
                "path": path,
                "symbol": symbol,
                "blob": objects.get(path),
                "present": path in objects,
                "declared_reference": reference,
            }
            result[json.dumps(row, sort_keys=True)] = row
    return [result[key] for key in sorted(result)]


def mapped_product_callers(
    mapping: dict,
    objects: dict[str, str],
    source_text,
) -> list[dict]:
    callers = mapping.get("productCallers", [])
    if callers is None:
        callers = []
    if not isinstance(callers, list):
        raise ValueError(
            "productCallers must be a list when present"
        )
    result = []
    for caller in callers:
        if not isinstance(caller, dict):
            raise ValueError(
                "productCallers entries must be objects"
            )
        path = caller.get("sourcePath", caller.get("path"))
        symbol = caller.get("nativeSymbol", caller.get("symbol"))
        if (
            not isinstance(path, str)
            or not isinstance(symbol, str)
            or not symbol
        ):
            raise ValueError(
                "product caller requires sourcePath/path "
                "and nativeSymbol/symbol"
            )
        path = safe_path(path)
        present = path in objects
        symbol_present = present and symbol in source_text(path)
        result.append(
            {
                "path": path,
                "blob": objects.get(path),
                "symbol": symbol,
                "state": caller.get("state"),
                "present": present,
                "symbol_present": symbol_present,
            }
        )
    return result


def selected_claim_flags(mapping: dict) -> dict[str, object]:
    boundary = mapping.get("claimBoundary", {})
    if not isinstance(boundary, dict):
        return {}
    return {
        key: value
        for key, value in sorted(boundary.items())
        if key
        in {
            "activation",
            "productExecutionProved",
            "independentAcceptance",
            "release",
        }
        or key.endswith("ProductExecutionProved")
        or key.endswith("ReceiptProved")
    }


def audit(root: Path, candidate: str) -> dict:
    if re.fullmatch(r"[0-9a-f]{40}", candidate) is None:
        raise ValueError("candidate must be a complete SHA")
    env = {
        key: val
        for key, val in os.environ.items()
        if not key.startswith("GIT_")
    }
    env.update(
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
    )

    def git(*args: str) -> str:
        return subprocess.check_output(
            ["git", "--literal-pathspecs", *args],
            cwd=root,
            env=env,
            text=True,
        ).strip()

    if git("rev-parse", "HEAD") != candidate:
        raise ValueError(
            "working tree is not the requested candidate"
        )
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
            raise ValueError(
                f"missing ordinary source file: {path}"
            )
        return git("show", f"{candidate}:{path}")

    contracts_path = "docs/contracts/CONTRACTS.json"
    verify_registered(json.loads(text(contracts_path)))
    policies = policy_by_consumer(
        json.loads(text(POLICY_PATH))
    )

    rows = []
    for consumer in CONSUMERS:
        policy = policies[consumer]
        map_path = (
            f"docs/modules/{consumer}/IMPLEMENTATION_MAP.json"
        )
        mapping = json.loads(text(map_path))
        if mapping.get("module") != consumer:
            raise ValueError(
                f"{consumer}: implementation map identity mismatch"
            )
        actual_caller_state = mapping.get("productCallerState")
        if (
            actual_caller_state
            != policy["expectedProductCallerState"]
        ):
            raise ValueError(
                f"{consumer}: productCallerState drift: "
                f"{actual_caller_state!r}"
            )
        boundary = mapping.get("claimBoundary", {})
        if (
            not isinstance(boundary, dict)
            or boundary.get("activation") is not False
        ):
            raise ValueError(
                f"{consumer}: activation must remain explicitly false"
            )

        roots = mapping.get(
            "declaredRoots",
            mapping.get("sourceRoot", []),
        )
        if isinstance(roots, str):
            roots = [roots]
        if not isinstance(roots, list) or not roots:
            raise ValueError(
                f"no declared roots for {consumer}"
            )
        roots = [
            safe_path(item.removesuffix("/**"))
            for item in roots
        ]

        sources = []
        for path, blob in sorted(objects.items()):
            if (
                not path.endswith(".rs")
                or not any(
                    path == item
                    or path.startswith(item + "/")
                    for item in roots
                )
            ):
                continue
            if "/tests/" in path or path.endswith("_tests.rs"):
                continue
            matches = sorted(
                set(READ_API.findall(text(path)))
            )
            if matches:
                sources.append(
                    {
                        "path": path,
                        "blob": blob,
                        "interfaces": matches,
                        "inspection": (
                            "lexical_reference_not_execution"
                        ),
                    }
                )

        mapped_operations = []
        for operation in mapping.get("operations", []):
            path = operation.get("sourcePath")
            if isinstance(path, str):
                path = safe_path(path)
            mapped_operations.append(
                {
                    "operation": operation.get("operation"),
                    "symbol": operation.get("nativeSymbol"),
                    "path": path,
                    "blob": objects.get(path),
                    "present": (
                        path in objects if path else False
                    ),
                    "declared_state": operation.get("state"),
                }
            )
        if any(
            not row["present"] for row in mapped_operations
        ):
            raise ValueError(
                f"{consumer}: mapped operation source is missing"
            )

        tests = mapped_tests(mapping, objects)
        if any(not row["present"] for row in tests):
            raise ValueError(
                f"{consumer}: mapped test source is missing"
            )

        product_callers = mapped_product_callers(
            mapping,
            objects,
            text,
        )
        minimum = policy["minimumMappedProductCallers"]
        if len(product_callers) < minimum:
            raise ValueError(
                f"{consumer}: expected at least {minimum} "
                "mapped product callers"
            )
        if any(
            not row["present"] or not row["symbol_present"]
            for row in product_callers
        ):
            raise ValueError(
                f"{consumer}: mapped product caller or symbol "
                "is missing"
            )

        flags = selected_claim_flags(mapping)
        rows.append(
            {
                "consumer": consumer,
                "contract": PORT_PREFIX + consumer,
                "implementation_map": {
                    "path": map_path,
                    "blob": objects[map_path],
                },
                "roots": roots,
                "read_source_references": sources,
                "direct_read_interface_state": (
                    "lexical_reference_present_execution_unproven"
                    if sources
                    else "no_direct_reference_in_declared_roots"
                ),
                "mapped_operations": mapped_operations,
                "declared_product_caller_state": (
                    actual_caller_state
                ),
                "product_callers": product_callers,
                "mapped_tests": tests,
                "migration": {
                    "class": policy["migrationClass"],
                    "adopted_read_boundary": (
                        policy["adoptedReadBoundary"]
                    ),
                    "minimum_mapped_product_callers": minimum,
                    "final_use_responsibility": (
                        policy["finalUseResponsibility"]
                    ),
                    "error_mapping_requirement": (
                        policy["errorMappingRequirement"]
                    ),
                    "required_execution_evidence": (
                        policy["requiredExecutionEvidence"]
                    ),
                },
                "claim_flags": flags,
                "product_execution_proved": boundary.get(
                    "productExecutionProved",
                    False,
                ),
                "independent_acceptance": boundary.get(
                    "independentAcceptance",
                    False,
                ),
                "activation": False,
                "audit_execution_proved": False,
            }
        )

    composition = []
    for role, path, symbol in COMPOSITION:
        body = text(path)
        if symbol not in body:
            raise ValueError(
                f"product composition symbol missing: {role}"
            )
        composition.append(
            {
                "role": role,
                "path": path,
                "blob": objects[path],
                "symbol": symbol,
                "symbol_present": True,
                "state": (
                    "source_composed_execution_unproven"
                ),
            }
        )
    return {
        "schema": AUDIT_SCHEMA,
        "candidate": {
            "commit": candidate,
            "tree": git("rev-parse", "HEAD^{tree}"),
        },
        "registry": {
            "path": contracts_path,
            "blob": objects[contracts_path],
        },
        "policy": {
            "path": POLICY_PATH,
            "blob": objects[POLICY_PATH],
            "schema": POLICY_SCHEMA,
        },
        "consumers": rows,
        "product_composition": composition,
        "activation": False,
        "product_execution_proved_by_audit": False,
        "claim_boundary": (
            "Exact registry, policy, map, source, "
            "caller-symbol and test-blob inspection does not "
            "establish build reachability, product execution, "
            "independent acceptance or activation."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if not output.is_relative_to(root / ".hepta-evidence"):
        raise SystemExit(
            "consumer audit output must be under .hepta-evidence"
        )
    result = audit(root, args.expected_sha)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "PASS_CONSUMER_SOURCE_AUDIT_V2",
                "consumers": len(result["consumers"]),
                "product_execution_proved": False,
            }
        )
    )


if __name__ == "__main__":
    main()
