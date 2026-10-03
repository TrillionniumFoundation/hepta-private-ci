#!/usr/bin/env python3
"""Apply phase-three kernel.evidence product/operations closure.

This creates concrete operational targets, runbooks, drill/receipt contracts,
and long-retention archive manifests. It never self-issues external drill,
independent acceptance, canary, promotion, or release evidence.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def p(name: str) -> Path:
    return ROOT / name


def read(name: str) -> str:
    return p(name).read_text(encoding="utf-8")


def write(name: str, text: str) -> None:
    target = p(name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


if not p("codex-rs/hepta-evidence/src/trust_snapshot.rs").exists():
    raise SystemExit("phase two has not landed; refusing to apply phase three")

OPERATIONS_PROFILE = {
    "schema": "hepta.kernel-evidence-operations-profile.v1",
    "schemaVersion": 1,
    "module": "kernel.evidence",
    "state": "qualification_targets_not_measured",
    "serviceLevelObjectives": {
        "monthlyAvailabilityPercent": 99.95,
        "acknowledgedWriteRpoSeconds": 0,
        "singleHostRestoreRtoMinutes": 30,
        "appendLatencyMs": {"p95": 100, "p99": 500},
        "verifyLatencyMs": {"p95": 250, "p99": 1000},
        "queryPageLatencyMs": {"p95": 200, "p99": 750},
    },
    "capacityQualification": {
        "minimumQualificationRows": 1000000,
        "maximumQueryPageEntries": 512,
        "minimumSustainedAppendPerSecond": 50,
        "maximumCasConflictRatePercent": 0.1,
    },
    "metrics": [
        {
            "name": "kernel_evidence_append_total",
            "type": "counter",
            "labels": ["outcome"],
        },
        {
            "name": "kernel_evidence_append_latency_ms",
            "type": "histogram",
            "labels": [],
        },
        {
            "name": "kernel_evidence_verify_total",
            "type": "counter",
            "labels": ["disposition", "profile"],
        },
        {
            "name": "kernel_evidence_verify_latency_ms",
            "type": "histogram",
            "labels": ["profile"],
        },
        {
            "name": "kernel_evidence_query_page_latency_ms",
            "type": "histogram",
            "labels": [],
        },
        {
            "name": "kernel_evidence_frontier_generation",
            "type": "gauge",
            "labels": ["store_id"],
        },
        {
            "name": "kernel_evidence_frontier_age_ms",
            "type": "gauge",
            "labels": ["store_id"],
        },
        {
            "name": "kernel_evidence_trust_generation",
            "type": "gauge",
            "labels": ["agent_id"],
        },
        {
            "name": "kernel_evidence_cas_conflict_total",
            "type": "counter",
            "labels": ["backend"],
        },
        {
            "name": "kernel_evidence_recovery_required_total",
            "type": "counter",
            "labels": ["reason_class"],
        },
        {
            "name": "kernel_evidence_backup_fence_rejection_total",
            "type": "counter",
            "labels": [],
        },
        {
            "name": "kernel_evidence_database_bytes",
            "type": "gauge",
            "labels": ["store_id"],
        },
        {
            "name": "kernel_evidence_disk_free_bytes",
            "type": "gauge",
            "labels": ["mount"],
        },
    ],
    "alerts": [
        {
            "id": "KE-001",
            "severity": "page",
            "condition": "recovery_required_total increases",
            "window": "immediate",
        },
        {
            "id": "KE-002",
            "severity": "page",
            "condition": "frontier generation decreases or trust predecessor mismatches",
            "window": "immediate",
        },
        {
            "id": "KE-003",
            "severity": "page",
            "condition": "frontier age exceeds 100% of configured maximum",
            "window": "immediate",
        },
        {
            "id": "KE-004",
            "severity": "ticket",
            "condition": "frontier age exceeds 80% of configured maximum",
            "window": "5m",
        },
        {
            "id": "KE-005",
            "severity": "page",
            "condition": "disk free is below 10% or 10 GiB",
            "window": "5m",
        },
        {
            "id": "KE-006",
            "severity": "ticket",
            "condition": "disk free is below 20% or 20 GiB",
            "window": "15m",
        },
        {
            "id": "KE-007",
            "severity": "page",
            "condition": "CAS conflicts exceed 0.1% or any CAS result is indeterminate",
            "window": "5m",
        },
        {
            "id": "KE-008",
            "severity": "ticket",
            "condition": "append or verify p99 exceeds SLO",
            "window": "15m",
        },
        {
            "id": "KE-009",
            "severity": "page",
            "condition": "exact-candidate or archive receipt digest mismatch",
            "window": "immediate",
        },
        {
            "id": "KE-010",
            "severity": "page",
            "condition": "owner lock cannot be acquired on the selected production host",
            "window": "immediate",
        },
    ],
    "claimBoundary": {
        "targetsAreNotMeasurements": True,
        "sourceFixturesAreNotPhysicalDrills": True,
        "externalOperatorReceiptRequired": True,
    },
}
write(
    "docs/lane-a-foundation/kernel.evidence/OPERATIONS_PROFILE_V1.json",
    json.dumps(OPERATIONS_PROFILE, indent=2) + "\n",
)

OPERATIONS = r"""# kernel.evidence operations and service objectives

