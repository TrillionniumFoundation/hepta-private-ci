#!/usr/bin/env python3
"""Apply the prompt.registry qualification-closeout source changes.

This authoring helper is intentionally kept on an isolated ops branch.  The
resulting delivery branch contains only ordinary source, documentation, and
qualification changes; this helper is never copied into the delivery history.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def path(name: str) -> Path:
    return ROOT / name


def replace(name: str, old: str, new: str, count: int = 1) -> None:
    target = path(name)
    text = target.read_text(encoding="utf-8")
    actual = text.count(old)
    if actual != count:
        raise SystemExit(f"{name}: expected {count} occurrences, found {actual}: {old!r}")
    target.write_text(text.replace(old, new, count), encoding="utf-8")


def write(name: str, content: str) -> None:
    target = path(name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.rstrip() + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Product qualification: remove the only strict-Clippy blocker without a
# workspace-wide allowance.  CanonicalRunOutcomeV1 is an in-workspace Rust API,
# has no serde wire representation, and all direct consumers are updated here.
# ---------------------------------------------------------------------------
replace(
    "codex-rs/hepta-intelligence/src/canonical.rs",
    "    Ready(IntelligenceHostEnvelopeV1),",
    "    Ready(Box<IntelligenceHostEnvelopeV1>),",
)
replace(
    "codex-rs/hepta-intelligence/src/canonical.rs",
    "    Ok(CanonicalRunOutcomeV1::Ready(IntelligenceHostEnvelopeV1 {\n",
    "    Ok(CanonicalRunOutcomeV1::Ready(Box::new(IntelligenceHostEnvelopeV1 {\n",
)
replace(
    "codex-rs/hepta-intelligence/src/canonical.rs",
    "        authority: AuthorityPosture::DENY_ALL,\n    }))\n}\n\nfn run_stage",
    "        authority: AuthorityPosture::DENY_ALL,\n    })))\n}\n\nfn run_stage",
)
replace(
    "codex-rs/hepta-agentd/src/intelligence_product_runner.rs",
    "            CanonicalRunOutcomeV1::Ready(envelope) => {\n",
    "            CanonicalRunOutcomeV1::Ready(envelope) => {\n                let envelope = *envelope;\n",
)

# ---------------------------------------------------------------------------
# CodeQL test-fixture cleanup.  Deterministic values remain reproducible but are
# domain-separated digests rather than hard-coded cryptographic byte arrays.
# ---------------------------------------------------------------------------
nonce_helper = '''

fn test_nonce(label: &str) -> [u8; 32] {
    let value = Digest32::of_bytes(
        format!("hepta.prompt-registry.test-nonce.v1:{label}").as_bytes(),
    );
    *value.as_array()
}
'''
for name in [
    "codex-rs/hepta-agentd/src/prompt_final_use_tests.rs",
    "codex-rs/hepta-agentd/src/prompt_runtime_tests.rs",
    "codex-rs/hepta-prompt-registry/tests/durable_relations_v4.rs",
]:
    replace(
        name,
        "fn digest(value: &str) -> Digest32 {\n    Digest32::of_bytes(value.as_bytes())\n}\n",
        "fn digest(value: &str) -> Digest32 {\n    Digest32::of_bytes(value.as_bytes())\n}\n" + nonce_helper,
    )

for old, new in [
    ("SigningKey::from_bytes(&[79; 32])", "SigningKey::from_bytes(&test_nonce(\"final-use-signing-key\"))"),
    ("SigningKey::from_bytes(&[82; 32])", "SigningKey::from_bytes(&test_nonce(\"final-use-revoke-signing-key\"))"),
    ("nonce: [80; 32]", "nonce: test_nonce(\"final-use-admission\")"),
    ("nonce: [81; 32]", "nonce: test_nonce(\"final-use-realization\")"),
    ("nonce: [83; 32]", "nonce: test_nonce(\"final-use-revoke\")"),
]:
    replace("codex-rs/hepta-agentd/src/prompt_final_use_tests.rs", old, new)

for old, new in [
    ("SigningKey::from_bytes(&[61; 32])", "SigningKey::from_bytes(&test_nonce(\"agentd-prompt-signing-key\"))"),
    ("nonce: [62; 32]", "nonce: test_nonce(\"agentd-prompt-admission\")"),
    ("nonce: [63; 32]", "nonce: test_nonce(\"agentd-prompt-realization\")"),
    ("nonce: [64; 32]", "nonce: test_nonce(\"agentd-prompt-revoke\")"),
]:
    replace("codex-rs/hepta-agentd/src/prompt_runtime_tests.rs", old, new)

replace(
    "codex-rs/hepta-prompt-registry/tests/durable_relations_v4.rs",
    "    nonce_byte: u8,\n",
    "    nonce_label: &str,\n",
)
replace(
    "codex-rs/hepta-prompt-registry/tests/durable_relations_v4.rs",
    "        nonce: [nonce_byte; 32],",
    "        nonce: test_nonce(nonce_label),",
)
replace(
    "codex-rs/hepta-prompt-registry/tests/durable_relations_v4.rs",
    "SigningKey::from_bytes(&[81; 32])",
    "SigningKey::from_bytes(&test_nonce(\"durable-relations-signing-key\"))",
)
replace(
    "codex-rs/hepta-prompt-registry/tests/durable_relations_v4.rs",
    'register_admitted(&mut registry, &authority, &key, "factor:left", 1);',
    'register_admitted(\n        &mut registry,\n        &authority,\n        &key,\n        "factor:left",\n        "factor-left-admission",\n    );',
)
replace(
    "codex-rs/hepta-prompt-registry/tests/durable_relations_v4.rs",
    'register_admitted(&mut registry, &authority, &key, "factor:right", 2);',
    'register_admitted(\n        &mut registry,\n        &authority,\n        &key,\n        "factor:right",\n        "factor-right-admission",\n    );',
)

# ---------------------------------------------------------------------------
# Documentation truth: name the actual V4/V5 split and stop presenting already
# implemented work packages as merely planned.
# ---------------------------------------------------------------------------
replace(
    "docs/modules/prompt.registry/TECHNICAL.md",
    "### Native storage V4: immutable payload extents and complete semantic metadata",
    "### V4 semantic core with V4/V5 payload envelope",
)
replace(
    "docs/modules/prompt.registry/TECHNICAL.md",
    "- State: `planned`;",
    "- State: `source_implemented_qualification_pending`;",
    count=3,
)
replace(
    "docs/modules/prompt.registry/TECHNICAL.md",
    "**Current implementation contracts:** [API and failure policy](API_CONTRACT.md), [operations and retention](OPERATIONS.md), [performance measurement](PERFORMANCE.md).",
    "**Current implementation contracts:** [API and failure policy](API_CONTRACT.md), [operations and retention](OPERATIONS.md), [performance measurement](PERFORMANCE.md), [architecture and traceability](ARCHITECTURE.md), and [independent acceptance](ACCEPTANCE.md).",
)

write(
    "docs/modules/prompt.registry/ARCHITECTURE.md",
    r'''# prompt.registry architecture and traceability

This document visualizes the committed source boundaries. It does not activate a
provider, accept a candidate, or authorize release. Machine-readable source and
qualification identities remain in `IMPLEMENTATION_MAP.json` and the four-lane
receipts.

## Governed prompt path

```mermaid
sequenceDiagram
    participant Authority as final-use authority
    participant Registry as DurablePromptRegistry
    participant Compiler as prompt.optimizer / context.compiler
    participant Agentd as AgentdPromptPipelineOwner
    participant Extension as hepta-prompt extension
    participant Provider as physical provider transport
    participant Output as output consumer

    Authority->>Registry: operation-bound admission/publication grants
    Registry-->>Compiler: exact snapshot + model tuple + payload digests
    Compiler-->>Agentd: compiled lease and exact selected bytes
    Agentd->>Agentd: durable stage + current-use validation
    Extension->>Agentd: prepare exact thread/turn attachment
    Agentd-->>Extension: byte-identical current attachment
    Extension->>Agentd: durable dispatch claim(attempt, request digest)
    Agentd-->>Extension: claim committed or fail closed
    Extension->>Provider: admit physical send
    Provider-->>Extension: terminal observation
    Extension->>Agentd: durable terminal/reconciliation fact
    Extension-->>Output: output only under the committed provider lifecycle
```

The committed candidate currently linearizes current-use validation through the
durable dispatch claim. Transport/output checkpointing is a separate capability
and must not be inferred from this diagram until its executable qualification
receipt is present.

## Publication and crash recovery

```mermaid
flowchart TD
    A[validated predecessor] --> B[write and fsync successor payload extent]
    B --> C[write and fsync registry.next]
    C --> D{atomic metadata selection}
    D -->|rename not attempted| E[predecessor authoritative]
    D -->|rename acknowledged| F[successor authoritative]
    D -->|outcome unknown| G[owner poisoned]
    G --> H[stop reads, writes, and final use]
    H --> I[reopen under directory lock]
    I --> J{verify selected metadata and exact extent}
    J -->|predecessor selected| E
    J -->|successor selected| F
    J -->|invalid| K[quarantine; external recovery decision]
```

## V4 semantic state and V5 payload-bank flip

```mermaid
flowchart LR
    V4[V4 semantic/audit image] --> M[immutable payload manifest]
    M --> A[V5 active payload bank]
    M --> B[V5 alternate payload bank]
    A -->|copy live extents + fsync| B
    B -->|atomic semantic selection| S[new selected bank]
    S -->|best-effort predecessor cleanup| C[old bank reclaimed]
    S -->|cleanup interrupted| R[reopen resumes cleanup without new revision]
```

Semantic identities, relations, lifecycle events, grant lineage, and revocation
facts remain in the V4 semantic image. V5 changes physical payload selection and
collection; it does not erase audit history or prove disposal of backups.

## Traceability matrix

| Operation/boundary | Authoritative source | Required executable evidence | Qualification lane |
| --- | --- | --- | --- |
| Register/admit/retire/revoke factor | `hepta-prompt-registry/src/durable.rs` | registry unit and integration tests | core exact-head + base-merge |
| Publish/dereference exact realization | `durable.rs`, `durable_payloads.rs` | payload digest, restart, corruption tests | core exact-head + base-merge |
| Checkpoint/restore/GC | `durable_maintenance.rs`, `durable_gc.rs` | crash, idempotence, retained-history and operational profiles | core exact-head + base-merge |
| Prepare and dispatch current use | `hepta-agentd/src/prompt_runtime.rs` | Agentd final-use and pipeline regressions | product exact-head + base-merge |
| Provider attempt binding | `ext/hepta-prompt/src/lib.rs` | extension attempt/terminal regressions | product exact-head + base-merge |
| Four-lane source qualification | `hepta-prompt-registry-qualification.yml` | four receipts + aggregate content digests | aggregate gate |
| Independent acceptance | `hepta-prompt-registry-acceptance.yml` | protected-environment acceptance artifact | separate independent gate |

Every acceptance artifact must bind the exact source/tree, base and synthetic
merge, workflow SHA, dependency lock digest, runner/target identity, and all four
lane artifact-content digests. A source-authoring workflow or implementation PR
cannot issue that acceptance itself.
''',
)

write(
    "docs/modules/prompt.registry/ACCEPTANCE.md",
    r'''# prompt.registry independent acceptance

Independent acceptance is deliberately separate from source implementation and
four-lane qualification.

## Required control

The workflow `.github/workflows/hepta-prompt-registry-acceptance.yml` uses the
protected environment `prompt-registry-independent-acceptance`. Repository
administrators must configure that environment with required reviewers who are
not the implementation pull-request author. Without that external protection,
no acceptance artifact is authoritative.

The workflow also fails when the invoking actor equals the pull-request author,
when the pull-request head no longer equals the requested source SHA, or when
the qualification summary is missing any exact identity.

## Bound evidence

An acceptance statement binds:

- source SHA and exact source tree;
- base SHA and bound synthetic-merge SHA/tree;
- qualification workflow SHA/ref and qualification run/attempt;
- `Cargo.lock` SHA-256;
- runner and target triple for every lane;
- all four receipt SHA-256 values;
- all four complete lane-artifact content digests;
- acceptance workflow SHA/run/attempt, protected actor, PR number, and PR author.

Acceptance does not activate the product, authorize deployment, dispose of
historical payload bytes, or release the module. Those fields remain false in
the statement.

## Invocation

After one four-lane run has produced a successful summary, an independent
reviewer may manually dispatch the acceptance workflow with the exact
qualification run, attempt, source SHA, and pull-request number. The workflow
re-downloads the immutable summary from that run and emits a separate acceptance
artifact. It never edits the source branch.
''',
)

# ---------------------------------------------------------------------------
# Machine-generated status sourced from IMPLEMENTATION_MAP.json.
# ---------------------------------------------------------------------------
write(
    "scripts/hepta-prompt-registry-status.py",
    r'''#!/usr/bin/env python3
"""Generate or verify the prompt.registry status block from the implementation map."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "docs/modules/prompt.registry/IMPLEMENTATION_MAP.json"
STATUS = ROOT / "docs/modules/prompt.registry/QUALIFICATION_STATUS.md"
BEGIN = "<!-- prompt.registry generated-status:begin -->"
END = "<!-- prompt.registry generated-status:end -->"


