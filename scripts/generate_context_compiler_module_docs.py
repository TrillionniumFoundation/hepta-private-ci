#!/usr/bin/env python3
"""Generate current state projections; retain detailed baseline design bytes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = Path("docs/modules/context.compiler/CURRENT_STATE.json")
OUTPUTS = {
    "technical": Path("docs/modules/context.compiler/TECHNICAL.md"),
    "map": Path("docs/modules/context.compiler/IMPLEMENTATION_MAP.json"),
    "manifest": Path("docs/modules/context.compiler/MODULE_MANIFEST.json"),
    "dossier": Path("qualification/module-execution-dossiers/detail/context.compiler.md"),
    "product": Path("docs/modules/context.compiler/CURRENT_PRODUCT_PATH.md"),
}


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def load_state(root=ROOT):
    state = json.loads((root / STATE_PATH).read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    if state["schemaVersion"] != 1 or state["module"] != "context.compiler":
        raise ValueError("unsupported module-state schema")
    for key in ("runtimeSourceAnchor", "runtimeSourceTree", "reviewedBaseSha"):
        if not re.fullmatch(r"[0-9a-f]{40}", state[key]):
            raise ValueError("source anchors must be full Git object identities")
    if state["maturity"]["exactHeadExecution"] != "unverified":
        raise ValueError("source state does not establish exact-head execution")
    for key in ("independentAcceptance", "activation", "release"):
        if state["maturity"][key] is not False:
            raise ValueError("source generation cannot self-grant acceptance or activation")
    if state["knownOpenItems"] and state["status"]["v2ProviderClosure"] == "complete":
        raise ValueError("open closure gates contradict complete status")
    return state


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_runtime_sources(state, root=ROOT):
    """Verify registered source bytes; this is not an exhaustive Rust call graph."""
    seen = set()
    for entry in state.get("runtimeSourceFiles", []):
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts or entry["path"] in seen:
            raise ValueError("invalid or duplicate registered source path")
        if not re.fullmatch(r"[0-9a-f]{40}", entry["blobSha"]):
            raise ValueError("registered source needs an exact Git blob")
        seen.add(entry["path"])
        target = root / relative
        if any((root / parent).is_symlink() for parent in (relative, *relative.parents)):
            raise ValueError("registered source may not traverse a symlink")
        content = target.read_bytes()
        actual = hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
        if actual != entry["blobSha"]:
            raise ValueError(f"registered source drift: {relative}")


def validate_bindings(state, root=ROOT):
    validate_runtime_sources(state, root)
    validate_consumer_execution(state, root)
    for reference in state["designReferences"]:
        content = (root / reference["path"]).read_bytes()
        actual = hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
        if actual != reference["blobSha"]:
            raise ValueError(f"retained design drift: {reference['path']}")
    for binding in state["sourceBindings"]:
        source = (root / binding["path"]).read_text(encoding="utf-8")
        module = (root / binding["moduleRoot"]).read_text(encoding="utf-8")
        caller = (root / binding["productCaller"]).read_text(encoding="utf-8")
        if binding["symbol"] not in source or binding["moduleDeclaration"] not in module or binding["symbol"] not in caller:
            raise ValueError(f"registered source/caller anchor missing: {binding['path']}")
    # These checks establish source-navigation anchors, not type-checking,
    # exhaustive call-graph reachability, native execution or authority honesty.


def validate_consumer_execution(state, root=ROOT):
    """Navigation checks only; exact runtime passes come from external logs."""
    registered = {entry["path"] for entry in state.get("runtimeSourceFiles", [])}
    identifiers = set()
    for row in state.get("consumerExecution", []):
        if row["id"] in identifiers:
            raise ValueError("duplicate consumer trace identity")
        identifiers.add(row["id"])
        if row["authenticatedProductE2E"] != "unverified" or row["exactExecution"] != "CI_EXACT_HEAD":
            raise ValueError("source trace cannot self-certify execution")
        definition = row["definition"]
        consumer = row.get("consumer")
        if (consumer is None) != (row["sourceState"] == "not_composed"):
            raise ValueError("consumer source state contradicts callsite")
        for anchor in [definition] + ([consumer] if consumer is not None else []):
            if anchor["path"] not in registered:
                raise ValueError("consumer source anchor is not blob-bound")
            source = (root / anchor["path"]).read_text(encoding="utf-8")
            if anchor["symbol"] not in source or anchor.get("call", "") not in source:
                raise ValueError("missing consumer source anchor")
        names = row.get("nativeTests", [])
        if len(names) != len(set(names)) or bool(names) != bool(row.get("command")):
            raise ValueError("invalid consumer native inventory")
        for test in row.get("testSources", []):
            if test["path"] not in registered or test["name"] not in names:
                raise ValueError("test source is not bound to the native inventory")
            if f"fn {test['name'].split('::')[-1]}(" not in (root / test["path"]).read_text(encoding="utf-8"):
                raise ValueError("native test definition missing")
        if {test["name"] for test in row.get("testSources", [])} != set(names):
            raise ValueError("native inventory lacks complete test source mapping")


def consumer_table(state):
    rows = ["| Capability | Definition | Actual source consumer | Native command | Authenticated product E2E |",
            "|---|---|---|---|---|"]
    for row in state.get("consumerExecution", []):
        definition = row["definition"]
        consumer = row.get("consumer")
        caller = f"`{consumer['path']}::{consumer['symbol']}`" if consumer else "Not composed"
        rows.append(f"| `{row['id']}` | `{definition['path']}::{definition['symbol']}` | {caller} | "
                    f"`{row.get('command') or 'none'}` | unverified |")
    return "\n".join(rows)


def bullets(values):
    return "\n".join(f"- {value}" for value in values)


def repository_map(value, state):
    """Expose the detailed contract through the repository's shared map schema.

    Consumer anchors describe source composition, never authenticated product
    execution. Preserve the contract inventory and its more detailed statuses.
    Source objects are rebound explicitly with the state, not silently at render.
    """
    root = "codex-rs/hepta-context-compiler"
    operations = []
    callers = []
    for row in state["consumerExecution"]:
        definition = row["definition"]
        operations.append({
            "operation": row["id"], "designOperation": row["id"],
            "nativeSymbol": definition["symbol"], "sourcePath": definition["path"],
            "sourcePathExists": True, "mappingClass": "owner_native",
            "state": row["sourceState"], "authority": "none",
            "delegatedCallees": [],
            "tests": [f"{test['path']}::{test['name']}" for test in row["testSources"]],
        })
        if row["consumer"] is not None:
            caller = row["consumer"]
            binding = {"sourcePath": caller["path"], "nativeSymbol": caller["symbol"]}
            if binding not in callers:
                callers.append(binding)
    value.update({
        "schema": "hepta.module-implementation-map.v3", "schemaVersion": 3,
        "contractStatus": value["status"],
        "status": {"implemented": True, "composed": True, "qualified": False},
        "sourceBase": {"commit": state["runtimeSourceAnchor"], "tree": state["runtimeSourceTree"]},
        "observedAtHead": {"commit": state["runtimeSourceAnchor"], "tree": state["runtimeSourceTree"]},
        "observedSourcePaths": [root, "codex-rs/Cargo.toml", "codex-rs/Cargo.lock"],
        "sourceIdentityPolicy": "candidate_or_exact_observation_v1",
        "laneId": "LANE-C-MEMORY", "owner": "intelligence-platform", "deputy": "security-authority",
        "technicalGuide": "docs/modules/context.compiler/V3_DEVELOPMENT.md",
        "declaredRoots": [root], "resolvedRoots": [root], "sourceRoot": [root],
        "sourceRootPresent": True, "productionImplementation": False,
        "productCallerState": "source_composed_authenticated_ingress_unverified",
        "productionWriterState": "not_established",
        "operations": operations, "productCallers": callers,
        "sourceObjects": state["implementationMapSourceObjects"],
        "claimBoundary": {
            "implementedOperationMappingComplete": True, "nativeSourceMappingComplete": False,
            "sourceRootPresent": True, "productionImplementation": False,
            "productExecutionProved": False, "independentAcceptance": False,
            "activation": False, "release": False,
        },
    })
    return value


def render_all(state, root=ROOT):
    digest = canonical_hash(state)
    header = (
        "<!-- GENERATED CURRENT STATE: edit CURRENT_STATE.json; detailed design is retained separately. -->\n"
        f"\nState SHA-256: `{digest}`. Source anchor: `{state['runtimeSourceAnchor']}`.\n"
        "The source anchor is provenance, not the final tested head. Only external execution receipts bind a final source/merge object.\n"
    )
    rows = ["| Dimension | Current state |", "|---|---|"]
    for key, value in state["maturity"].items():
        rows.append(f"| `{key}` | `{str(value).lower()}` |")
    current = "\n".join(rows)
    graph = """```text
current registry/optimizer path (provisional admission remains open)
  -> compile_prompt_registry_v2 -> compile_v2
  -> compiler-owned canonical bundle -> build_attachment
  -> Agentd prompt_runtime + exact_context_delivery
  -> Core / codex-api exact encoded HTTP body
  -> verify_responses_developer_context
  -> exclusive observer Proving claim (before await)
  -> host final-request proof / tokenizer / durable pre-send
  -> exclusive expiry recheck -> same-body transport
  -> provider terminal -> existing owner reconciliation
```
The structural slot guard is not an independent admission authority. The expiry
recheck is not a registry revocation check. Full late-terminal recovery and an
attempt-bound acknowledgement remain open. V3 files listed below are not
counted as active merely because they exist.
"""
    graph = state.get("productCallGraph", graph)
    documents = {}
    for kind, title in [
        ("technical", "context.compiler technical development guide"),
        ("dossier", "context.compiler execution dossier"),
        ("product", "context.compiler current product path"),
    ]:
        path = OUTPUTS[kind]
        references = []
        for reference in state["designReferences"]:
            relative = os.path.relpath(reference["path"], path.parent)
            references.append(f"[{Path(reference['path']).name}]({relative}) — retained Git blob `{reference['blobSha']}`")
        documents[path] = (
            f"# {title}\n" + header + "\n## 1. Current implementation and evidence state\n\n" + current
            + "\n\n## 2. Direct-source changes in this follow-up\n\n" + bullets(state["implementedThisFollowup"])
            + "\n\n## 3. Current product call path\n\n" + graph
            + "\n## 4. Dormant integration inputs\n\n" + bullets([f"`{item['path']}`: {item['reason']}" for item in state["dormantSource"]])
            + "\n\n## 5. Remaining implementation and qualification gates\n\n" + bullets(state["knownOpenItems"])
            + "\n\n## 6. Verification\n\n"
            + state.get("verificationNarrative", "Execution evidence must be read from the exact-candidate receipts.")
            + "\n\n"
            + "The canonical workflow uses separate source-head and deterministic synthetic-merge lanes. "
            + "Both must retain passing receipts with source/base/tested commit/tree, run/attempt, command exit codes, nonempty native test counts and log digests. "
            + "Candidate identity is revalidated before and after each command. Pending, skipped, cancelled and missing artifacts are not passes.\n\n"
            + "## 7. Retained detailed design\n\n"
            + "Active V3 contracts and development workflow: [V3 development guide](../../../docs/modules/context.compiler/V3_DEVELOPMENT.md).\n\n"
            + "The complete previous technical guide, implementation map, dossier and product-path design are preserved byte-for-byte below. "
            + "Their earlier completion statements are historical, not current acceptance evidence. Algorithms, proof objects, byte identities, capacity requirements, threat controls, migration targets and test design remain available in full.\n\n"
            + bullets(references)
            + "\n\n## 8. Consumer execution trace\n\n" + consumer_table(state)
            + "\n\nThese are reviewed source anchors, not compiler reachability or execution evidence. "
            + "The exact-candidate receipt records each required native name and command/log identity; "
            + "native fixture passes never qualify authenticated ingress, independent provider truth or a target host.\n"
            + "\n## 9. Change discipline\n\n"
            + "Edit `CURRENT_STATE.json`, run `python3 scripts/generate_context_compiler_module_docs.py --write`, and commit all five projections together. "
            + "CI uses `--check` only. Source-navigation checks are deliberately not described as compilation or independent security acceptance. "
            + "No candidate workflow may rewrite Rust source or push remediation commits.\n"
        )
    # Preserve the complete previous map/manifest contracts and inventories;
    # replace their current-state assertions rather than dropping their fields.
    rationale = {
        "coreImplementation": "Core verified V2 source exists; native execution is a separate gate.",
        "productComposition": "The current source uses provisional admission and the V2 exact-body path. Dormant V3 files are not active product composition.",
        "v2ProviderClosure": "Typed slot and observer safety guards are present. Independent authority, immutable tokenizer qualification, final revocation and crash reconciliation remain open.",
        "currentHeadQualification": "No immutable passing receipt for the final source/merge candidate is asserted by source generation.",
    }
    rationale.update(state.get("statusRationale", {}))
    baseline = root / "docs/modules/context.compiler/design-baseline"
    for kind, name in (("map", "IMPLEMENTATION_MAP.json"), ("manifest", "MODULE_MANIFEST.json")):
        value = json.loads((baseline / name).read_text(encoding="utf-8"), object_pairs_hook=unique_object)
        value.update({
            "generated": {"state": str(STATE_PATH), "stateSha256": digest,
                          "generator": "scripts/generate_context_compiler_module_docs.py",
                          "reviewedBaseSha": state["reviewedBaseSha"],
                          "integrationBranch": state["integrationBranch"]},
            "reviewedBaseSha": state["reviewedBaseSha"], "integrationBranch": state["integrationBranch"],
            "runtimeSourceAnchor": state["runtimeSourceAnchor"], "runtimeSourceTree": state["runtimeSourceTree"],
            "status": state["status"], "statusRationale": rationale, "maturity": state["maturity"],
            "sourceBindings": state["sourceBindings"], "dormantSource": state["dormantSource"],
            "runtimeSourceFiles": state.get("runtimeSourceFiles", []),
            "consumerExecution": state.get("consumerExecution", []),
            "designReferences": state["designReferences"], "knownOpenItems": state["knownOpenItems"],
            "invariantInterpretation": "Retained invariants are required contracts; status and knownOpenItems identify implementation and execution gaps.",
        })
        value["sourceRoots"] = list(dict.fromkeys(value["sourceRoots"] + [binding["path"] for binding in state["sourceBindings"]] + [entry["path"] for entry in state.get("runtimeSourceFiles", [])]))
        value["qualification"].update(state["qualification"])
        value["qualification"]["receiptArtifact"] = "context-compiler-<source-sha>-<lane>-<run-id>-<attempt>"
        value["qualification"]["runner"] = "scripts/context_compiler_execution.py"
        value["qualification"]["commands"] = [command.replace("cargo test", "just test") for command in value["qualification"]["commands"]]
        if kind == "map":
            value["productComposition"]["state"] = "partial"
            value["productComposition"]["singlePhysicalPath"] = "Registry/compiler V3 uses the existing Agentd exact-body owner; authenticated ingress and external security-capability consumption remain not composed. No alternate owner is activated."
            value = repository_map(value, state)
        else:
            value["artifacts"]["currentProductPath"] = str(OUTPUTS["product"])
        documents[OUTPUTS[kind]] = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    return documents


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        state = load_state()
        validate_bindings(state)
        failed = False
        for path, expected in render_all(state).items():
            target = ROOT / path
            if args.write:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(expected, encoding="utf-8")
            elif not target.is_file() or target.read_text(encoding="utf-8") != expected:
                print(f"out of date: {path}")
                failed = True
        return int(failed)
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"context state verification failed: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
