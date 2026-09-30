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


def append_once(path: str, marker: str, block: str) -> None:
    text = read(path)
    if marker in text:
        return
    write(path, text.rstrip() + "\n\n" + block.strip() + "\n")


DOC = "docs/modules/prompt.registry"

write(f"{DOC}/THREAT_MODEL.md", r'''
# prompt.registry threat model

Document schema version: `1`  
Identity binding: the exact `documentation_hash`, `implementation_map_hash`,
`source_tree_hash`, workflow identity and artifact hashes are emitted by
`hepta.prompt-registry.readiness-manifest.v1`. This document does not carry a
mutable handwritten `asOfCommit` value.

## Security objective

A prompt factor or realization may affect a provider request only while its
exact identity, owner, admission, lifecycle, context, model/tool binding,
deadline, storage generation and transport generation remain current. Revoked,
retired, stale-owner, replayed, corrupted, or ambiguously committed material
must fail closed without granting retry or activation authority.

## Protected assets

- factor text and realization payload bytes;
- lifecycle, relation, supersession and revocation history;
- current owner and checkpoint authority;
- exact provider request and output-event bindings;
- qualification receipts and readiness manifests;
- source, backup, checkpoint and payload-extent disposal evidence.

## Trust boundaries

1. `DurablePromptRegistry` is the single local writer and durable lifecycle
   authority. A successful in-memory return is not a substitute for publication
   and reopen reconciliation.
2. Agentd owns compilation, final-use validation and durable dispatch claims.
3. Core owns the physical provider stream and invokes the policy lease before
   every event becomes visible to downstream consumers.
4. Optimizer consumes read-only graph/snapshot evidence and receives no write or
   effect authority.
5. Deployment controllers own external owner fencing, checkpoint activation,
   backup disposal and provider-side cancellation semantics.
6. CI proves only the exact repository candidate and never activates production.

## Threats and required controls

| Threat | Control | Proof location |
| --- | --- | --- |
| Cached attachment reused after revoke | host preparation is repeated at provider begin and before every output event | `ext/hepta-prompt`, product required tests |
| Output replay/reordering | strictly monotonic per-attempt event sequence | `provider_output_sequence_replay_fails_closed` |
| Mid-stream revoke leaks later output | authorization error terminates Core stream task and records indeterminate terminal state | Core client marker plus before-first/mid-stream tests |
| Old owner resumes after handoff | exact `AuthorityFenceV1` match; successor must advance owner, epoch, storage and transport generation | `governance.rs` |
| Checkpoint accepted while old transport remains live | deployment must bind checkpoint activation and transport generation to one fence transaction | `RETENTION_AND_FENCING.md` |
| Logical GC misrepresented as secure erasure | independent physical-disposal state is explicit; only `IndependentlyVerified` means external proof | `governance.rs` |
| Digest substitution or tokenizer/template drift | source binding includes model, context, payload, fragment and provider request digests | API contract and extension tests |
| Evidence replay or cross-attempt mixing | all four required lanes share source/base/run/attempt and artifact digests | aggregate script |
| Workflow artifact substitution | every receipt, raw log and artifact is hashed and revalidated | qualification summary |
| Corrupt or torn durable state grants retry | integrity/uncertain-commit failures poison authority and require reopen/reconciliation | durable failure tests |
| Logs disclose prompt/provider secrets | policy seams expose stable IDs and digests only; error detail is bounded and secret-free | extension API and failure contract |

## Residual and external risks

Repository proof does not show that a remote provider stopped computation after
its HTTP request was accepted, that bytes already observed by an external
consumer can be recalled, or that a target storage device physically erased old
blocks. Those claims require target-host/provider evidence and independent
acceptance. Consequently `productionReady`, `productActivated`, `accepted` and
`released` remain false in repository qualification output.
''')