This document is the production operations contract for `kernel.evidence`. The
numbers below are qualification and activation gates. They are not historical
measurements and do not mark the module active.

## Service-level gates

| Objective | Activation target |
|---|---:|
| Monthly availability | 99.95% |
| RPO for acknowledged evidence writes | 0 seconds |
| RTO for a single-host restore | 30 minutes |
| Append latency | p95 <= 100 ms; p99 <= 500 ms |
| Verify latency | p95 <= 250 ms; p99 <= 1,000 ms |
| Paged query latency | p95 <= 200 ms; p99 <= 750 ms |
| CAS conflict rate | <= 0.1%; no unresolved outcome |

RPO zero applies only after the SQLite commit and independently durable frontier
acknowledgement required by the publication ceremony. A request whose commit or
CAS outcome is unknown is not acknowledged; it enters `recovery_required`.

## Required metrics and alerts

The machine-readable inventory is
[`OPERATIONS_PROFILE_V1.json`](OPERATIONS_PROFILE_V1.json). Alert `KE-001` pages
on any new `recovery_required` transition. Registry/frontier rollback, digest
mismatch, unknown CAS, archive substitution and owner-lock conflict also page
immediately. Frontier age at 80% of its maximum and disk free below the warning
threshold create tickets before the hard-stop threshold.

Every alert carries store ID, Agent generation, source commit/tree, trust and
frontier generations, backend identity digest and a redacted reason class. It
must not include payloads, signatures, private keys, credentials or evidence
contents.

## Capacity qualification

The selected production binary, filesystem and external backend must demonstrate
at least one million qualification rows, sustained 50 append operations per
second, bounded 512-entry pages, and the declared latency objectives under
concurrent append/query/verify and frontier publication. Censored, timed-out and
rejected operations are counted; they are never removed from the denominator.

## Operational authority

Dashboards and alerts observe; they do not grant acceptance, promotion or
release. Source tests and simulated faults cannot set `backupRestoreDrilled`,
`canaryAccepted` or `releaseApproved`. Those status changes require retained,
externally signed receipts from distinct authorized principals.
"""
write("docs/lane-a-foundation/kernel.evidence/OPERATIONS.md", OPERATIONS)

RUNBOOK = r"""# kernel.evidence operator runbook

## Universal stop rule

On identity, digest, generation, signature, CAS acknowledgement, database
integrity or owner-lock ambiguity, stop writes and enter `recovery_required`.
Do not create a new ID, delete a conflicting row, roll back the trust registry,
or retry a CAS until an authenticated latest read resolves the outcome.

## Issuer key rotation

1. Freeze the intended role and affected issuer/key epoch.
2. Create signed trust registry generation `N+1`, with predecessor equal to the
   canonical digest of generation `N`.
3. Retain distinct-principal threshold signatures and publish the registry.
4. Publish a frontier binding the new generation, predecessor and registry
   digest through authenticated CAS.
5. Restart/canary one host; verify old-key evidence no longer satisfies a
   positive profile and new-key evidence does.
6. Roll out only after retained exact-candidate and operator receipts pass.

## Emergency revocation

1. Page security and the evidence owner.
2. Publish an `N+1` registry marking the affected epoch revoked.
3. Publish the matching external frontier and record the reason digest.
4. Stop any host that cannot authenticate latest registry/frontier state.
5. Add scoped evidence revocations where historical evidence must become
   inactive; do not mutate or delete the original rows.

## Unknown CAS result

1. Fence product writes.
2. Read authenticated latest from the independent backend.
3. If latest equals the proposed generation/digest, record the durable
   acknowledgement and continue.
4. If latest is the predecessor, retry with a fresh CAS request ID.
5. If latest is neither, preserve all objects and escalate as a split-brain
   incident. Never guess which write won.

## Backup publication

1. Acquire the exclusive backup writer fence; failure means another writer or
   backup is active.
