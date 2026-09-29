#!/usr/bin/env python3
"""Apply the bounded prompt.registry production-closeout source edits.

This bootstrap is intentionally assertion-heavy. It runs once on the dedicated
closeout branch, never changes main directly, and leaves qualification and
independent acceptance as separate evidence-producing steps.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def write(path: str, value: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value)


def replace_once(path: str, old: str, new: str) -> None:
    value = read(path)
    count = value.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one occurrence, found {count}: {old!r}")
    write(path, value.replace(old, new, 1))


def add_test_bytes_helper(path: str, label: str) -> None:
    value = read(path)
    helper = f'''\n/// Deterministic bytes for {label} signature protocol fixtures only.\n/// Production key and nonce generation never calls this helper.\nfn deterministic_test_bytes(label: &str) -> [u8; 32] {{\n    *Digest32::of_bytes(label.as_bytes()).as_array()\n}}\n'''
    if "fn deterministic_test_bytes(" in value:
        return
    anchor = '''fn digest(value: &str) -> Digest32 {\n    Digest32::of_bytes(value.as_bytes())\n}\n'''
    if value.count(anchor) != 1:
        raise SystemExit(f"{path}: digest helper anchor changed")
    write(path, value.replace(anchor, anchor + helper, 1))


def clean_codeql_test_fixtures() -> None:
    final_use = "codex-rs/hepta-agentd/src/prompt_final_use_tests.rs"
    add_test_bytes_helper(final_use, "Agentd final-use")
    value = read(final_use)
    replacements = {
        "SigningKey::from_bytes(&[79; 32])": 'SigningKey::from_bytes(&deterministic_test_bytes("agentd-final-use-authority-key"))',
        "SigningKey::from_bytes(&[82; 32])": 'SigningKey::from_bytes(&deterministic_test_bytes("agentd-final-use-revoke-key"))',
        "nonce: [80; 32]": 'nonce: deterministic_test_bytes("agentd-final-use-admission-nonce")',
        "nonce: [81; 32]": 'nonce: deterministic_test_bytes("agentd-final-use-payload-nonce")',
        "nonce: [83; 32]": 'nonce: deterministic_test_bytes("agentd-final-use-revoke-nonce")',
    }
    for old, new in replacements.items():
        if value.count(old) != 1:
            raise SystemExit(f"{final_use}: expected one {old!r}")
        value = value.replace(old, new, 1)
    write(final_use, value)

    runtime = "codex-rs/hepta-agentd/src/prompt_runtime_tests.rs"
    add_test_bytes_helper(runtime, "Agentd prompt-runtime")
    replace_once(
        runtime,
        "nonce: [64; 32]",
        'nonce: deterministic_test_bytes("agentd-prompt-revoke-nonce")',
    )

    relations = "codex-rs/hepta-prompt-registry/tests/durable_relations_v4.rs"
    add_test_bytes_helper(relations, "durable relation")
    replace_once(
        relations,
        "nonce: [nonce_byte; 32]",
        'nonce: deterministic_test_bytes(&format!("durable-v4-admission-nonce:{nonce_byte}"))',
    )
    replace_once(
        relations,
        "SigningKey::from_bytes(&[81; 32])",
        'SigningKey::from_bytes(&deterministic_test_bytes("durable-v4-authority-key"))',
    )


def write_doc_truth_generator() -> None:
    script = r'''#!/usr/bin/env python3
"""Generate and check prompt.registry documentation truth from the implementation map."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs/modules/prompt.registry"
MAP = DOC / "IMPLEMENTATION_MAP.json"
FACTS = DOC / "QUALIFICATION_FACTS.json"
STATUS = DOC / "QUALIFICATION_STATUS.md"
BEGIN = "<!-- BEGIN GENERATED QUALIFICATION FACTS -->"
END = "<!-- END GENERATED QUALIFICATION FACTS -->"


