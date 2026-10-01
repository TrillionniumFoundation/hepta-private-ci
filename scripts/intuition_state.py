#!/usr/bin/env python3
"""Generate source-state projections; never infer execution or approval.

--check is read-only and suitable for qualification. --write is an ordinary
source-authoring operation and is forbidden inside qualification workflows.
Existing technical prose outside the generated block is preserved verbatim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATE = "docs/modules/intuition.policy/CURRENT_STATE.json"
MAP = "docs/modules/intuition.policy/IMPLEMENTATION_MAP.json"
DOCS = (
    "docs/modules/intuition.policy/TECHNICAL.md",
    "docs/modules/intuition.policy/OPERATIONS.md",
    "docs/modules/intuition.policy/CI_EVIDENCE.md",
    "qualification/module-execution-dossiers/detail/intuition.policy.md",
)
CONTRACTS = "docs/modules/intuition.policy/CONTRACTS.md"
START = "<!-- intuition-source-state:begin -->"
END = "<!-- intuition-source-state:end -->"
FLAGS = (
    "is_production_implemented",
    "happy_path_verified",
    "edge_failures_verified",
    "has_independent_acceptance_proof",
)
FACT_IDS = {
    "native_policy",
    "authenticated_roles",
    "host_commit",
    "admission_receipt",
    "authority_read",
    "startup_profile",
    "telemetry",
    "source_qualification",
    "source_projection",
}
GAP_IDS = {
    "durable_handoff",
    "transport_receipt",
    "generation_recovery",
    "typed_domains",
    "legacy_consumers",
    "exact_execution",
    "operator_acceptance",
}
MAX_BYTES = 2_000_000


def pairs_unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(text: str) -> dict[str, Any]:
    value = json.loads(
        text,
        object_pairs_hook=pairs_unique,
        parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)),
    )
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def keys(value: Any, expected: set[str], name: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{name}: unknown or missing fields")


def text(value: Any, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 1200
        or any(character in value for character in ("\n", "\r", "|", "<", ">"))
    ):
        raise ValueError(f"{name}: invalid bounded single-line text")
    return value


def safe_file(root: Path, name: str, *, must_exist: bool = True) -> Path:
    path = PurePosixPath(name)
    if not isinstance(name, str) or path.is_absolute() or "\\" in name or ":" in name:
        raise ValueError("invalid relative source path")
    if any(part in {".", ".."} for part in name.split("/")) or path.as_posix() != name:
        raise ValueError("noncanonical source path")
    if path.parts[0] not in {"codex-rs", "docs", "qualification", "scripts", ".github"}:
        raise ValueError("source path is outside registered roots")
    cursor = root
    for part in path.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError(f"symlink source path: {name}")
    if cursor.exists():
        if not cursor.is_file() or cursor.stat().st_size > MAX_BYTES:
            raise ValueError(f"invalid source file: {name}")
    elif must_exist:
        raise ValueError(f"missing source file: {name}")
    return cursor


def validate(state: dict[str, Any], root: Path) -> None:
    keys(
        state,
        {"schema", "module", "authority", "completion", "facts", "gaps", "contracts"},
        "state",
    )
    if (state["schema"], state["module"], state["authority"]) != (
        "hepta.intuition.source-state.v1",
        "intuition.policy",
        "source_state_only",
    ):
        raise ValueError("unsupported source-state identity")
    keys(state["completion"], set(FLAGS), "completion")
    if any(state["completion"][flag] is not False for flag in FLAGS):
        raise ValueError("source-state projection cannot mint completion or acceptance")
    for collection, expected_ids in (("facts", FACT_IDS), ("gaps", GAP_IDS)):
        values = state[collection]
        if not isinstance(values, list) or len(values) != len(expected_ids):
            raise ValueError(f"{collection}: missing requirements")
        if any(not isinstance(item, dict) for item in values):
            raise ValueError(f"{collection}: invalid row")
        if {item.get("id") for item in values} != expected_ids:
            raise ValueError(f"{collection}: duplicate, unknown or omitted requirement")
    for fact in state["facts"]:
        keys(
            fact,
            {"id", "summary", "state", "source", "symbol", "tests", "evidence"},
            "fact",
        )
        if fact["state"] not in {"source_present", "source_partial"}:
            raise ValueError("a source fact cannot claim verified execution")
        for field in ("summary", "symbol", "evidence"):
            text(fact[field], field)
        source = safe_file(root, fact["source"])
        if fact["symbol"] not in source.read_text(encoding="utf-8"):
            raise ValueError(f"missing symbol for {fact['id']}")
        if not isinstance(fact["tests"], list) or not 1 <= len(fact["tests"]) <= 8:
            raise ValueError("fact must identify bounded test sources")
        for name in fact["tests"]:
            safe_file(root, name)
    for gap in state["gaps"]:
        keys(gap, {"id", "required"}, "gap")
        text(gap["required"], "required")
    contracts = state["contracts"]
    if not isinstance(contracts, list) or not 1 <= len(contracts) <= 32:
        raise ValueError("missing bounded contract matrix")
    names = set()
    for contract in contracts:
        keys(contract, {"name", "layer", "status"}, "contract")
        for field in contract:
            text(contract[field], field)
        if contract["name"] in names:
            raise ValueError("duplicate contract")
        names.add(contract["name"])


def canonical_digest(state: dict[str, Any]) -> str:
    data = json.dumps(
        state, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return hashlib.sha256(data).hexdigest()


def generated_block(state: dict[str, Any]) -> str:
    rows = [
        START,
        "## Canonical source-state projection",
        "",
        f"Source: `{STATE}`; content SHA-256: `{canonical_digest(state)}`.",
        "",
        "These are inspected source facts, not compilation, runtime, independent acceptance or release receipts.",
        "All four production completion predicates remain false. Current execution identity belongs only to immutable command artifacts.",
        "",
        "| Requirement | Source state | Scope |",
        "| --- | --- | --- |",
    ]
    for fact in state["facts"]:
        rows.append(f"| `{fact['id']}` | `{fact['state']}` | {fact['summary']} |")
    rows += ["", "Remaining closure requirements:", ""]
    rows += [f"- **{gap['id']}**: {gap['required']}" for gap in state["gaps"]]
    rows += [
        "",
        f"Version and requirement-to-test/artifact mappings: `{CONTRACTS}`.",
        END,
    ]
    return "\n".join(rows) + "\n"


def replace_block(original: str, block: str, *, initialize: bool = False) -> str:
    if START not in original and END not in original and initialize:
        head, separator, tail = original.partition("\n")
        if not separator or not head.startswith("# "):
            raise ValueError("document must have an existing title")
        return head + "\n\n" + block + "\n" + tail
    if original.count(START) != 1 or original.count(END) != 1:
        raise ValueError("missing or duplicate generated block markers")
    start, end = original.index(START), original.index(END) + len(END)
    if start >= end:
        raise ValueError("reversed generated block markers")
    if original[end : end + 1] == "\n":
        end += 1
    return original[:start] + block + original[end:]


def contract_document(state: dict[str, Any]) -> str:
    rows = [
        "# intuition.policy contracts and evidence traceability",
        "",
        "Generated from CURRENT_STATE.json by scripts/intuition_state.py. Source references are not test-pass evidence.",
        "",
        "## Version matrix",
        "",
        "| Contract | Layer | Status |",
        "| --- | --- | --- |",
    ]
    rows += [
        f"| `{c['name']}` | {c['layer']} | {c['status']} |" for c in state["contracts"]
    ]
    rows += [
        "",
        "## Implemented request sequence",
        "",
        "```text",
        "Immutable startup profile / current signed ObjectiveStart",
        "  -> existing canonical seven-owner preparation",
        "  -> authenticated generator/evaluator/observer evidence",
        "  -> native explicit risk routing / immutable host pins",
        "  -> sole writer lock / fresh owner clock / current trust and three-role revalidation",
        "  -> reject-only canonical seven-owner / RunStart fence; selected original evaluation proof revalidation",
        "  -> selected-only LedgerWriter commit with independent witness",
        "  -> repeated canonical currentness check / final run/context admission with retained policy receipt",
        "  -> in-process bound outcome (not a wire or durable delivery acknowledgement)",
        "```",
        "",
        "A post-policy failure retains the exact acknowledged receipt and its typed cause. The kernel and receipt grant no dispatch authority.",
        "The canonical final-use callback can reject admission but receives only a read-only clock interface. The sink samples time again and revalidates policy qualification after the callback. These checks do not create a cross-owner durable transaction or restart reconciliation.",
        "",
        "## Durable orchestration target, not a completed state machine",
        "",
        "```text",
        "Prepared(intent durable before effect)",
        "  -> PolicyCommitted(owner receipt verified)",
        "  -> RunStarted -> ContextAttached -> Delivered(explicit acknowledgement)",
        "Any interrupted stage -> ReconcileRequired -> current-authority exact replay",
        "Revoked/stale/unverifiable state -> Quarantined (no silent compatibility fallback)",
        "```",
        "",
        "Do not treat tracing output, a clean drop/reopen, or a digest-only record as durable authenticated recovery. The Agentd orchestration journal must not replace the sole authoritative learning ledger or its independent witness.",
        "",
        "## Requirements, source tests and immutable evidence",
        "",
        "| Requirement | Source and symbol | Test sources | Required execution evidence |",
        "| --- | --- | --- | --- |",
    ]
    for f in state["facts"]:
        tests = "; ".join(f"`{name}`" for name in f["tests"])
        rows.append(
            f"| `{f['id']}` | `{f['source']}` / `{f['symbol']}` | {tests} | {f['evidence']} |"
        )
    rows += [
        "",
        "Qualification requires the fixed source commit/tree, fixed base and recomputed merge tree, real command exit codes and logs, retained binaries, and independent same-run evidence agreement. An authoring job never supplies this acceptance.",
        "",
        "## Digest boundaries",
        "",
        "Generator identity/order, scorer outputs and assignment distribution remain separately committed. Product receipts bind original risk, matched profile rule, full propensities and disposition. Historical risk encoding is a read-only compatibility view; it cannot alter the request used by the native kernel.",
        "",
        "Historical generator completeness evidence V1 still binds the V1 candidate-set digest, including utility, confidence, OOD and assignment probability. V2 scorer/distribution separation does not remove that compatibility signing coupling; uncoupling it requires a new signed payload version and consumer migration.",
        "",
        "The private prepared digest uses hepta.agentd.prepared-intuition.v3 and binds qualification lifetime plus admitted trust generation/distribution. The committed service digest uses hepta.agentd.committed-intuition.v2 and additionally binds final-use time and current trust distribution. Historical durable ProductionDecisionV2 encodings remain unchanged.",
        "",
        "The in-process admission digest binds the service receipt, authenticated decision, host binding, dispatch proposal, immutable run snapshot, context attachment and observed run revision. It does not redefine the V1 transport or claim remote delivery.",
        "",
    ]
    return "\n".join(rows)


def project(root: Path, *, write: bool = False) -> list[str]:
    state = load_json(safe_file(root, STATE).read_text(encoding="utf-8"))
    validate(state, root)
    mapping_path = safe_file(root, MAP)
    mapping = load_json(mapping_path.read_text(encoding="utf-8"))
    if mapping.get("full_completion_predicate") != state["completion"]:
        raise ValueError(
            "implementation map completion disagrees with source-only state"
        )
    projected = dict(mapping)
    projected["sourceStateProjection"] = {
        "source": STATE,
        "contentSha256": canonical_digest(state),
        "facts": state["facts"],
        "gaps": state["gaps"],
        "isExecutionProof": False,
    }
    outputs = {
        MAP: json.dumps(projected, indent=2, ensure_ascii=False) + "\n",
        CONTRACTS: contract_document(state),
    }
    block = generated_block(state)
    for name in DOCS:
        original = safe_file(root, name).read_text(encoding="utf-8")
        outputs[name] = replace_block(original, block, initialize=write)
    changed = []
    for name, expected in outputs.items():
        path = safe_file(root, name, must_exist=False)
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current != expected:
            changed.append(name)
            if write:
                path.write_text(expected, encoding="utf-8", newline="\n")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args()
    try:
        drift = project(ROOT, write=args.write)
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.exit(2, f"intuition source-state rejected: {error}\n")
    if drift and args.check:
        parser.exit(1, "intuition source-state drift:\n" + "\n".join(drift) + "\n")
    print(
        "intuition source-state projections are synchronized (not execution acceptance)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