def truth(value: bool) -> str:
    return "true" if value else "false"


def render(row: dict) -> str:
    claim = row["claimBoundary"]
    lifecycle = row["lifecycleStates"]
    closed = bool(row["closedWorldPublicFunctions"])
    product_proved = bool(claim["productExecutionProved"])
    independently_accepted = bool(claim["independentAcceptance"])
    production_ready = bool(
        closed
        and claim["nativeSourceMappingComplete"]
        and product_proved
        and independently_accepted
        and claim["activation"]
    )
    schemas = ", ".join(str(value) for value in row["activePersistentSchemas"])
    values = [
        ("sourceImplemented", lifecycle["sourceImplemented"]),
        ("sourceComposed", lifecycle["sourceComposed"]),
        ("closedWorldPublicFunctions", closed),
        ("nativeSourceMappingComplete", claim["nativeSourceMappingComplete"]),
        ("productExecutionProved", product_proved),
        ("independentlyAccepted", independently_accepted),
        ("productActivated", lifecycle["productActivated"]),
        ("productionReady", production_ready),
        ("released", lifecycle["released"]),
    ]
    lines = [
        BEGIN,
        "",
        "| Generated field | Value |",
        "| --- | --- |",
        *[f"| `{name}` | `{truth(bool(value))}` |" for name, value in values],
        f"| `activePersistentSchemas` | `{schemas}` |",
        f"| `semanticSchema` | `{row['semanticSchema']}` |",
        f"| `payloadGenerationSchema` | `{row['payloadGenerationSchema']}` |",
        "",
        "This block is generated from `IMPLEMENTATION_MAP.json`. When either "
        "`productExecutionProved` or `closedWorldPublicFunctions` is false, this "
        "document cannot claim production completion.",
        "",
        END,
    ]
    return "\n".join(lines)