write(f"{DOC}/MIGRATIONS.md", r'''
# prompt.registry persistent migration contract

Document schema version: `1`  
Identity binding: `migration_hash` in the readiness manifest covers this file and
all named migration/storage source files.

## Supported compatibility matrix

| From | To | Open/read | Automatic rewrite | Rollback | Payload risk | Minimum reader |
| --- | --- | --- | --- | --- | --- | --- |
| V2 semantic snapshot | V4 durable metadata | compatibility read/import only | no implicit authority activation | source retained until verified checkpoint | imported payload must be rebound and validated | V4-aware owner |
| V4 metadata with inline/legacy payload representation | V5 payload generation | strict reopen plus validated payload generation | only through explicit owner transaction | rollback only to retained, exact V4 source; no mixed writer versions | uncertain publication poisons and reconciles | V5 owner |
| V5 generation N | V5 generation N+1 | exact generation and digest validation | explicit publication | old generation may be retained only under policy and fence | stale generations cannot authorize current use | V5 owner |

## Rules

- A reader may inspect compatible evidence but must not silently become writer or
  owner.
- A writer must use one active storage schema and one payload generation for a
  transaction.
- Unknown fields, unsupported schema versions, identity mismatch and partial
  publication fail closed.
- Migration completion requires reopen, exact revision/digest comparison and a
  durable checkpoint receipt. Copying files is not activation.
- Rollback never revives revoked material. Revocation/lifecycle frontiers must be
  at least as strong as the source state.
- `AuthorityFenceV1` must advance for cross-owner activation. A stale process may
  read diagnostics but cannot write, dispatch or release output.

## Evidence invalidation

Any change to V2/V4/V5 codecs, durable I/O, payload generation, governance types,
this matrix, or migration tests changes `migration_hash` and invalidates prior
readiness manifests.
''')

write(f"{DOC}/READINESS_MANIFEST.md", r'''
# prompt.registry single-candidate readiness manifest

Document schema version: `1`

The only repository-controlled merge-readiness fact is
`hepta.prompt-registry.readiness-manifest.v1`, embedded in the four-lane
qualification summary. Human prose and individual workflow badges are not
qualification facts.

## Required identity fields

```text
source_head_sha
base_sha
deterministic_merge_sha
github_merge_sha
workflow_sha
final_merge_sha
workflow_run_id
workflow_attempt
runner_image
target_triple
Cargo.lock_hash
migration_hash
test_set_hash
qualification_profile_hash
implementation_map_hash
documentation_hash
source_tree_hash
artifact_hashes
required_lanes
```

`final_merge_sha` is null before an actual protected merge. `github_merge_sha`
is the workflow event identity and is not interchangeable with the deterministic
base merge. All per-lane maps preserve their own runner, target, test-set and
artifact identity.

## Fail-closed rule

Exactly four lanes are required:

- `core/exact-head`;
- `product/exact-head`;
- `core/base-merge`;
- `product/base-merge`.

A missing, skipped, cancelled, interrupted, failed, cross-run, cross-attempt or
identity-mismatched lane yields:

```text
productionQualified = false
mergeReady = false
productionReady = false
```

A successful four-lane summary may set repository-controlled
`productionQualified=true` and `mergeReady=true`; it still keeps
`productionReady=false`, `productActivated=false`, `accepted=false` and
`released=false` until external and operator gates are satisfied.

## Immutability

Qualification is read-only. It may download dependencies during a bounded prime
step, but it never changes source, regenerates maps, commits, pushes, activates,
or joins green results from another workflow attempt.
''')

write(f"{DOC}/RETENTION_AND_FENCING.md", r'''
# prompt.registry retention and external fencing

Document schema version: `1`

## Versioned retention policy

`RetentionPolicyV1` defines minimum ages for revoked payloads, retired payloads,
audit metadata and tombstones, plus checkpoint confirmations and whether secure
disposal evidence is mandatory. Its canonical digest is stored with each
`RetentionDecisionV1`.

A persisted decision contains:

```text
policy_version
policy_digest
decision_wall_time_ms
decision_monotonic_epoch
eligible_since_ms
last_gc_attempt_ms
last_gc_failure
physical_disposal_state
```

The physical states are intentionally distinct:

1. `logical_use_fenced`;
2. `payload_extent_released`;
3. `backup_released`;
4. `checkpoint_confirmed`;
5. `independently_verified`.

Only the final state is external physical-erasure proof. Local unlink, compaction
or a false `source_erased` flag must never be promoted automatically.

## Authority fence

Every deployment-owned write, checkpoint activation, provider dispatch and
output completion must present the exact current `AuthorityFenceV1`:

```text
version
authority_epoch
owner_instance_id
checkpoint_sequence
handoff_nonce
storage_generation
transport_generation
```

A successor must use a different owner and nonce and strictly advance authority,
storage and transport generations. Restarting an old process cannot make its
fence current.

## Integration transaction

A deployment handoff should perform, atomically from the controller's point of
view:

1. quiesce current dispatch and output release;
2. produce and verify checkpoint identity;
3. allocate successor owner/nonce and advance generations;
4. publish the new fence to storage and provider controllers;
5. activate the successor;
6. prove the old owner cannot write or release output;
7. apply retention/disposal policy to source, slots, backups and extents;
8. record independent disposal evidence when required.

The repository supplies validated types and local fail-closed behavior. The
deployment state store and provider controller remain external acceptance gates.
''')