2. Produce a transactionally consistent SQLite backup image.
3. Re-open it read-only and verify migrations, schema, canonical rows, foreign
   keys and the all-authoritative-table digest.
4. Hash the complete image and retain immutable object version plus storage
   ETag digest.
5. Publish the signed frontier and durable backup receipt with CAS.
6. Release the fence only after authenticated acknowledgement. Any ambiguous
   outcome remains `recovery_required`.

## Restore

1. Keep the target host stopped and acquire the exclusive owner and backup
   fences.
2. Fetch authenticated latest frontier, trust registry and immutable backup
   version from independent storage.
3. Verify threshold signatures, predecessor chain, source/tree/build pins,
   complete image digest, receipt digest and backend identity.
4. Restore into a new path; never overwrite the only retained predecessor.
5. Open read-only, recompute `recovery_state_v2`, and require exact equality.
6. Start one canary host. A valid but older image must be rejected.
7. Retain a signed drill/incident receipt; only authorized external operation
   may advance `backupRestoreDrilled`.

## Incident evidence

Preserve exact timestamps, source commit/tree, binary digest, trust/frontier
records, immutable object version, raw command logs and observed exit codes.
Redact secrets and payloads. Every corrective action references the incident ID
and predecessor generation.
"""
write("docs/lane-a-foundation/kernel.evidence/RUNBOOK.md", RUNBOOK)

ARCHIVE = r"""# kernel.evidence qualification archive contract V1

GitHub workflow artifacts are a transport cache, not the permanent audit store.
Every exact-source and deterministic-merge lane emits `archive-manifest.json`
with the exact candidate, workflow identity and SHA-256/byte count for every raw
record and log. The manifest explicitly records
`externalArchiveAcknowledged=false`; repository CI cannot self-assert external
retention.

The external archive must provide immutable object versions, authenticated
reads, retention lock for at least seven years or the governing evidence
horizon (whichever is longer), legal-hold support, independent access control,
and a signed durable acknowledgement binding repository/run/attempt/artifact,
manifest digest and object version. A mutable URL or GitHub artifact ID alone is
not an archive receipt.

Qualification artifacts are retained in GitHub for 365 days as a convenience.
Expiration, deletion, skipped upload or an unverified copy never becomes a
passing archive disposition. Promotion/release remains blocked until the
required external archive receipt is admitted by an independent principal.
"""
write("docs/lane-a-foundation/kernel.evidence/ARCHIVE_V1.md", ARCHIVE)

DRILLS = {
    "schema": "hepta.kernel-evidence-drill-status.v1",
    "schemaVersion": 1,
    "module": "kernel.evidence",
    "sourceFixtures": {
        "diskFull": "implemented_not_physical_acceptance",
        "multiProcessContention": "implemented_not_physical_acceptance",
        "casConflict": "implemented_not_physical_acceptance",
        "staleDatabase": "implemented_not_physical_acceptance",
    },
    "requiredExternalDrills": {
        "immutableObjectStoreCas": False,
        "crashBeforeCas": False,
        "crashAfterCasBeforeAck": False,
        "powerLossDuringBackup": False,
        "completeDatabaseReplacement": False,
        "restoreBehindRevocation": False,
        "signerRotationAndRevocation": False,
        "rpoRtoMeasured": False,
    },
    "backupRestoreDrilled": False,
    "authority": "external_operator_and_security_receipts_required",
}
write(
    "qualification/kernel-evidence/DRILL_STATUS.json",
    json.dumps(DRILLS, indent=2) + "\n",
)

ARCHIVE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "urn:hepta:kernel-evidence:archive-manifest:v1",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schemaVersion",
        "module",
        "lane",
        "repository",
        "workflowRunId",
        "workflowRunAttempt",
        "candidate",
        "files",
        "externalArchiveAcknowledged",
    ],
    "properties": {
        "schemaVersion": {"const": 1},
        "module": {"const": "kernel.evidence"},
        "lane": {"enum": ["source-head", "base-merge"]},
        "repository": {"type": "string", "minLength": 3},
        "workflowRunId": {"type": "string", "pattern": "^[1-9][0-9]*$"},
        "workflowRunAttempt": {"type": "string", "pattern": "^[1-9][0-9]*$"},
        "candidate": {"type": "object"},
        "files": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["path", "bytes", "sha256"],
                "properties": {
                    "path": {"type": "string", "pattern": "^[A-Za-z0-9._-]+$"},
                    "bytes": {"type": "integer", "minimum": 1},
                    "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                },
            },
        },
        "externalArchiveAcknowledged": {"const": False},
    },
}
write(
    "qualification/kernel-evidence/archive-manifest.schema.json",
    json.dumps(ARCHIVE_SCHEMA, indent=2) + "\n",
)

ARCHIVE_SCRIPT = r"""#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def positive_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value.isdigit() or int(value) <= 0:
        raise SystemExit(f"{name} must be a positive decimal integer")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--lane", choices=["source-head", "base-merge"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    candidate_path = args.records / "candidate.json"
    if not candidate_path.is_file():
        raise SystemExit("candidate.json is required before archive manifest generation")
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    files = []
    for item in sorted(args.records.iterdir(), key=lambda item: item.name):
        if item == args.output or not item.is_file() or item.is_symlink():
            continue
        stat = item.stat()
        if stat.st_nlink != 1 or stat.st_size <= 0:
            raise SystemExit(f"unsafe or empty archive input: {item}")
        files.append({"path": item.name, "bytes": stat.st_size, "sha256": sha256(item)})
    if not files:
        raise SystemExit("archive manifest would be empty")
    manifest = {
        "schemaVersion": 1,
        "module": "kernel.evidence",
        "lane": args.lane,
        "repository": os.environ.get("GITHUB_REPOSITORY", ""),
        "workflowRunId": positive_env("GITHUB_RUN_ID"),
        "workflowRunAttempt": positive_env("GITHUB_RUN_ATTEMPT"),
        "candidate": candidate,
        "files": files,
        "externalArchiveAcknowledged": False,
    }
    if "/" not in manifest["repository"]:
        raise SystemExit("GITHUB_REPOSITORY must be owner/repository")
    args.output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