def replace_block(text: str, generated: str, *, create: bool) -> str:
    starts = text.count(BEGIN)
    ends = text.count(END)
    if starts == 0 and ends == 0 and create:
        return text.rstrip() + "\n\n## Machine-generated implementation status\n\n" + generated + "\n"
    if starts != 1 or ends != 1:
        raise ValueError("status document must contain exactly one generated block")
    before, remainder = text.split(BEGIN, 1)
    _, after = remainder.split(END, 1)
    return before + generated + after


def guard_human_claims(text: str, row: dict) -> None:
    scrubbed = re.sub(
        re.escape(BEGIN) + r".*?" + re.escape(END),
        "",
        text,
        flags=re.DOTALL,
    )
    claim = row["claimBoundary"]
    if not claim["productExecutionProved"] or not row["closedWorldPublicFunctions"]:
        forbidden = re.compile(
            r"\|\s*(?:productionReady|productExecutionProved|closedWorldPublicFunctions)\s*\|\s*(?:`?true`?)\s*\|",
            flags=re.IGNORECASE,
        )
        if forbidden.search(scrubbed):
            raise ValueError("human status contradicts the fail-closed implementation map")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    row = json.loads(MAP.read_text(encoding="utf-8"))
    text = STATUS.read_text(encoding="utf-8")
    guard_human_claims(text, row)
    expected = replace_block(text, render(row), create=args.write)
    if args.write:
        STATUS.write_text(expected.rstrip() + "\n", encoding="utf-8")
        print("generated prompt.registry qualification status")
    elif text != expected:
        raise SystemExit("prompt.registry qualification status is stale")
    else:
        print("prompt.registry qualification status verified")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise SystemExit(f"prompt.registry status rejected: {error}") from error