write(f"{DOC}/FAULT_INJECTION.md", r'''
# prompt.registry fault-injection qualification

Document schema version: `1`

## Matrix

| Boundary | Repository fault | Target-device fault | Required invariant |
| --- | --- | --- | --- |
| before payload write | process exit, capacity rejection | disk full/inode exhaustion | no admitted mutation |
| payload written, metadata not published | process exit, short/failed write | power loss | orphan bytes grant no authority |
| metadata written, rename not complete | injected sync/publication failure | torn metadata/file fsync failure | reopen chooses only valid image |
| rename complete, directory sync incomplete | uncertain commit | directory persistence loss | poison then reconcile; no blind retry |
| checkpoint publication | old-owner restart | network partition/controller rollback | stale fence cannot activate/write |
| GC marked, physical cleanup pending | restart | delayed/unavailable device cleanup | logical use remains fenced; cleanup resumes |
| physical cleanup done, state commit uncertain | uncertain commit | power loss | disposal is not overclaimed; reconcile first |

`scripts/hepta-prompt-registry-fault-matrix.py --execute-repository` runs the
repository-owned process/publication regressions. Power-loss, filesystem,
permission, device-corruption and deployment-controller cases must run on each
target filesystem and attach their artifact digest to external acceptance.

## Target filesystems

At minimum qualify the production filesystem/mount options and one recovery
configuration. Record kernel, filesystem, mount flags, storage class, cache and
flush semantics. A GitHub-hosted runner is not target-device evidence.
''')

write(f"{DOC}/SOAK_TESTING.md", r'''
# prompt.registry mixed-workload soak qualification

Document schema version: `1`

## Required workload

Run for 30–60 minutes with a deterministic seed and a bounded mix of register,
admit, lease/current-use validation, dispatch, retire, revoke, GC, checkpoint,
reopen and read-only optimizer operations. Exercise 1k, 8k and 16,384 logical
record scales and payload occupancy near the configured ceiling.

## Required measurements

- operation count and error taxonomy by operation;
- p50/p95/p99 latency and maximum latency;
- writer lock wait and hold time;
- bytes cloned/serialized/hashed and physical write amplification;
- GC pause, reclaimed bytes and cleanup-pending age;
- checkpoint duration and reopen/reconciliation duration;
- oldest pending/reclaimable age when a persisted policy is configured;
- starvation/fairness across Agentd readers;
- peak RSS and metadata/payload file growth.

## Pass criteria

No invariant violation, unauthorized retry, revocation resurrection, stale fence
acceptance, unbounded growth, starvation or missing terminal record is allowed.
Performance thresholds are deployment-profile inputs and must be recorded in the
artifact; they must not be silently inferred from the small 31-sample benchmark.

`scripts/hepta-prompt-registry-soak.py` provides the reproducible repository
harness. The operational qualification workflow is read-only and uploads its raw
logs and summary. Results from different source SHA, runner image, target triple
or profile cannot be combined.
''')

