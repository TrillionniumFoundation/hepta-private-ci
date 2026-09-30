#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text.rstrip() + "\n", encoding="utf-8")


def replace_once(path: str, old: str, new: str, marker: str) -> None:
    text = read(path)
    if marker in text:
        return
    if text.count(old) != 1:
        raise SystemExit(f"{path}: expected exactly one replacement anchor for {marker!r}")
    write(path, text.replace(old, new, 1))


def replace_count(path: str, old: str, new: str, count: int, marker: str) -> None:
    text = read(path)
    if marker in text:
        return
    if text.count(old) != count:
        raise SystemExit(f"{path}: expected {count} replacement anchors for {marker!r}")
    write(path, text.replace(old, new))


ACCEPT = "scripts/hepta-prompt-registry-accept.py"
WORKFLOW = ".github/workflows/hepta-prompt-registry-qualification.yml"

replace_once(
    ACCEPT,
    '''    if summary.get("schema") != "hepta.prompt-registry.qualification-summary.v2":
        raise ValueError("unsupported qualification summary")
    if summary.get("sourceQualified") is not True:
        raise ValueError("source was not qualified")
    if any(summary.get(name) is not False for name in ("accepted", "productActivated", "released")):
        raise ValueError("qualification summary crossed its claim boundary")
''',
    '''    if summary.get("schema") != "hepta.prompt-registry.qualification-summary.v4":
        raise ValueError("unsupported qualification summary")
    if any(summary.get(name) is not True for name in (
        "sourceQualified", "productionQualified", "closedWorldPublicFunctions",
        "productExecutionProved", "mergeReady",
    )):
        raise ValueError("repository candidate was not fully qualified")
    if summary.get("productionReady") is not False or any(
        summary.get(name) is not False
        for name in ("accepted", "productActivated", "released")
    ):
        raise ValueError("qualification summary crossed its claim boundary")
''',
    '"repository candidate was not fully qualified"',
)
replace_once(
    ACCEPT,
    '''    if str(summary.get("runId")) != args.qualification_run or str(summary.get("runAttempt")) != args.qualification_attempt:
        raise ValueError("qualification run identity mismatch")
''',
    '''    if str(summary.get("workflowRunId")) != args.qualification_run or str(summary.get("workflowRunAttempt")) != args.qualification_attempt:
        raise ValueError("qualification run identity mismatch")
''',
    'summary.get("workflowRunId")',
)
replace_once(
    ACCEPT,
    '''    for name in ("sourceSha", "sourceTree", "baseSha"):
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
''',
    '''    for name in (
        "sourceSha", "sourceTreeHash", "baseSha", "deterministicMergeSha",
        "deterministicMergeTree",
    ):
        if not re.fullmatch(r"[a-f0-9]{40}", summary.get(name, "")):
            raise ValueError("invalid summary identity: " + name)
    workflow = summary.get("qualificationWorkflow")
    if not isinstance(workflow, dict) or not re.fullmatch(r"[a-f0-9]{40}", workflow.get("sha", "")) or not workflow.get("ref"):
        raise ValueError("invalid qualification workflow identity")
    if not re.fullmatch(r"[a-f0-9]{64}", summary.get("cargoLockSha256", "")):
        raise ValueError("invalid dependency lock identity")
    readiness = summary.get("readinessManifest")
    if not isinstance(readiness, dict) or readiness.get("schema") != "hepta.prompt-registry.readiness-manifest.v1":
        raise ValueError("missing readiness manifest")
    if readiness.get("source_head_sha") != args.source or readiness.get("productionQualified") is not True or readiness.get("mergeReady") is not True:
        raise ValueError("readiness manifest identity or state mismatch")
    if readiness.get("productionReady") is not False:
        raise ValueError("readiness manifest crossed deployment boundary")
    receipts = exact_keys(summary.get("receiptSha256"), "receipt digests")
    artifacts = exact_keys(summary.get("laneArtifactContentSha256"), "artifact digests")
    runners = exact_keys(summary.get("runnerImages"), "runner images")
''',
    'readiness.get("source_head_sha")',
)
replace_once(
    ACCEPT,
    '''        "sourceTree": summary["sourceTree"],
        "baseSha": summary["baseSha"],
        "syntheticMerge": merge,
        "qualificationWorkflow": workflow,
        "qualificationRun": {"id": args.qualification_run, "attempt": args.qualification_attempt},
        "dependencyLockSha256": summary["dependencyLockSha256"],
        "runnerTargets": runners,
''',
    '''        "sourceTreeHash": summary["sourceTreeHash"],
        "baseSha": summary["baseSha"],
        "deterministicMergeSha": summary["deterministicMergeSha"],
        "deterministicMergeTree": summary["deterministicMergeTree"],
        "githubMergeSha": summary.get("githubMergeSha"),
        "finalMergeSha": summary.get("finalMergeSha"),
        "qualificationWorkflow": workflow,
        "qualificationRun": {"id": args.qualification_run, "attempt": args.qualification_attempt},
        "cargoLockSha256": summary["cargoLockSha256"],
        "migrationHash": summary["migrationHash"],
        "implementationMapSha256": summary["implementationMapSha256"],
        "documentationHash": summary["documentationHash"],
        "runnerImages": runners,
        "readinessManifest": readiness,
''',
    '"readinessManifest": readiness,',
)

replace_count(
    WORKFLOW,
    '''      - 'codex-rs/ext/hepta-prompt/**'
      - 'codex-rs/hepta-codex-adapter/**'
''',
    '''      - 'codex-rs/ext/hepta-prompt/**'
      - 'codex-rs/ext/extension-api/src/contributors/model_provider_policy.rs'
      - 'codex-rs/core/src/client.rs'
      - 'codex-rs/hepta-codex-adapter/**'
''',
    2,
    "codex-rs/ext/extension-api/src/contributors/model_provider_policy.rs",
)
replace_count(
    WORKFLOW,
    '''      - '.github/workflows/hepta-prompt-registry-acceptance.yml'
''',
    '''      - '.github/workflows/hepta-prompt-registry-acceptance.yml'
      - '.github/workflows/hepta-prompt-registry-operational-qualification.yml'
''',
    2,
    ".github/workflows/hepta-prompt-registry-operational-qualification.yml",
)

# The repository test filters intentionally accept module-qualified test names.
for relative in (
    "scripts/hepta-prompt-registry-fault-matrix.py",
    "scripts/hepta-prompt-registry-soak.py",
):
    text = read(relative)
    text = text.replace(', "--exact", "--nocapture"', ', "--nocapture"')
    text = text.replace(', "--exact", "--test-threads=1"', ', "--test-threads=1"')
    write(relative, text)

print("prompt.registry compatibility closeout patch applied")