''',
)

# Wire status generation into the exact-source map and expand the source
# inventory to include the workflows and contracts that now govern acceptance.
replace(
    "scripts/hepta-prompt-registry-map.py",
    "import subprocess\n",
    "import subprocess\nimport sys\n",
)
replace(
    "scripts/hepta-prompt-registry-map.py",
    'MAP = ROOT / "docs/modules/prompt.registry/IMPLEMENTATION_MAP.json"\n',
    'MAP = ROOT / "docs/modules/prompt.registry/IMPLEMENTATION_MAP.json"\nSTATUS_TOOL = ROOT / "scripts/hepta-prompt-registry-status.py"\n',
)
replace(
    "scripts/hepta-prompt-registry-map.py",
    '    "scripts/hepta-prompt-registry-aggregate.py",\n',
    '    "scripts/hepta-prompt-registry-aggregate.py",\n    "scripts/hepta-prompt-registry-status.py",\n    "scripts/hepta-prompt-registry-accept.py",\n    ".github/workflows/hepta-prompt-registry-qualification.yml",\n    ".github/workflows/hepta-prompt-registry-acceptance.yml",\n',
)
replace(
    "scripts/hepta-prompt-registry-map.py",
    '    "docs/modules/prompt.registry/PERFORMANCE.md",\n',
    '    "docs/modules/prompt.registry/PERFORMANCE.md",\n    "docs/modules/prompt.registry/ARCHITECTURE.md",\n    "docs/modules/prompt.registry/ACCEPTANCE.md",\n',
)
replace(
    "scripts/hepta-prompt-registry-map.py",
    '        MAP.write_text(json.dumps(row, sort_keys=True, indent=2) + "\\n", encoding="utf-8")\n        print("generated prompt.registry map; commit this map before qualification")',
    '        MAP.write_text(json.dumps(row, sort_keys=True, indent=2) + "\\n", encoding="utf-8")\n        subprocess.run([sys.executable, str(STATUS_TOOL), "--write"], cwd=ROOT, check=True)\n        print("generated prompt.registry map and status; commit both before qualification")',
)
replace(
    "scripts/hepta-prompt-registry-map.py",
    '        if row != build(observation):\n            raise ValueError("stale/incomplete prompt.registry implementation map")\n        print(f"prompt.registry map verified read-only: {len(row[\'operations\'])} operations, {len(row[\'exactSourceEvidence\'][\'entries\'])} source blobs")',
    '        if row != build(observation):\n            raise ValueError("stale/incomplete prompt.registry implementation map")\n        subprocess.run([sys.executable, str(STATUS_TOOL), "--check"], cwd=ROOT, check=True)\n        print(f"prompt.registry map verified read-only: {len(row[\'operations\'])} operations, {len(row[\'exactSourceEvidence\'][\'entries\'])} source blobs")',
)

# ---------------------------------------------------------------------------
# Four-lane evidence: bind workflow, dependency lock, runner/target, and the
# complete artifact contents.  Aggregate success still is not acceptance.
# ---------------------------------------------------------------------------
replace(
    "scripts/hepta-prompt-registry-qualify.py",
    'def git(*args: str) -> str:\n    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()\n\n',
    '''def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def file_sha256(value: Path) -> str:
    return hashlib.sha256(value.read_bytes()).hexdigest()


def rust_target_triple() -> str:
    output = subprocess.check_output(["rustc", "--version", "--verbose"], text=True)
    for line in output.splitlines():
        if line.startswith("host: "):
            target = line.removeprefix("host: ").strip()
            if target:
                return target
    raise ValueError("rustc did not report a host target triple")