append_once(f"{DOC}/ACCEPTANCE.md", "## Acceptance authority and evidence validity", r'''
## Acceptance authority and evidence validity

### Roles

- **source owner** freezes the exact candidate and verifies no CI source writer
  exists on the candidate branch;
- **qualification owner** reviews the four-lane readiness manifest and raw
  artifacts;
- **security/semantic reviewer** independently reviews lifecycle, failure,
  output-fence, migration and data-disposal semantics;
- **deployment owner** qualifies target storage, provider cancellation, external
  fencing and rollback;
- **operator/release authority** alone may activate or release.

No role may infer another role's approval from a green workflow.

### Gate contract

Each gate names exact inputs, outputs and failure conditions. Repository
qualification requires the single-candidate manifest described in
`READINESS_MANIFEST.md`; target-host acceptance additionally requires device
fault artifacts, a mixed-workload soak, authority-fence handoff evidence,
retention/disposal evidence and a rollback rehearsal.

### Activation and rollback

Activation must pin the final merge SHA, implementation/document/migration
hashes, active storage schema, owner instance, checkpoint identity and storage /
transport generations. Rollback must quiesce dispatch/output, advance the fence,
select a verified non-stale checkpoint and prove that revoked identities remain
revoked. A rollback to an older source or checkpoint does not authorize
resurrection.

### Emergency revoke

Emergency revoke must be durable before new dispatch and is revalidated before
every output event. Existing local streams terminate on authorization error and
record an indeterminate terminal result. Remote computation or already observed
bytes require provider/deployment handling and cannot be recalled by the
registry.

### Evidence lifetime

Any source, Cargo.lock, workflow, test set, migration, implementation map,
document, runner profile or artifact change invalidates the old readiness
manifest. Target-host evidence also expires when kernel/filesystem/storage class,
provider transport, controller, KMS/HSM/WORM configuration or deployment policy
changes.
''')

append_once(f"{DOC}/API_CONTRACT.md", "## Per-event provider output currentness", r'''
## Per-event provider output currentness

A successful durable dispatch claim is not a perpetual output capability. Core
presents a secret-free `ModelProviderOutputBatch` to the attempt lease before
every provider event is exposed downstream. The prompt runtime lease:

1. validates a strictly monotonic event sequence;
2. re-runs owner preparation/current-use validation;
3. requires the exact original attachment binding;
4. checks the deadline;
5. returns `Allow` only for that event.

Revocation, removal, identity drift, expiry, replay or sequence gap returns a
stable error. Core records an indeterminate terminal state and terminates the
local stream task; later events and final completion cannot pass the release
boundary. This proves local transport/stream/output fencing, not remote rollback
or recall of bytes already observed.
''')

append_once(f"{DOC}/OPERATIONS.md", "## Versioned retention, fencing and device qualification", r'''
## Versioned retention, fencing and device qualification

Use `RetentionPolicyV1` and `RetentionDecisionV1` for auditable age/disposal
policy and `AuthorityFenceV1` for external owner, checkpoint, storage and
transport generations. Persist these values in the deployment authority store;
constructing them in process grants no authority.

`oldest_reclaimable_age_ms=None` remains truthful when no durable enqueue time
and policy decision exist. Never translate unknown to zero. Local GC, checkpoint
copy or unlink does not establish independent physical erasure.

Before activation execute `FAULT_INJECTION.md`, `SOAK_TESTING.md`, a fence
handoff/restart drill and a restore/rollback drill on the target filesystem and
provider controller. Attach exact artifacts to the acceptance record.
''')

append_once(f"{DOC}/PERFORMANCE.md", "## Long-duration mixed workload", r'''
## Long-duration mixed workload

The 31-sample micro/profiles are regression guards, not capacity commitments.
Production qualification additionally requires the 30–60 minute protocol in
`SOAK_TESTING.md`, including lock wait/hold time, write amplification, GC pause,
reopen duration, fairness, RSS and file-growth evidence. Introduce WAL,
segmentation, incremental hashing or background compaction only after this data
identifies a sustained bottleneck and the recovery proof is updated.
''')

append_once(f"{DOC}/ARCHITECTURE.md", "## Physical provider output fence", r'''
## Physical provider output fence

```text
DurablePromptRegistry current identity
  -> Agentd final-use lease and durable dispatch claim
  -> hepta-prompt attempt lease
  -> Core provider transport
  -> authorize_output(sequence, event_digest, encoded_bytes)
  -> downstream stream/final output
```

Every arrow after the durable claim remains conditional. The attempt lease
revalidates current ownership and exact attachment identity before each event.
An authorization error terminates the local stream and prevents final completion
from being reported as delivered.
''')