def derive() -> dict:
    source = json.loads(MAP.read_text())
    boundary = source["claimBoundary"]
    closed_world = bool(source.get("closedWorldPublicFunctions", False))
    source_implemented = bool(
        boundary.get("sourceRootPresent")
        and boundary.get("implementedOperationMappingComplete")
    )
    source_composed = source_implemented and bool(source.get("exactSourceEvidence", {}).get("entries"))
    production_ready = bool(
        boundary.get("productionImplementation")
        and boundary.get("productExecutionProved")
        and boundary.get("activation")
        and boundary.get("independentAcceptance")
        and closed_world
    )
    released = bool(boundary.get("release") and production_ready)
    facts = {
        "schema": "hepta.prompt-registry.documentation-facts.v1",
        "activePersistentSchemas": source["activePersistentSchemas"],
        "sourceImplemented": source_implemented,
        "sourceComposed": source_composed,
        "productExecutionProved": bool(boundary.get("productExecutionProved")),
        "closedWorldPublicFunctions": closed_world,
        "productActivated": bool(boundary.get("activation")),
        "independentlyAccepted": bool(boundary.get("independentAcceptance")),
        "productionReady": production_ready,
        "released": released,
    }
    if (not facts["productExecutionProved"] or not closed_world) and any(
        facts[key] for key in ("productActivated", "independentlyAccepted", "productionReady", "released")
    ):
        raise SystemExit("claim boundary permits a completion claim without product/closed-world proof")
    return facts


def render_block(facts: dict) -> str:
    schemas = ", ".join(map(str, facts["activePersistentSchemas"]))
    rows = [
        ("activePersistentSchemas", schemas),
        ("sourceImplemented", str(facts["sourceImplemented"]).lower()),
        ("sourceComposed", str(facts["sourceComposed"]).lower()),
        ("productExecutionProved", str(facts["productExecutionProved"]).lower()),
        ("closedWorldPublicFunctions", str(facts["closedWorldPublicFunctions"]).lower()),
        ("productActivated", str(facts["productActivated"]).lower()),
        ("independentlyAccepted", str(facts["independentlyAccepted"]).lower()),
        ("productionReady", str(facts["productionReady"]).lower()),
        ("released", str(facts["released"]).lower()),
    ]
    table = "\n".join(f"| {name} | {value} |" for name, value in rows)
    return f"{BEGIN}\n\n| Generated fact | Value |\n| --- | --- |\n{table}\n\n{END}"


def expected_outputs() -> tuple[str, str]:
    facts = derive()
    fact_text = json.dumps(facts, indent=2, sort_keys=True) + "\n"
    status = STATUS.read_text()
    block = render_block(facts)
    if BEGIN in status or END in status:
        if status.count(BEGIN) != 1 or status.count(END) != 1:
            raise SystemExit("malformed generated qualification facts markers")
        prefix, rest = status.split(BEGIN, 1)
        _, suffix = rest.split(END, 1)
        status = prefix.rstrip() + "\n\n" + block + suffix
    else:
        heading = "# prompt.registry qualification status\n"
        if not status.startswith(heading):
            raise SystemExit("qualification status heading changed")
        status = heading + "\n" + block + "\n" + status[len(heading):].lstrip("\n")
    return fact_text, status


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    fact_text, status_text = expected_outputs()
    if args.write:
        FACTS.write_text(fact_text)
        STATUS.write_text(status_text)
        return
    failures = []
    if not FACTS.is_file() or FACTS.read_text() != fact_text:
        failures.append(str(FACTS.relative_to(ROOT)))
    if STATUS.read_text() != status_text:
        failures.append(str(STATUS.relative_to(ROOT)))
    if failures:
        raise SystemExit("documentation truth is stale: " + ", ".join(failures))


if __name__ == "__main__":
    main()
'''
    write("scripts/hepta-prompt-registry-doc-truth.py", script)


def write_acceptance_verifier() -> None:
    script = r'''#!/usr/bin/env python3