"""
write("scripts/kernel_evidence_archive_manifest.py", ARCHIVE_SCRIPT)

ARCHIVE_TEST = r"""import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "kernel_evidence_archive_manifest.py"


class ArchiveManifestTests(unittest.TestCase):
    def test_manifest_binds_candidate_and_every_existing_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "candidate.json").write_text(
                json.dumps({"commit": "a" * 40, "tree": "b" * 40}), encoding="utf-8"
            )
            (root / "evidence-tests.json").write_text("{}\n", encoding="utf-8")
            output = root / "archive-manifest.json"
            env = dict(os.environ)
            env.update(
                GITHUB_REPOSITORY="example/repo",
                GITHUB_RUN_ID="123",
                GITHUB_RUN_ATTEMPT="2",
            )
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--records",
                    str(root),
                    "--lane",
                    "source-head",
                    "--output",
                    str(output),
                ],
                check=True,
                env=env,
            )
            manifest = json.loads(output.read_text(encoding="utf-8"))
            self.assertFalse(manifest["externalArchiveAcknowledged"])
            self.assertEqual(manifest["workflowRunId"], "123")
            self.assertEqual(
                {item["path"] for item in manifest["files"]},
                {"candidate.json", "evidence-tests.json"},
            )
            self.assertTrue(all(len(item["sha256"]) == 64 for item in manifest["files"]))

    def test_empty_or_missing_candidate_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ)
            env.update(
                GITHUB_REPOSITORY="example/repo",
                GITHUB_RUN_ID="123",
                GITHUB_RUN_ATTEMPT="1",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--records",
                    directory,
                    "--lane",
                    "source-head",
                    "--output",
                    str(Path(directory) / "archive-manifest.json"),
                ],
                env=env,
            )
            self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
"""
write("scripts/tests/test_kernel_evidence_archive_manifest.py", ARCHIVE_TEST)

# Extend artifact retention and generate per-lane manifests before upload.
workflow = " .github/workflows/hepta-kernel-evidence-qualification.yml".strip()
value = read(workflow)
value = value.replace("retention-days: 90", "retention-days: 365")
if "Build exact-source archive manifest" not in value:
    marker = "      - name: Retain exact-source receipts\n"
    step = """      - name: Build exact-source archive manifest
        shell: bash
        run: |
          python3 scripts/kernel_evidence_archive_manifest.py \\
            --records "$RUNNER_TEMP/kernel-evidence" \\
            --lane source-head \\
            --output "$RUNNER_TEMP/kernel-evidence/archive-manifest.json"

"""
    if marker not in value:
        raise SystemExit("exact-source artifact step marker drifted")
    value = value.replace(marker, step + marker, 1)
if "Build synthetic-merge archive manifest" not in value:
    marker = "      - name: Retain synthetic-merge receipts\n"
    step = """      - name: Build synthetic-merge archive manifest
        shell: bash
        run: |
          python3 scripts/kernel_evidence_archive_manifest.py \\
            --records "$RUNNER_TEMP/kernel-evidence" \\
            --lane base-merge \\
            --output "$RUNNER_TEMP/kernel-evidence/archive-manifest.json"