append_once(f"{DOC}/TECHNICAL.md", "## Detailed closeout documents", r'''
## Detailed closeout documents

- `READINESS_MANIFEST.md`: unique candidate/run/attempt and fail-closed merge fact;
- `THREAT_MODEL.md`: assets, trust boundaries, attacks and residual risks;
- `MIGRATIONS.md`: V2/V4/V5 compatibility and rollback rules;
- `RETENTION_AND_FENCING.md`: policy/disposal states and external generations;
- `FAULT_INJECTION.md`: process, filesystem, power-loss and controller matrix;
- `SOAK_TESTING.md`: 30–60 minute mixed-workload protocol;
- `ACCEPTANCE.md`: roles, gates, activation, rollback and evidence lifetime.

All documents are bound by `documentation_hash`; migration-specific source and
documents are additionally bound by `migration_hash`.
''')

FAULT_SCRIPT = r'''#!/usr/bin/env python3
"""Emit or execute the repository-owned prompt.registry fault matrix."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
CARGO = ROOT / "codex-rs"
CASES = [
    {
        "id": "payload-publication-unknown",
        "boundary": "physical cleanup or payload publication before acknowledged state",
        "test": "gc_indeterminate_publication_poison_preserves_both_slots_until_reopen",
        "external": False,
    },
    {
        "id": "process-exit-after-unknown-commit",
        "boundary": "unknown commit followed by process restart",
        "test": "gc_process_exit_after_unknown_commit_reconciles",
        "external": False,
    },
    {
        "id": "checkpoint-conflict",
        "boundary": "partial/conflicting checkpoint destination",
        "test": "operational_compaction_retry_is_idempotent_and_conflicting_destination_is_untouched",
        "external": False,
    },
    {
        "id": "stale-restore-after-revoke",
        "boundary": "restore candidate behind revocation frontier",
        "test": "operational_stale_restore_is_rejected_after_revocation",
        "external": False,
    },
    {"id": "power-loss", "boundary": "device power loss at every publication phase", "test": None, "external": True},
    {"id": "disk-inode-permission", "boundary": "disk full, inode exhaustion and permission drift", "test": None, "external": True},
    {"id": "device-corruption", "boundary": "metadata/payload corruption and flush mismatch", "test": None, "external": True},
    {"id": "owner-controller-partition", "boundary": "old owner recovery during checkpoint handoff", "test": None, "external": True},
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-repository", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = {"schema": "hepta.prompt-registry.fault-matrix.v1", "cases": []}
    for case in CASES:
        row = dict(case)
        row.update({"executed": False, "passed": False, "durationSeconds": None})
        if args.execute_repository and not case["external"]:
            started = time.monotonic()
            completed = subprocess.run(
                ["cargo", "test", "--locked", "--offline", "-p", "codex-hepta-prompt-registry", case["test"], "--", "--exact", "--nocapture", "--test-threads=1"],
                cwd=CARGO,
                check=False,
            )
            row.update({
                "executed": True,
                "passed": completed.returncode == 0,
                "exitCode": completed.returncode,
                "durationSeconds": time.monotonic() - started,
            })
        result["cases"].append(row)
    result["repositoryCasesPassed"] = all(
        row["passed"] for row in result["cases"] if not row["external"]
    ) if args.execute_repository else False
    result["externalCasesRequired"] = [row["id"] for row in result["cases"] if row["external"]]
    text = json.dumps(result, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    if args.execute_repository and not result["repositoryCasesPassed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
'''
write("scripts/hepta-prompt-registry-fault-matrix.py", FAULT_SCRIPT)