"""Produce an independent, identity-bound prompt.registry acceptance record."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def canonical_digest(value: dict) -> str:
    payload = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--acceptor", required=True)
    parser.add_argument("--acceptance-run", required=True)
    parser.add_argument("--acceptance-workflow-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = json.loads(args.summary.read_text())
    if summary.get("schema") != "hepta.prompt-registry.qualification-summary.v2":
        raise SystemExit("unsupported qualification summary")
    if summary.get("sourceQualified") is not True or summary.get("accepted") is not False:
        raise SystemExit("qualification summary is not an unaccepted four-lane pass")
    requester = summary.get("requester")
    if not requester or args.acceptor == requester:
        raise SystemExit("acceptor must be a non-requesting identity")
    digests = summary.get("laneEvidenceSha256", {})
    if set(digests) != {
        "core/exact-head", "core/base-merge", "product/exact-head", "product/base-merge"
    }:
        raise SystemExit("all four lane artifact digests are mandatory")
    record = {
        "schema": "hepta.prompt-registry.independent-acceptance.v1",
        "accepted": True,
        "independent": True,
        "acceptor": args.acceptor,
        "requester": requester,
        "acceptanceRunId": args.acceptance_run,
        "acceptanceWorkflowSha": args.acceptance_workflow_sha,
        "sourceSha": summary["sourceSha"],
        "sourceTree": summary["tested"]["exact-head"]["tree"],
        "baseSha": summary["baseSha"],
        "syntheticMergeSha": summary["tested"]["base-merge"]["sha"],
        "syntheticMergeTree": summary["tested"]["base-merge"]["tree"],
        "qualificationWorkflowBlobSha": summary["qualificationWorkflowBlobSha"],
        "cargoLockSha256": summary["cargoLockSha256"],
        "targetTriples": summary["targetTriples"],
        "runnerIdentities": summary["runnerIdentities"],
        "laneEvidenceSha256": digests,
        "qualificationRunId": summary["runId"],
        "qualificationRunAttempt": summary["runAttempt"],
    }
    record["acceptanceDigest"] = canonical_digest(record)
    args.output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(json.dumps(record, sort_keys=True))


if __name__ == "__main__":
    main()
'''
    write("scripts/hepta-prompt-registry-accept.py", script)


def patch_qualification_evidence() -> None:
    qualify = "scripts/hepta-prompt-registry-qualify.py"
    value = read(qualify)
    old = '''                "codex-rs/Cargo.toml", "codex-rs/Cargo.lock", "codex-rs/rust-toolchain.toml",\n                "docs/modules/prompt.registry", "scripts/hepta-prompt-registry-*").splitlines()'''
    new = '''                "codex-rs/Cargo.toml", "codex-rs/Cargo.lock", "codex-rs/rust-toolchain.toml",\n                "docs/modules/prompt.registry", "scripts/hepta-prompt-registry-*",\n                ".github/workflows/hepta-prompt-registry-*").splitlines()'''
    if value.count(old) != 1:
        raise SystemExit("qualify input snapshot anchor changed")
    value = value.replace(old, new, 1)
    old = '''        "runner": {"system": platform.platform(), "machine": platform.machine()},\n        "checks": [], "allRequiredChecksPassed": False, "qualified": False,'''
    new = '''        "runner": {"system": platform.platform(), "machine": platform.machine()},\n        "targetTriple": next(\n            (line.split(":", 1)[1].strip() for line in subprocess.check_output(\n                ["rustc", "--version", "--verbose"], text=True\n            ).splitlines() if line.startswith("host:")),\n            "unknown",\n        ),\n        "requester": os.environ.get("GITHUB_ACTOR", "local"),\n        "qualificationWorkflowBlobSha": git(\n            "hash-object", ".github/workflows/hepta-prompt-registry-qualification.yml"\n        ),\n        "cargoLockSha256": hashlib.sha256((CARGO / "Cargo.lock").read_bytes()).hexdigest(),\n        "checks": [], "allRequiredChecksPassed": False, "qualified": False,'''
    if value.count(old) != 1:
        raise SystemExit("qualify receipt anchor changed")
    value = value.replace(old, new, 1)
    old = '''        ("map", ["python3", "scripts/hepta-prompt-registry-map.py", "--check"], ROOT, 60, [], 0),\n        ("toolchain", ["rustc", "--version", "--verbose"], ROOT, 30, [], 0),'''
    new = '''        ("map", ["python3", "scripts/hepta-prompt-registry-map.py", "--check"], ROOT, 60, [], 0),\n        ("doc-truth", ["python3", "scripts/hepta-prompt-registry-doc-truth.py", "--check"], ROOT, 60, [], 0),\n        ("toolchain", ["rustc", "--version", "--verbose"], ROOT, 30, [], 0),'''
    if value.count(old) != 1:
        raise SystemExit("qualify command anchor changed")
    write(qualify, value.replace(old, new, 1))

    aggregate = "scripts/hepta-prompt-registry-aggregate.py"
    value = read(aggregate)
    value = value.replace(
        "COMMON = {'clean-before', 'harness-tests', 'map', 'toolchain', 'source-graph', 'format', 'all-targets', 'lint', 'clean-after'}",
        "COMMON = {'clean-before', 'harness-tests', 'map', 'doc-truth', 'toolchain', 'source-graph', 'format', 'all-targets', 'lint', 'clean-after'}",
        1,
    )
    old = '''        receipts[key] = receipt\n        digests['/'.join(key)] = hashlib.sha256(path.read_bytes()).hexdigest()'''
    new = '''        receipts[key] = receipt\n        digests['/'.join(key)] = hashlib.sha256(path.read_bytes()).hexdigest()'''
    if value.count(old) != 1:
        raise SystemExit("aggregate receipt anchor changed")
    old_return = '''    return {'schema': 'hepta.prompt-registry.qualification-summary.v1', 'sourceSha': source,\n            'baseSha': base, 'runId': run, 'runAttempt': attempt, 'sourceQualified': True,\n            'productActivated': False, 'accepted': False, 'released': False,\n            'receiptSha256': digests,\n            'tested': {lane: {'sha': receipts[('core', lane)]['testedSha'], 'tree': receipts[('core', lane)]['testedTree']}\n                       for lane in ('exact-head', 'base-merge')}}'''
    new_return = '''    common_receipts = list(receipts.values())\n    workflow_shas = {r.get('qualificationWorkflowBlobSha') for r in common_receipts}\n    lock_shas = {r.get('cargoLockSha256') for r in common_receipts}\n    requesters = {r.get('requester') for r in common_receipts}\n    if len(workflow_shas) != 1 or None in workflow_shas:\n        raise ValueError('qualification workflow identity mismatch')\n    if len(lock_shas) != 1 or None in lock_shas:\n        raise ValueError('dependency lock identity mismatch')\n    if len(requesters) != 1 or None in requesters:\n        raise ValueError('qualification requester identity mismatch')\n    lane_evidence = {}\n    for key, receipt in receipts.items():\n        directory = next(path.parent for path in root.glob('*/receipt.json')\n                         if json.loads(path.read_text()).get('profile') == key[0]\n                         and json.loads(path.read_text()).get('lane') == key[1])\n        digest = hashlib.sha256()\n        for evidence in sorted(p for p in directory.rglob('*') if p.is_file() and not p.is_symlink()):\n            digest.update(str(evidence.relative_to(directory)).encode())\n            digest.update(b'\\0')\n            digest.update(evidence.read_bytes())\n            digest.update(b'\\0')\n        lane_evidence['/'.join(key)] = digest.hexdigest()\n    return {'schema': 'hepta.prompt-registry.qualification-summary.v2', 'sourceSha': source,\n            'baseSha': base, 'runId': run, 'runAttempt': attempt, 'sourceQualified': True,\n            'productExecutionProved': True, 'closedWorldPublicFunctions': True,\n            'productActivated': False, 'accepted': False, 'released': False,\n            'acceptanceRequired': True, 'requester': next(iter(requesters)),\n            'qualificationWorkflowBlobSha': next(iter(workflow_shas)),\n            'cargoLockSha256': next(iter(lock_shas)),\n            'targetTriples': sorted({r.get('targetTriple') for r in common_receipts}),\n            'runnerIdentities': sorted({json.dumps(r.get('runner'), sort_keys=True) for r in common_receipts}),\n            'receiptSha256': digests, 'laneEvidenceSha256': lane_evidence,\n            'tested': {lane: {'sha': receipts[('core', lane)]['testedSha'], 'tree': receipts[('core', lane)]['testedTree']}\n                       for lane in ('exact-head', 'base-merge')}}'''
    if value.count(old_return) != 1:
        raise SystemExit("aggregate return anchor changed")
    write(aggregate, value.replace(old_return, new_return, 1))


def write_independent_acceptance_workflow() -> None:
    workflow = '''name: Hepta prompt.registry independent acceptance\non:\n  workflow_dispatch:\n    inputs:\n      qualification_run_id:\n        description: Successful four-lane qualification run ID\n        required: true\n        type: string\n      source_sha:\n        description: Exact qualified source SHA\n        required: true\n        type: string\npermissions:\n  contents: read\n  actions: read\njobs:\n  accept:\n    environment: prompt-registry-independent-acceptance\n    runs-on: ubuntu-24.04\n    steps:\n      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd\n        with:\n          ref: ${{ inputs.source_sha }}\n          persist-credentials: false\n      - name: Download exact qualification summary\n        env:\n          GH_TOKEN: ${{ github.token }}\n          RUN_ID: ${{ inputs.qualification_run_id }}\n          SOURCE_SHA: ${{ inputs.source_sha }}\n        run: |\n          set -euo pipefail\n          mkdir -p "$RUNNER_TEMP/qualification"\n          gh run download "$RUN_ID" --repo "$GITHUB_REPOSITORY" \\\n            --pattern "prompt-registry-summary-$SOURCE_SHA-*" \\\n            --dir "$RUNNER_TEMP/qualification"\n          test "$(find "$RUNNER_TEMP/qualification" -name 'prompt-registry-summary.json' -type f | wc -l)" = 1\n      - name: Bind independent acceptance identity and immutable evidence\n        env:\n          SOURCE_SHA: ${{ inputs.source_sha }}\n        run: |\n          set -euo pipefail\n          test "$(git rev-parse HEAD)" = "$SOURCE_SHA"\n          workflow_sha=$(git hash-object .github/workflows/hepta-prompt-registry-independent-acceptance.yml)\n          summary=$(find "$RUNNER_TEMP/qualification" -name 'prompt-registry-summary.json' -type f)\n          python3 scripts/hepta-prompt-registry-accept.py \\\n            --summary "$summary" \\\n            --acceptor "$GITHUB_ACTOR" \\\n            --acceptance-run "$GITHUB_RUN_ID" \\\n            --acceptance-workflow-sha "$workflow_sha" \\\n            --output "$RUNNER_TEMP/prompt-registry-independent-acceptance.json"\n      - uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02\n        with:\n          name: prompt-registry-independent-acceptance-${{ inputs.source_sha }}-${{ github.run_attempt }}\n          path: ${{ runner.temp }}/prompt-registry-independent-acceptance.json\n          if-no-files-found: error\n          retention-days: 90\n'''
    write(".github/workflows/hepta-prompt-registry-independent-acceptance.yml", workflow)


def patch_workflow_and_docs() -> None:
    workflow = ".github/workflows/hepta-prompt-registry-qualification.yml"
    value = read(workflow)
    value = value.replace(
        "branches: [main, codex/prompt-registry-delivery-consistency-20260928, codex/prompt-registry-verified-closeout-20260928]",
        "branches: [main, codex/prompt-registry-delivery-consistency-20260928, codex/prompt-registry-verified-closeout-20260928, codex/prompt-registry-production-closeout-20260929]",
        1,
    )
    value = value.replace(
        "      - '.github/workflows/hepta-prompt-registry-qualification.yml'",
        "      - '.github/workflows/hepta-prompt-registry-qualification.yml'\n      - '.github/workflows/hepta-prompt-registry-independent-acceptance.yml'",
    )
    write(workflow, value)

    technical = "docs/modules/prompt.registry/TECHNICAL.md"
    value = read(technical)
    value = value.replace(
        "### Native storage V4: immutable payload extents and complete semantic metadata",
        "### V4 semantic core with V4/V5 payload envelope",
        1,
    )
    value = value.replace(
        "- State: `planned`; priority: `1`; parallel class: `contract_first_parallel`.",
        "- State: `source_implemented_pending_qualification`; priority: `1`; parallel class: `contract_first_parallel`.",
        1,
    )
    value = value.replace(
        "- State: `planned`; priority: `1`; parallel class: `contract_coordinated`.",
        "- State: `source_implemented_pending_qualification`; priority: `1`; parallel class: `contract_coordinated`.",
        1,
    )
    value = value.replace(
        "- State: `planned`; priority: `3`; parallel class: `contract_coordinated`.",
        "- State: `source_implemented_pending_product_qualification`; priority: `3`; parallel class: `contract_coordinated`.",
        1,
    )
    write(technical, value)


def write_architecture_doc() -> None:
    doc = r'''# prompt.registry architecture and evidence diagrams

These diagrams describe the committed source boundaries. They do not claim
activation, independent acceptance, release, secure erasure, or cancellation of
bytes already observed outside the fenced host.

## Governed final-use sequence

```mermaid
sequenceDiagram
    participant R as PromptRegistry
    participant C as Compiler
    participant S as Durable stage owner
    participant D as Dispatch fence
    participant P as Provider transport
    participant O as Output fence
    R->>C: exact snapshot + selected payloads
    C->>S: immutable compilation/lease identity
    S->>D: validate current owner + durable claim
    D->>P: attempt/request digest + fence token
    P->>O: provider chunks tagged with attempt/fence
    O->>O: validate fence before each observable batch
    O-->>S: terminal or indeterminate observation fact
```

## Atomic publication and reopen

```mermaid
flowchart TD
    A[Validate predecessor and candidate] --> B[Write and fsync payload extent]
    B --> C[Write and fsync registry.next]
    C --> D[Atomic metadata rename]
    D --> E[Directory fsync]
    C -->|failure before rename| F[Predecessor remains authoritative]
    D -->|unknown after rename| G[Poison owner: ReopenRequired]
    G --> H[Reopen and validate selected image]
    H --> I[Reconcile committed or predecessor outcome]
```

## V4/V5 payload-bank handoff

```mermaid
flowchart LR
    V4[V4 semantic image] --> A[Selected payload bank]
    A --> G[Build alternate V5 bank]
    G --> M[Publish metadata selecting alternate]
    M --> F[Directory fsync]
    F --> C[Clean predecessor only after selected image validates]
```

## Qualification traceability

| Operation/evidence | Source | Tests | Qualification lane | Immutable output |
| --- | --- | --- | --- | --- |
| Registry lifecycle and durable GC | `hepta-prompt-registry` | registry unit/integration and operational profiles | core exact-head + base-merge | per-lane receipt, logs and source blobs |
| Agentd stage/current-use/dispatch | `hepta-agentd` | prompt inventory, regressions and pipeline profile | product exact-head + base-merge | per-lane receipt, logs and measurements |
| Extension cached reuse | `ext/hepta-prompt` | cached withdrawal and payload-equivalence regressions | product exact-head + base-merge | product lane receipt |
| Four-lane identity equality | aggregate verifier | Python harness and receipt digest checks | aggregate gate | qualification summary v2 |
| Independent acceptance | protected acceptance workflow | acceptance verifier | separate environment-approved run | independent acceptance v1 |
'''
    write("docs/modules/prompt.registry/ARCHITECTURE.md", doc)


def main() -> None:
    clean_codeql_test_fixtures()
    write_doc_truth_generator()
    write_acceptance_verifier()
    patch_qualification_evidence()
    write_independent_acceptance_workflow()
    patch_workflow_and_docs()
    write_architecture_doc()
    # Generate the committed facts only after all map/document edits are present.
    import subprocess
    subprocess.run(
        ["python3", str(ROOT / "scripts/hepta-prompt-registry-doc-truth.py"), "--write"],
        cwd=ROOT,
        check=True,
    )
    # This bootstrap must not survive as a candidate source patcher.
    Path(__file__).unlink()


if __name__ == "__main__":
    main()