"""
    if marker not in value:
        raise SystemExit("merge artifact step marker drifted")
    value = value.replace(marker, step + marker, 1)
write(workflow, value)

convergence = ".github/workflows/hepta-kernel-evidence-convergence.yml"
if p(convergence).exists():
    write(
        convergence,
        read(convergence).replace("retention-days: 90", "retention-days: 365"),
    )

# Update status source but keep every operational/external gate false.
status_path = p("qualification/kernel-evidence/STATUS_SOURCE.json")
status = json.loads(status_path.read_text(encoding="utf-8"))
for source in [
    "docs/lane-a-foundation/kernel.evidence/ARCHIVE_V1.md",
    "docs/lane-a-foundation/kernel.evidence/OPERATIONS.md",
    "docs/lane-a-foundation/kernel.evidence/OPERATIONS_PROFILE_V1.json",
    "docs/lane-a-foundation/kernel.evidence/RUNBOOK.md",
    "qualification/kernel-evidence/DRILL_STATUS.json",
    "qualification/kernel-evidence/archive-manifest.schema.json",
    "scripts/kernel_evidence_archive_manifest.py",
    "scripts/kernel_evidence_phase3_operations.py",
    "scripts/tests/test_kernel_evidence_archive_manifest.py",
]:
    if source not in status["sourcePaths"]:
        status["sourcePaths"].append(source)
status["sourcePaths"] = sorted(status["sourcePaths"])
status["capabilities"].update(
    {
        "concreteOperationsProfile": True,
        "keyRotationRevocationRunbook": True,
        "unknownCasRestoreIncidentRunbook": True,
        "qualificationArchiveManifest": True,
        "qualificationArtifactRetention365Days": True,
        "externalDrillReceiptContract": True,
    }
)
for flag in [
    "exactSourceQualified",
    "mergeCandidateQualified",
    "independentAcceptance",
    "externalFrontierActive",
    "backupRestoreDrilled",
    "canaryAccepted",
    "releaseApproved",
]:
    status[flag] = False
status["workflowRunId"] = None
status["artifactDigest"] = None
status_path.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")

for name, section in {
    "docs/modules/kernel.evidence/TECHNICAL.md": """

## Production operations references

Concrete qualification targets and alert inventory are in [`OPERATIONS_PROFILE_V1.json`](../../lane-a-foundation/kernel.evidence/OPERATIONS_PROFILE_V1.json). Operator procedures are in [`RUNBOOK.md`](../../lane-a-foundation/kernel.evidence/RUNBOOK.md), and long-retention evidence requirements are in [`ARCHIVE_V1.md`](../../lane-a-foundation/kernel.evidence/ARCHIVE_V1.md). The workflow now emits a digest-bound archive manifest and retains its transport artifact for 365 days. External archival acknowledgement, physical drills, independent acceptance, canary and release remain separate false gates.
""",
    "docs/lane-a-foundation/kernel.evidence/CURRENT_IMPLEMENTATION.md": """

## Product and operations closure

The qualification lanes emit per-file archive manifests, use 365-day GitHub transport retention and publish concrete SLO/RPO/RTO, metrics, alert and incident procedures. Source fixtures cover disk-full, CAS conflict, stale database and multi-process contention. `DRILL_STATUS.json` deliberately keeps every physical object-store, power-loss, full-restore and measured RPO/RTO drill false until an external operator supplies retained evidence.
""",
    "qualification/kernel-evidence/TRACEABILITY.md": """

## Phase-three product and operations closure

- Paged query support is retained from the convergence source.
- `OPERATIONS_PROFILE_V1.json` defines concrete latency, availability, capacity, RPO/RTO and alert gates without claiming measurements.
- `RUNBOOK.md` covers rotation, emergency revocation, unknown CAS, backup, restore and incident evidence.
- Qualification lanes generate digest-bound archive manifests and retain GitHub transport artifacts for 365 days; permanent external archive acknowledgement is still required.
- `DRILL_STATUS.json` distinguishes source fault fixtures from real object-store, power-loss and restore drills; `backupRestoreDrilled` remains false.
- Independent acceptance can be verified and stored but cannot be self-issued by repository CI.
""",
}.items():
    value = read(name)
    heading = section.strip().splitlines()[0]
    if heading not in value:
        write(name, value.rstrip() + section + "\n")

print("phase-three operations closure applied; external gates preserved false")