SOAK_SCRIPT = r'''#!/usr/bin/env python3
"""Run a bounded, source-bound prompt.registry mixed regression soak."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
CARGO = ROOT / "codex-rs"
COMMANDS = [
    ["cargo", "test", "--locked", "--offline", "-p", "codex-hepta-prompt-registry", "gc_reclaims_inactive_raw_bytes_but_preserves_audit_and_revocation_after_restart", "--", "--exact", "--test-threads=1"],
    ["cargo", "test", "--locked", "--offline", "-p", "codex-hepta-prompt-registry", "operational_compaction_retry_is_idempotent_and_conflicting_destination_is_untouched", "--", "--exact", "--test-threads=1"],
    ["cargo", "test", "--locked", "--offline", "-p", "codex-hepta-prompt-extension", "provider_output_revocation_after_first_event_fails_closed", "--", "--exact", "--test-threads=1"],
    ["cargo", "test", "--locked", "--offline", "-p", "codex-hepta-agentd", "prompt_", "--", "--test-threads=1"],
]


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-seconds", type=int, default=3600)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.duration_seconds < 30 or args.duration_seconds > 7200:
        raise SystemExit("duration must be between 30 and 7200 seconds")
    started = time.monotonic()
    iterations = []
    index = 0
    while time.monotonic() - started < args.duration_seconds:
        command = COMMANDS[index % len(COMMANDS)]
        command_started = time.monotonic()
        completed = subprocess.run(command, cwd=CARGO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
        payload = completed.stdout.encode()
        row = {
            "iteration": index + 1,
            "command": command,
            "exitCode": completed.returncode,
            "durationSeconds": time.monotonic() - command_started,
            "logSha256": hashlib.sha256(payload).hexdigest(),
        }
        iterations.append(row)
        log = args.output.parent / f"soak-{index + 1:05d}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_bytes(payload)
        if completed.returncode != 0:
            break
        index += 1
    result = {
        "schema": "hepta.prompt-registry.mixed-soak.v1",
        "candidateSha": git("rev-parse", "HEAD"),
        "sourceTreeHash": git("rev-parse", "HEAD^{tree}"),
        "requestedDurationSeconds": args.duration_seconds,
        "actualDurationSeconds": time.monotonic() - started,
        "iterations": iterations,
        "passed": bool(iterations) and all(row["exitCode"] == 0 for row in iterations),
        "scope": "repository mixed regression soak; target-host lock/write-amplification instrumentation remains an activation gate",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
'''
write("scripts/hepta-prompt-registry-soak.py", SOAK_SCRIPT)

WORKFLOW = r'''name: prompt.registry operational qualification

on:
  workflow_dispatch:
    inputs:
      duration_seconds:
        description: Mixed-workload soak duration (30-7200 seconds)
        required: true
        default: "3600"
  schedule:
    - cron: "17 3 * * 6"

permissions:
  contents: read

concurrency:
  group: prompt-registry-operational-${{ github.ref }}
  cancel-in-progress: false

jobs:
  fault-and-soak:
    runs-on: ubuntu-24.04
    timeout-minutes: 150
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 1
          persist-credentials: false
      - uses: dtolnay/rust-toolchain@stable
        with:
          toolchain: 1.90.0
          components: rustfmt,clippy
      - name: Prime dependencies
        working-directory: codex-rs
        run: cargo test --locked -p codex-hepta-prompt-registry -p codex-hepta-prompt-extension -p codex-hepta-agentd --no-run
      - name: Repository fault matrix
        env:
          CARGO_NET_OFFLINE: "true"
        run: python3 scripts/hepta-prompt-registry-fault-matrix.py --execute-repository --output "$RUNNER_TEMP/fault-matrix.json"
      - name: Mixed workload soak
        env:
          CARGO_NET_OFFLINE: "true"
          DURATION: ${{ github.event.inputs.duration_seconds || '3600' }}
        run: python3 scripts/hepta-prompt-registry-soak.py --duration-seconds "$DURATION" --output "$RUNNER_TEMP/soak/summary.json"
      - name: Upload source-bound operational evidence
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: prompt-registry-operational-${{ github.sha }}-${{ github.run_id }}-${{ github.run_attempt }}
          path: |
            ${{ runner.temp }}/fault-matrix.json
            ${{ runner.temp }}/soak
          if-no-files-found: error
          retention-days: 30
'''
write(".github/workflows/hepta-prompt-registry-operational-qualification.yml", WORKFLOW)

print("prompt.registry docs and operational closeout patch applied")