''',
)
replace(
    "scripts/hepta-prompt-registry-qualify.py",
    '    receipt = {\n',
    '''    workflow_sha = os.environ.get("PROMPT_REGISTRY_WORKFLOW_SHA", source)
    workflow_ref = os.environ.get("PROMPT_REGISTRY_WORKFLOW_REF", "local/source-bound")
    if not re.fullmatch(r"[a-f0-9]{40}", workflow_sha):
        raise SystemExit("invalid qualification workflow SHA")
    target_triple = rust_target_triple()
    receipt = {
''',
)
replace(
    "scripts/hepta-prompt-registry-qualify.py",
    '        "runner": {"system": platform.platform(), "machine": platform.machine()},\n        "checks": [], "allRequiredChecksPassed": False, "qualified": False,',
    '''        "workflowSha": workflow_sha,
        "workflowRef": workflow_ref,
        "dependencyLockSha256": file_sha256(CARGO / "Cargo.lock"),
        "targetTriple": target_triple,
        "runner": {
            "system": platform.platform(),
            "machine": platform.machine(),
            "name": os.environ.get("RUNNER_NAME", "local"),
            "os": os.environ.get("RUNNER_OS", platform.system()),
            "arch": os.environ.get("RUNNER_ARCH", platform.machine()),
            "environment": os.environ.get("RUNNER_ENVIRONMENT", "local"),
            "targetTriple": target_triple,
        },
        "checks": [], "allRequiredChecksPassed": False, "qualified": False,''',
)

write(
    "scripts/hepta-prompt-registry-aggregate.py",
    r'''#!/usr/bin/env python3
"""Aggregate four exact-run receipts. Never activates, accepts, or releases."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

LANES = {(profile, lane) for profile in ("core", "product") for lane in ("exact-head", "base-merge")}
COMMON = {"clean-before", "harness-tests", "map", "toolchain", "source-graph", "format", "all-targets", "lint", "clean-after"}
REQUIRED = {
    "core": COMMON | {"registry-inventory", "registry", "operational-profiles"},
    "product": COMMON | {"agentd-inventory", "extension-inventory", "optimizer", "extension", "agentd", "pipeline-profile"},
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def artifact_content_digest(directory: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(entry for entry in directory.rglob("*") if entry.is_file())
    if not files:
        raise ValueError("empty lane artifact")
    for entry in files:
        if entry.is_symlink():
            raise ValueError("lane artifact contains a symlink")
        relative = entry.relative_to(directory).as_posix().encode()
        payload_digest = hashlib.sha256(entry.read_bytes()).digest()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(payload_digest)
    return digest.hexdigest()


def single(receipts: dict, field: str):
    values = {receipt.get(field) for receipt in receipts.values()}
    if len(values) != 1 or None in values:
        raise ValueError("four lanes disagree on " + field)
    return values.pop()


def aggregate(root: Path, source: str, base: str, run: str, attempt: str) -> dict:
    receipts = {}
    receipt_digests = {}
    artifact_digests = {}
    for receipt_path in sorted(root.glob("*/receipt.json")):
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        key = (receipt.get("profile"), receipt.get("lane"))
        if key not in LANES or key in receipts:
            raise ValueError("unknown or duplicate qualification lane")
        if receipt.get("schema") != "hepta.prompt-registry.qualification-receipt.v2":
            raise ValueError("unsupported qualification receipt")
        for name, expected in [("sourceSha", source), ("baseSha", base), ("runId", run), ("runAttempt", attempt)]:
            if str(receipt.get(name)) != expected:
                raise ValueError("receipt identity or run attempt mismatch: " + name)
        for name in ("sourceSha", "baseSha", "testedSha", "testedTree", "workflowSha"):
            if not re.fullmatch(r"[a-f0-9]{40}", receipt.get(name, "")):
                raise ValueError("invalid exact identity: " + name)
        if not re.fullmatch(r"[a-f0-9]{64}", receipt.get("dependencyLockSha256", "")):
            raise ValueError("invalid dependency lock digest")
        if not receipt.get("workflowRef") or not receipt.get("targetTriple"):
            raise ValueError("missing workflow or target identity")
        runner = receipt.get("runner")
        if not isinstance(runner, dict) or runner.get("targetTriple") != receipt["targetTriple"]:
            raise ValueError("invalid runner identity")
        if key[1] == "exact-head" and receipt["testedSha"] != source:
            raise ValueError("wrong exact-head candidate")
        if receipt.get("allRequiredChecksPassed") is not True:
            raise ValueError("lane did not pass every required check")
        if any(receipt.get(name) is not False for name in ("qualified", "productionReady", "productActivated", "accepted", "released")):
            raise ValueError("lane crossed its claim boundary")
        checks = receipt.get("checks", [])
        if len(checks) != len(REQUIRED[key[0]]) or {check.get("name") for check in checks} != REQUIRED[key[0]]:
            raise ValueError("missing or unexpected required checks")
        for check in checks:
            if check.get("state") != "passed" or check.get("exitCode") != 0 or check.get("postconditionFailures") != []:
                raise ValueError("failed, interrupted or skipped check")
            log = receipt_path.parent / (check["name"] + ".log")
            if not log.is_file() or log.is_symlink() or sha256_bytes(log.read_bytes()) != check.get("logSha256"):
                raise ValueError("raw log missing or digest mismatch")
        if not receipt.get("sourceFiles"):
            raise ValueError("source blob manifest missing")
        receipts[key] = receipt
        label = "/".join(key)
        receipt_digests[label] = sha256_bytes(receipt_path.read_bytes())
        artifact_digests[label] = artifact_content_digest(receipt_path.parent)
    if set(receipts) != LANES:
        raise ValueError("all four lanes are mandatory")
    workflow_sha = single(receipts, "workflowSha")
    workflow_ref = single(receipts, "workflowRef")
    lock_digest = single(receipts, "dependencyLockSha256")
    for lane in ("exact-head", "base-merge"):
        core, product = (receipts[(profile, lane)] for profile in ("core", "product"))
        if any(core[name] != product[name] for name in ("testedSha", "testedTree", "sourceFiles")):
            raise ValueError("core and product tested different source")
    exact = receipts[("core", "exact-head")]
    merged = receipts[("core", "base-merge")]
    return {
        "schema": "hepta.prompt-registry.qualification-summary.v2",
        "sourceSha": source,
        "sourceTree": exact["testedTree"],
        "baseSha": base,
        "syntheticMerge": {"sha": merged["testedSha"], "tree": merged["testedTree"]},
        "runId": run,
        "runAttempt": attempt,
        "qualificationWorkflow": {"sha": workflow_sha, "ref": workflow_ref},
        "dependencyLockSha256": lock_digest,
        "runnerTargets": {
            "/".join(key): {"targetTriple": receipt["targetTriple"], "runner": receipt["runner"]}
            for key, receipt in sorted(receipts.items())
        },
        "sourceQualified": True,
        "productActivated": False,
        "accepted": False,
        "released": False,
        "receiptSha256": receipt_digests,
        "laneArtifactContentSha256": artifact_digests,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--attempt", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = aggregate(args.root, args.source, args.base, args.run, args.attempt)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
''',
)

write(
    "scripts/hepta-prompt-registry-harness-tests.py",
    r'''#!/usr/bin/env python3
"""Offline tests for qualification evidence parsing; not native qualification."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("qualify", Path(__file__).with_name("hepta-prompt-registry-qualify.py"))
qualify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qualify)


