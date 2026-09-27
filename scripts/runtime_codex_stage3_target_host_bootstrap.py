#!/usr/bin/env python3
"""One-shot exact-source target-host qualification hardening."""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "scripts/runtime_codex_target_host_evidence.py": "97741544e0f483710d1b58e0d7a4a4b13e801fc4",
    "scripts/tests/test_runtime_codex_target_host_evidence.py": "2c980f6401447e54e496112ad2d80e2106b74471",
    ".github/workflows/runtime-codex-target-host.yml": "8ae42ff2c7ff272eea1d98c5732630b9ed7f8bb3",
}


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def write(name: str, text: str) -> None:
    (ROOT / name).write_text(text, encoding="utf-8")


def verify(name: str, expected: str) -> None:
    actual = subprocess.check_output(["git", "hash-object", "--", name], cwd=ROOT, text=True).strip()
    if actual != expected:
        raise SystemExit(f"{name}: expected {expected}, got {actual}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def replace_between(text: str, start: str, end: str, replacement: str, label: str) -> str:
    first = text.find(start)
    if first < 0 or text.find(start, first + 1) >= 0:
        raise SystemExit(f"{label}: missing or ambiguous start marker")
    stop = text.find(end, first + len(start))
    if stop < 0:
        raise SystemExit(f"{label}: end marker missing")
    return text[:first] + replacement + text[stop:]


def patch_evidence() -> None:
    name = "scripts/runtime_codex_target_host_evidence.py"
    text = read(name)
    old = '''FAULT_SCENARIOS = (
    "provider-ack-loss",
    "event-lag",
    "process-death",
    "agentd-restart",
)
FAULT_OUTCOMES = {
    "provider-ack-loss": {"reconciled_terminal", "indeterminate", "quarantined"},
    "event-lag": {"quarantined"},
    "process-death": {"reconciled_terminal", "indeterminate", "quarantined"},
    "agentd-restart": {"reconciled_terminal", "indeterminate", "quarantined"},
}
EVIDENCE_SCHEMAS = {
    "host-identity.json": "hepta.runtime-codex-host-identity.v1",
    "issuer-custody.json": "hepta.runtime-codex-issuer-custody.v1",
    "anti-rollback.json": "hepta.runtime-codex-anti-rollback.v1",
}
'''
    new = '''FAULT_SCENARIOS = (
    "provider-ack-loss",
    "event-lag",
    "worker-kill-after-fence",
    "worker-restart",
    "agentd-restart",
    "revocation-advance-before-entry",
    "duplicate-owner",
    "stale-revision",
)
FAULT_OUTCOMES = {
    "provider-ack-loss": {"reconciled_terminal", "indeterminate", "quarantined"},
    "event-lag": {"quarantined"},
    "worker-kill-after-fence": {"reconciled_terminal", "indeterminate", "quarantined"},
    "worker-restart": {"reconciled_terminal", "indeterminate", "quarantined"},
    "agentd-restart": {"reconciled_terminal", "indeterminate", "quarantined"},
    "revocation-advance-before-entry": {"rejected_before_send"},
    "duplicate-owner": {"single_winner"},
    "stale-revision": {"rejected_before_send"},
}
ZERO_SEND_FAULTS = {
    "revocation-advance-before-entry",
    "stale-revision",
}
RESTART_FAULTS = {"worker-restart", "agentd-restart"}
EVIDENCE_SCHEMAS = {
    "host-identity.json": "hepta.runtime-codex-host-identity.v1",
    "issuer-custody.json": "hepta.runtime-codex-issuer-custody.v1",
    "anti-rollback.json": "hepta.runtime-codex-anti-rollback.v1",
    "canary-rollback.json": "hepta.runtime-codex-canary-rollback.v1",
    "independent-acceptance.json": "hepta.runtime-codex-independent-acceptance.v1",
}
'''
    text = replace_once(text, old, new, "fault and external evidence inventory")

    start = '''def validate_fault(
    path: Path, scenario: str, source_sha: str
) -> dict[str, Any]:'''
    end = '''def build_manifest(args: argparse.Namespace) -> dict[str, Any]:'''
    replacement = '''def validate_fault(
    path: Path, scenario: str, source_sha: str
) -> dict[str, Any]:
    value = load_json(path)
    if value.get("schema") != "hepta.runtime-codex-fault-evidence.v2":
        raise EvidenceError(f"unsupported fault evidence schema: {path}")
    if value.get("schemaVersion") != 2 or value.get("scenario") != scenario:
        raise EvidenceError(f"fault evidence scenario mismatch: {path}")
    if value.get("sourceSha") != source_sha or value.get("verified") is not True:
        raise EvidenceError(f"fault evidence is unverified or source-mismatched: {path}")
    expected_requests = 0 if scenario in ZERO_SEND_FAULTS else 1
    if value.get("physicalRequestCount") != expected_requests:
        raise EvidenceError(f"fault scenario has an invalid physical request count: {path}")
    if value.get("freshFenceAckCount") != expected_requests:
        raise EvidenceError(f"fault scenario has an invalid fresh-fence winner count: {path}")
    if value.get("duplicateRequestCount") != 0 or value.get("replayedRequestCount") != 0:
        raise EvidenceError(f"fault scenario observed a duplicate or replay: {path}")
    if value.get("abortAfterFenceAccepted") is not False:
        raise EvidenceError(f"fault scenario accepted abort after the effect-entry fence: {path}")
    if value.get("ownerRevisionMonotonic") is not True:
        raise EvidenceError(f"fault scenario lost owner revision monotonicity: {path}")
    if value.get("durableOutcome") not in FAULT_OUTCOMES[scenario]:
        raise EvidenceError(f"fault scenario has an invalid durable outcome: {path}")
    unresolved = value["durableOutcome"] in {"indeterminate", "quarantined"}
    if value.get("unresolvedCapacityRetained") is not unresolved:
        raise EvidenceError(f"fault scenario has an invalid capacity disposition: {path}")
    if not isinstance(value.get("operationId"), str) or not value["operationId"]:
        raise EvidenceError(f"fault scenario omitted operation identity: {path}")
    for field in ("journalSha256", "providerAuditSha256", "harnessSha256"):
        require_sha(value.get(field), f"{scenario}.{field}", HEX64)
    required_observation = {
        "event-lag": "eventLagObserved",
        "worker-kill-after-fence": "workerKillObserved",
        "worker-restart": "workerRestartObserved",
        "agentd-restart": "agentdRestartObserved",
        "revocation-advance-before-entry": "revocationAdvanceObserved",
        "duplicate-owner": "duplicateOwnerObserved",
        "stale-revision": "staleRevisionRejected",
    }.get(scenario)
    if required_observation and value.get(required_observation) is not True:
        raise EvidenceError(f"fault scenario omitted {required_observation}: {path}")
    return value


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:'''
    text = replace_between(text, start, end, replacement, "strict fault validation")
    text = replace_once(
        text,
        '''    if args.iterations < 3 or args.iterations > 20:
        raise EvidenceError("iterations must be in 3..=20")''',
        '''    if args.iterations < 30 or args.iterations > 200:
        raise EvidenceError("iterations must be in 30..=200")''',
        "statistical sample floor",
    )
    text = replace_once(
        text,
        '''        "iterations": args.iterations,
        "runs": runs,''',
        '''        "iterations": args.iterations,
        "minimumStatisticalSampleMet": args.iterations >= 30,
        "runs": runs,''',
        "sample evidence field",
    )
    text = replace_once(
        text,
        '''            "targetHostEvidenceCollected": True,
            "independentAcceptance": False,''',
        '''            "targetHostEvidenceCollected": True,
            "canaryRollbackEvidenceCollected": True,
            "independentAcceptanceEvidenceCollected": True,
            "independentAcceptance": False,''',
        "external evidence claim boundary",
    )
    write(name, text)


def patch_tests() -> None:
    name = "scripts/tests/test_runtime_codex_target_host_evidence.py"
    text = read(name)
    text = replace_once(text, "range(1, 4)", "range(1, 31)", "test canary count")
    text = replace_once(
        text,
        '''                    "physicalRequestCount": 3,
                    "duplicateRequestCount": 0,
                    "requestIds": ["one", "two", "three"],''',
        '''                    "physicalRequestCount": 30,
                    "duplicateRequestCount": 0,
                    "requestIds": [f"request-{index}" for index in range(1, 31)],''',
        "provider audit sample",
    )
    old_fault = '''                        "schema": "hepta.runtime-codex-fault-evidence.v1",
                        "schemaVersion": 1,
                        "scenario": scenario,
                        "sourceSha": source,
                        "verified": True,
                        "physicalRequestCount": 1,
                        "duplicateRequestCount": 0,
                        "replayedRequestCount": 0,
                        "durableOutcome": outcome,
                        "operationId": f"operation:{scenario}",
                        "journalSha256": "f" * 64,
                        "restartObserved": scenario == "agentd-restart",'''
    new_fault = '''                        "schema": "hepta.runtime-codex-fault-evidence.v2",
                        "schemaVersion": 2,
                        "scenario": scenario,
                        "sourceSha": source,
                        "verified": True,
                        "physicalRequestCount": 0 if scenario in module.ZERO_SEND_FAULTS else 1,
                        "freshFenceAckCount": 0 if scenario in module.ZERO_SEND_FAULTS else 1,
                        "duplicateRequestCount": 0,
                        "replayedRequestCount": 0,
                        "abortAfterFenceAccepted": False,
                        "ownerRevisionMonotonic": True,
                        "unresolvedCapacityRetained": outcome in {"indeterminate", "quarantined"},
                        "durableOutcome": outcome,
                        "operationId": f"operation:{scenario}",
                        "journalSha256": "f" * 64,
                        "providerAuditSha256": "1" * 64,
                        "harnessSha256": "2" * 64,
                        "eventLagObserved": scenario == "event-lag",
                        "workerKillObserved": scenario == "worker-kill-after-fence",
                        "workerRestartObserved": scenario == "worker-restart",
                        "agentdRestartObserved": scenario == "agentd-restart",
                        "revocationAdvanceObserved": scenario == "revocation-advance-before-entry",
                        "duplicateOwnerObserved": scenario == "duplicate-owner",
                        "staleRevisionRejected": scenario == "stale-revision",'''
    text = replace_once(text, old_fault, new_fault, "fault fixture v2")
    text = replace_once(text, '"iterations": 3,', '"iterations": 30,', "test iteration count")
    text = replace_once(
        text,
        '''            self.assertTrue(manifest["claimBoundary"]["faultMatrixExecuted"])
            self.assertFalse(manifest["claimBoundary"]["release"])''',
        '''            self.assertTrue(manifest["minimumStatisticalSampleMet"])
            self.assertTrue(manifest["claimBoundary"]["faultMatrixExecuted"])
            self.assertTrue(
                manifest["claimBoundary"]["independentAcceptanceEvidenceCollected"]
            )
            self.assertFalse(manifest["claimBoundary"]["release"])''',
        "manifest assertions",
    )
    text = replace_once(
        text,
        '''            value["replayedRequestCount"] = 1
            write_json(broken, value)
            with self.assertRaises(module.EvidenceError):
                module.build_manifest(args)''',
        '''            value["replayedRequestCount"] = 1
            write_json(broken, value)
            with self.assertRaises(module.EvidenceError):
                module.build_manifest(args)

            value["replayedRequestCount"] = 0
            value["abortAfterFenceAccepted"] = True
            write_json(broken, value)
            with self.assertRaises(module.EvidenceError):
                module.build_manifest(args)''',
        "abort-after-fence negative test",
    )
    write(name, text)


def patch_workflow() -> None:
    name = ".github/workflows/runtime-codex-target-host.yml"
    text = read(name)
    text = replace_once(
        text,
        '''      journal_root:
        description: Absolute owner-private qualification journal directory
        required: true
        type: string
      iterations:
        description: Number of physical real-provider canary operations (3..20)
        required: true
        default: "5"
        type: string''',
        '''      journal_root:
        description: Absolute owner-private qualification journal directory
        required: true
        type: string
      fault_harness:
        description: Absolute independently provisioned runtime.codex fault harness
        required: true
        type: string
      iterations:
        description: Number of physical real-provider canary operations (30..200)
        required: true
        default: "50"
        type: string''',
        "workflow inputs",
    )
    text = replace_once(
        text,
        '''      JOURNAL_ROOT: ${{ inputs.journal_root }}
      ITERATIONS: ${{ inputs.iterations }}''',
        '''      JOURNAL_ROOT: ${{ inputs.journal_root }}
      FAULT_HARNESS: ${{ inputs.fault_harness }}
      ITERATIONS: ${{ inputs.iterations }}''',
        "fault harness environment",
    )
    text = replace_once(
        text,
        '''          (( ITERATIONS >= 3 && ITERATIONS <= 20 ))
          test -S "${AGENTD_SOCKET}"
          test -f "${AUTHORITY_CONFIG}"
          test -d "${JOURNAL_ROOT}"''',
        '''          (( ITERATIONS >= 30 && ITERATIONS <= 200 ))
          test -S "${AGENTD_SOCKET}"
          test -f "${AUTHORITY_CONFIG}"
          test -d "${JOURNAL_ROOT}"
          [[ "${FAULT_HARNESS}" = /* ]]
          test -x "${FAULT_HARNESS}"''',
        "target-host preflight",
    )
    text = replace_once(
        text,
        '''          test -f "${HEPTA_RUNTIME_CODEX_ANTI_ROLLBACK_EVIDENCE:?}"
          test -x "${HEPTA_RUNTIME_CODEX_PROVIDER_AUDIT_EXPORTER:?}"''',
        '''          test -f "${HEPTA_RUNTIME_CODEX_ANTI_ROLLBACK_EVIDENCE:?}"
          test -f "${HEPTA_RUNTIME_CODEX_CANARY_ROLLBACK_EVIDENCE:?}"
          test -f "${HEPTA_RUNTIME_CODEX_INDEPENDENT_ACCEPTANCE_EVIDENCE:?}"
          test -x "${HEPTA_RUNTIME_CODEX_PROVIDER_AUDIT_EXPORTER:?}"''',
        "independent evidence preflight",
    )
    text = replace_once(
        text,
        '''      - name: Build the named native caller
        working-directory: codex-rs
        run: cargo build --locked -p codex-hepta-infer-worker-host --bin hepta-infer-worker''',
        '''      - name: Verify target-host evidence tooling
        run: python3 -m unittest -v scripts.tests.test_runtime_codex_target_host_evidence

      - name: Build the named native caller
        working-directory: codex-rs
        run: cargo build --locked -p codex-hepta-infer-worker-host --bin hepta-infer-worker''',
        "evidence tool tests",
    )
    marker = '''      - name: Build target-host evidence manifest
        shell: bash'''
    fault_step = '''      - name: Execute mandatory external fault matrix
        shell: bash
        run: |
          set -euo pipefail
          EVIDENCE="${RUNNER_TEMP}/runtime-codex-target-host"
          BINARY="${CARGO_TARGET_DIR:-$(pwd)/codex-rs/target}/debug/hepta-infer-worker"
          mkdir -p "${EVIDENCE}/faults"
          scenarios=(
            provider-ack-loss
            event-lag
            worker-kill-after-fence
            worker-restart
            agentd-restart
            revocation-advance-before-entry
            duplicate-owner
            stale-revision
          )
          for scenario in "${scenarios[@]}"; do
            "${FAULT_HARNESS}" \
              --scenario "${scenario}" \
              --source-sha "${SOURCE_SHA}" \
              --binary "${BINARY}" \
              --agentd-socket "${AGENTD_SOCKET}" \
              --agent-id "${AGENT_ID}" \
              --generation "${AGENT_GENERATION}" \
              --model "${MODEL}" \
              --authority-config "${AUTHORITY_CONFIG}" \
              --journal-root "${JOURNAL_ROOT}" \
              --output "${EVIDENCE}/faults/${scenario}.json"
          done

'''
    text = replace_once(text, marker, fault_step + marker, "external fault matrix step")
    text = replace_once(
        text,
        '''          cp "${HEPTA_RUNTIME_CODEX_HOST_IDENTITY_EVIDENCE}" "${EVIDENCE}/host-identity.evidence"
          cp "${HEPTA_RUNTIME_CODEX_ISSUER_CUSTODY_EVIDENCE}" "${EVIDENCE}/issuer-custody.evidence"
          cp "${HEPTA_RUNTIME_CODEX_ANTI_ROLLBACK_EVIDENCE}" "${EVIDENCE}/anti-rollback.evidence"''',
        '''          cp "${HEPTA_RUNTIME_CODEX_HOST_IDENTITY_EVIDENCE}" "${EVIDENCE}/host-identity.json"
          cp "${HEPTA_RUNTIME_CODEX_ISSUER_CUSTODY_EVIDENCE}" "${EVIDENCE}/issuer-custody.json"
          cp "${HEPTA_RUNTIME_CODEX_ANTI_ROLLBACK_EVIDENCE}" "${EVIDENCE}/anti-rollback.json"
          cp "${HEPTA_RUNTIME_CODEX_CANARY_ROLLBACK_EVIDENCE}" "${EVIDENCE}/canary-rollback.json"
          cp "${HEPTA_RUNTIME_CODEX_INDEPENDENT_ACCEPTANCE_EVIDENCE}" "${EVIDENCE}/independent-acceptance.json"''',
        "external evidence filenames",
    )
    start = '''          python3 - "${EVIDENCE}" <<'PY'
          import hashlib, json, math, os, platform, re, statistics, sys'''
    end = '''          mkdir -p .hepta-evidence/runtime-codex/target-host'''
    replacement = '''          python3 scripts/runtime_codex_target_host_evidence.py build \
            --evidence-root "${EVIDENCE}" \
            --source-sha "${SOURCE_SHA}" \
            --source-tree "$(git rev-parse HEAD^{tree})" \
            --agent-id "${AGENT_ID}" \
            --generation "${AGENT_GENERATION}" \
            --model "${MODEL}" \
            --iterations "${ITERATIONS}" \
            --output "${EVIDENCE}/manifest.json"
          python3 scripts/runtime_codex_target_host_evidence.py verify \
            "${EVIDENCE}/manifest.json"
          mkdir -p .hepta-evidence/runtime-codex/target-host'''
    text = replace_between(text, start, end, replacement, "canonical evidence builder")
    write(name, text)


def main() -> None:
    for name, expected in EXPECTED.items():
        verify(name, expected)
    patch_evidence()
    patch_tests()
    patch_workflow()
    (ROOT / ".github/workflows/runtime-codex-stage3-target-host-bootstrap.yml").unlink(missing_ok=True)
    Path(__file__).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