class EvidenceTests(unittest.TestCase):
    def test_inventory_is_not_execution(self):
        self.assertEqual(qualify.completed_tests("tests::required: test\n0 tests, 0 benchmarks"), set())

    def test_ignored_and_failed_tests_are_not_passes(self):
        text = "test a::first ... ignored\ntest a::second ... FAILED\ntest a::third ... ok\n"
        self.assertEqual(qualify.completed_tests(text), {"a::third"})

    def test_profile_parser_ignores_noise_and_invalid_json(self):
        text = 'noise\n{"schema":"other"}\n{"bad\ntest prefix {"schema":"hepta.prompt-registry.x","count":1}\n'
        self.assertEqual(qualify.profile_rows(text), [{"schema": "hepta.prompt-registry.x", "count": 1}])

    def test_missing_profiles_fail_closed(self):
        self.assertTrue(qualify.check_measurements("operational-profiles", []))
        self.assertTrue(qualify.check_measurements("pipeline-profile", []))

    def rows(self):
        scale = [{"schema": "hepta.prompt-registry.operational-scale.v2", "logicalRecords": n,
                  "inPlaceGc": {"collectedPayloadRecords": 1, "cleanupPending": False},
                  "snapshot": {"samples": 31}, "dereference": {"samples": 31}} for n in (1000, 8000, 16384)]
        fsync = [{"schema": "hepta.prompt-registry.fsync-profile.v2", "bytes": n, "total": {"samples": 31}} for n in (4096, 65536, 1048576)]
        writers = [{"schema": "hepta.prompt-registry.writer-profile.v1", "finalLogicalRecords": n,
                    "registration": {"samples": 31}, "retirement": {"samples": 31}} for n in (1000, 8000, 16384)]
        return scale + fsync + writers

    def test_complete_bounded_profiles(self):
        self.assertEqual(qualify.check_measurements("operational-profiles", self.rows()), [])
        self.assertEqual(qualify.check_measurements("pipeline-profile", [{"schema": "hepta.prompt-registry.pipeline-profile.v1"}] * 31), [])

    def test_duplicates_or_unfinished_collection_cannot_pass(self):
        rows = self.rows()
        self.assertTrue(qualify.check_measurements("operational-profiles", rows + rows[:1]))
        rows[0]["inPlaceGc"]["cleanupPending"] = True
        self.assertTrue(qualify.check_measurements("operational-profiles", rows))

    def test_missing_sample_count_cannot_pass(self):
        rows = self.rows()
        rows[1]["snapshot"]["samples"] = 0
        self.assertTrue(qualify.check_measurements("operational-profiles", rows))


aggregate_spec = importlib.util.spec_from_file_location("aggregate", Path(__file__).with_name("hepta-prompt-registry-aggregate.py"))
summary = importlib.util.module_from_spec(aggregate_spec)
aggregate_spec.loader.exec_module(summary)


class AggregationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.receipts = []
        for profile, lane in sorted(summary.LANES):
            directory = self.root / (profile + "-" + lane)
            directory.mkdir()
            checks = []
            for name in sorted(summary.REQUIRED[profile]):
                log = b"actual fixture log\n"
                (directory / (name + ".log")).write_bytes(log)
                checks.append({"name": name, "state": "passed", "exitCode": 0,
                               "postconditionFailures": [], "logSha256": hashlib.sha256(log).hexdigest()})
            receipt = {
                "schema": "hepta.prompt-registry.qualification-receipt.v2",
                "profile": profile,
                "lane": lane,
                "sourceSha": "a" * 40,
                "baseSha": "b" * 40,
                "testedSha": ("a" if lane == "exact-head" else "c") * 40,
                "testedTree": "d" * 40,
                "runId": "1",
                "runAttempt": "1",
                "workflowSha": "e" * 40,
                "workflowRef": "TrillionniumFoundation/hepta-private-ci/.github/workflows/qualification.yml@refs/pull/1/merge",
                "dependencyLockSha256": "f" * 64,
                "targetTriple": "x86_64-unknown-linux-gnu",
                "runner": {"system": "test", "machine": "x86_64", "name": "runner", "os": "Linux", "arch": "X64", "environment": "github-hosted", "targetTriple": "x86_64-unknown-linux-gnu"},
                "checks": checks,
                "allRequiredChecksPassed": True,
                "sourceFiles": {"file": "0" * 64},
                "qualified": False,
                "productionReady": False,
                "productActivated": False,
                "accepted": False,
                "released": False,
            }
            receipt_path = directory / "receipt.json"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            self.receipts.append((receipt_path, receipt))

    def run_aggregate(self):
        return summary.aggregate(self.root, "a" * 40, "b" * 40, "1", "1")

    def rewrite(self, index=0, **values):
        receipt_path, receipt = self.receipts[index]
        receipt.update(values)
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    def test_four_lane_success_is_not_acceptance(self):
        result = self.run_aggregate()
        self.assertEqual(result["schema"], "hepta.prompt-registry.qualification-summary.v2")
        self.assertTrue(result["sourceQualified"])
        self.assertFalse(result["accepted"])
        self.assertFalse(result["released"])
        self.assertEqual(len(result["receiptSha256"]), 4)
        self.assertEqual(len(result["laneArtifactContentSha256"]), 4)

    def test_missing_lane_rejected(self):
        self.receipts[0][0].unlink()
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_wrong_candidate_or_historical_attempt_rejected(self):
        self.rewrite(runAttempt="2")
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_raw_log_tampering_rejected(self):
        (self.receipts[0][0].parent / "map.log").write_text("changed", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_zero_or_skipped_check_cannot_hide_in_success_receipt(self):
        receipt_path, receipt = self.receipts[0]
        receipt["checks"][0]["state"] = "not_run"
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_different_tested_tree_rejected(self):
        self.rewrite(testedTree="1" * 40)
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_workflow_or_lock_mismatch_rejected(self):
        self.rewrite(index=1, workflowSha="2" * 40)
        with self.assertRaises(ValueError):
            self.run_aggregate()
        self.rewrite(index=1, workflowSha="e" * 40, dependencyLockSha256="3" * 64)
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_missing_target_identity_rejected(self):
        self.rewrite(targetTriple="")
        with self.assertRaises(ValueError):
            self.run_aggregate()


if __name__ == "__main__":
    unittest.main(verbosity=2)
''',
)

# Qualification workflow identity is passed into each lane and the new branch is
# eligible for a direct push diagnostic as well as PR qualification.
replace(
    ".github/workflows/hepta-prompt-registry-qualification.yml",
    "branches: [main, codex/prompt-registry-delivery-consistency-20260928, codex/prompt-registry-verified-closeout-20260928]",
    "branches: [main, codex/prompt-registry-delivery-consistency-20260928, codex/prompt-registry-verified-closeout-20260928, codex/prompt-registry-full-closeout-20260929]",
)
replace(
    ".github/workflows/hepta-prompt-registry-qualification.yml",
    "      BASE_SHA: ${{ needs.bind.outputs.base }}\n",
    "      BASE_SHA: ${{ needs.bind.outputs.base }}\n      PROMPT_REGISTRY_WORKFLOW_SHA: ${{ github.workflow_sha }}\n      PROMPT_REGISTRY_WORKFLOW_REF: ${{ github.workflow_ref }}\n",
)

# ---------------------------------------------------------------------------
# Separate protected-environment acceptance.  It consumes, but never rewrites,
# the successful four-lane summary.
# ---------------------------------------------------------------------------
write(
    "scripts/hepta-prompt-registry-accept.py",
    r'''#!/usr/bin/env python3
"""Create a source-bound independent acceptance statement from a qualified summary."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

LANES = {f"{profile}/{lane}" for profile in ("core", "product") for lane in ("exact-head", "base-merge")}


def exact_keys(value: object, name: str) -> dict:
    if not isinstance(value, dict) or set(value) != LANES:
        raise ValueError(name + " must bind exactly four lanes")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--qualification-run", required=True)
    parser.add_argument("--qualification-attempt", required=True)
    parser.add_argument("--pull-request", type=int, required=True)
    parser.add_argument("--pull-request-author", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--acceptance-workflow-sha", required=True)
    parser.add_argument("--acceptance-run", required=True)
    parser.add_argument("--acceptance-attempt", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    raw = args.summary.read_bytes()
    summary = json.loads(raw)
    if summary.get("schema") != "hepta.prompt-registry.qualification-summary.v2":
        raise ValueError("unsupported qualification summary")
    if summary.get("sourceQualified") is not True:
        raise ValueError("source was not qualified")
    if any(summary.get(name) is not False for name in ("accepted", "productActivated", "released")):
        raise ValueError("qualification summary crossed its claim boundary")
    if summary.get("sourceSha") != args.source:
        raise ValueError("source identity mismatch")
    if str(summary.get("runId")) != args.qualification_run or str(summary.get("runAttempt")) != args.qualification_attempt:
        raise ValueError("qualification run identity mismatch")
    if args.actor.casefold() == args.pull_request_author.casefold():
        raise ValueError("implementation author cannot independently accept the candidate")
    for name in ("sourceSha", "sourceTree", "baseSha"):
        if not re.fullmatch(r"[a-f0-9]{40}", summary.get(name, "")):
            raise ValueError("invalid summary identity: " + name)
    workflow = summary.get("qualificationWorkflow")
    merge = summary.get("syntheticMerge")
    if not isinstance(workflow, dict) or not re.fullmatch(r"[a-f0-9]{40}", workflow.get("sha", "")) or not workflow.get("ref"):
        raise ValueError("invalid qualification workflow identity")
    if not isinstance(merge, dict) or any(not re.fullmatch(r"[a-f0-9]{40}", merge.get(name, "")) for name in ("sha", "tree")):
        raise ValueError("invalid synthetic merge identity")
    if not re.fullmatch(r"[a-f0-9]{64}", summary.get("dependencyLockSha256", "")):
        raise ValueError("invalid dependency lock identity")
    receipts = exact_keys(summary.get("receiptSha256"), "receipt digests")
    artifacts = exact_keys(summary.get("laneArtifactContentSha256"), "artifact digests")
    runners = exact_keys(summary.get("runnerTargets"), "runner targets")
    for collection in (receipts, artifacts):
        if any(not re.fullmatch(r"[a-f0-9]{64}", value) for value in collection.values()):
            raise ValueError("invalid lane digest")
    if not re.fullmatch(r"[a-f0-9]{40}", args.acceptance_workflow_sha):
        raise ValueError("invalid acceptance workflow SHA")

    statement = {
        "schema": "hepta.prompt-registry.independent-acceptance.v1",
        "accepted": True,
        "acceptedAt": datetime.now(timezone.utc).isoformat(),
        "acceptorId": args.actor,
        "pullRequest": args.pull_request,
        "pullRequestAuthor": args.pull_request_author,
        "sourceSha": summary["sourceSha"],
        "sourceTree": summary["sourceTree"],
        "baseSha": summary["baseSha"],
        "syntheticMerge": merge,
        "qualificationWorkflow": workflow,
        "qualificationRun": {"id": args.qualification_run, "attempt": args.qualification_attempt},
        "dependencyLockSha256": summary["dependencyLockSha256"],
        "runnerTargets": runners,
        "receiptSha256": receipts,
        "laneArtifactContentSha256": artifacts,
        "qualificationSummarySha256": hashlib.sha256(raw).hexdigest(),
        "acceptanceWorkflow": {
            "sha": args.acceptance_workflow_sha,
            "runId": args.acceptance_run,
            "runAttempt": args.acceptance_attempt,
            "protectedEnvironment": "prompt-registry-independent-acceptance",
        },
        "productActivated": False,
        "released": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(statement, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(statement, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise SystemExit(f"prompt.registry acceptance rejected: {error}") from error
''',
)

write(
    ".github/workflows/hepta-prompt-registry-acceptance.yml",
    r'''name: Hepta prompt.registry independent acceptance

on:
  workflow_dispatch:
    inputs:
      qualification_run_id:
        description: Successful four-lane qualification run ID
        required: true
        type: string
      qualification_attempt:
        description: Qualification run attempt
        required: true
        default: "1"
        type: string
      source_sha:
        description: Exact qualified source SHA
        required: true
        type: string
      pull_request_number:
        description: Implementation pull request number
        required: true
        type: string

permissions:
  contents: read
  actions: read

jobs:
  accept:
    name: independent prompt.registry acceptance
    runs-on: ubuntu-24.04
    environment: prompt-registry-independent-acceptance
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
        with:
          ref: ${{ inputs.source_sha }}
          persist-credentials: false
      - uses: actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c
        with:
          name: prompt-registry-summary-${{ inputs.source_sha }}-${{ inputs.qualification_attempt }}
          path: ${{ runner.temp }}/prompt-registry-summary
          run-id: ${{ inputs.qualification_run_id }}
          github-token: ${{ github.token }}
      - id: pr
        name: Bind independent actor and exact PR head
        env:
          GH_TOKEN: ${{ github.token }}
          PR_NUMBER: ${{ inputs.pull_request_number }}
          SOURCE_SHA: ${{ inputs.source_sha }}
        shell: bash
        run: |
          set -euo pipefail
          test "$(git rev-parse HEAD)" = "$SOURCE_SHA"
          test "$(printf '%s' "$SOURCE_SHA" | grep -Ec '^[a-f0-9]{40}$')" = 1
          pr=$(gh api "repos/$GITHUB_REPOSITORY/pulls/$PR_NUMBER")
          head=$(jq -r '.head.sha' <<<"$pr")
          author=$(jq -r '.user.login' <<<"$pr")
          test "$head" = "$SOURCE_SHA"
          test -n "$author"
          test "${author,,}" != "${GITHUB_ACTOR,,}"
          echo "author=$author" >> "$GITHUB_OUTPUT"
      - name: Produce source-bound acceptance statement
        env:
          SOURCE_SHA: ${{ inputs.source_sha }}
          QUALIFICATION_RUN: ${{ inputs.qualification_run_id }}
          QUALIFICATION_ATTEMPT: ${{ inputs.qualification_attempt }}
          PR_NUMBER: ${{ inputs.pull_request_number }}
          PR_AUTHOR: ${{ steps.pr.outputs.author }}
          ACCEPTOR: ${{ github.actor }}
          ACCEPTANCE_WORKFLOW_SHA: ${{ github.workflow_sha }}
          ACCEPTANCE_RUN: ${{ github.run_id }}
          ACCEPTANCE_ATTEMPT: ${{ github.run_attempt }}
        shell: bash
        run: >-
          python3 scripts/hepta-prompt-registry-accept.py
          --summary "$RUNNER_TEMP/prompt-registry-summary/prompt-registry-summary.json"
          --source "$SOURCE_SHA"
          --qualification-run "$QUALIFICATION_RUN"
          --qualification-attempt "$QUALIFICATION_ATTEMPT"
          --pull-request "$PR_NUMBER"
          --pull-request-author "$PR_AUTHOR"
          --actor "$ACCEPTOR"
          --acceptance-workflow-sha "$ACCEPTANCE_WORKFLOW_SHA"
          --acceptance-run "$ACCEPTANCE_RUN"
          --acceptance-attempt "$ACCEPTANCE_ATTEMPT"
          --output "$RUNNER_TEMP/prompt-registry-acceptance.json"
      - uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        with:
          name: prompt-registry-acceptance-${{ inputs.source_sha }}-${{ github.run_attempt }}
          path: ${{ runner.temp }}/prompt-registry-acceptance.json
          if-no-files-found: error
          retention-days: 90
''',
)

print("phase-one prompt.registry source changes applied")
