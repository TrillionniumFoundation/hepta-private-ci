# runtime.codex convergence — 2026-09-28

Branch: `work/runtime-codex-convergence-20260928`. Frozen main: `a126987b84737dbc2ee2592442a314117bddb4a2`.

This candidate combines the final server-owned fence changes from #1123 (`a11c9a68ca4c4510c64a6747959c4df903924a86`) with the compatible additions from #1124, #1125 and #1127 (stack tip `537950196b5d10258b9c9788a18ce6c7803575af`, shared predecessor `b21add8523459a51af141bd151872181b20e9700`). Existing branches and main are not rewritten. One-shot transport files are removed before the actual candidate is committed. Only normal source is qualified.

## Correctness and recovery

The exact non-idempotent Agentd `RunMarkDispatchedExact` CAS is an irreversible effect-entry fence. Abort is legal only while `ContextAttached`; a caller-supplied digest is NOT permission to undo `Dispatched`. The fresh ACK binds run, revision, generation, dispatch digest, context and compilation envelope. Unknown/idempotent/mismatched ACK never permits physical send. Cancellation and the anchored remaining deadline are checked again after the owner RPC. Post-fence stops retain capacity and history.

Owner fence and pre-effect abort compute the next revision before mutating fields. Overflow must not partially publish a digest or phase. The typestate vocabulary agrees: only `DurablePrepared` can abort, and `OwnerCommitted` already denotes a possible effect. This is partial typestate decomposition, not complete static enforcement of all cross-process invariants.

Definitive App Server rejection is durably prepared locally, then acknowledged by the Agentd owner, then releases local capacity. Restart resumes a pending rejection without resending. Standalone native runs without an intelligence-owner binding complete their local rejection without inventing an Agentd run. Ephemeral history is removed only after terminal/rejection persistence; possible effects retain it. Cleanup counters are bounded-process observations, not a durable orphan reaper.

## Security and clock

The Linux production authorizer configuration pins issuer PID, process start ticks, executable digest, cgroup digest and boot-ID digest. The connected peer is checked around the grant exchange. The production CLI fails closed without the expected process identity; test composition is explicitly different. These checks do not establish a trusted deployment, prevent every same-owner/namespace race, or replace external signer custody.

Native execution has one monotonic budget anchored to the wall time carried by the signed request, rejects sub-millisecond budgets and excessive backward wall-clock drift, and cannot regain time after an owner RPC. This is local clock discipline, not an authenticated time service.

The signed quarantine envelope verifier binds the original operation, request, dispatch, evidence, epoch, sequence and nonce. Original-operation replay remains prohibited. It is not yet a deployed durable resolution service, external anti-rollback frontier, or authenticated provider terminal oracle. Missing history therefore still retains the operation.

## Qualification contract

The old #1123 lane artifacts rejected every native command with `invalid tested_sha`: the workflow exported `HEPTA_CI_TESTED_SHA` while the executor reads `TESTED_SHA`. This candidate fixes the actual environment contract and tests real command execution against a clean temporary Git checkout. Prior signed failed receipts remain failures.

The focused source plan has twelve mandatory command records, including native binaries, adapter, durable control, Agent protocol, Agentd lifecycle, worker host, product E2E, model-only topology, crash model, quarantine protocol, strict lint and formatting. Source-head and deterministic ordered-parent base-merge remain independent and fail-fast is disabled. The existing protected `CI required` aggregate additionally depends on both runtime.codex lanes; this change does not alter repository branch protection or waive other required checks.

Candidate-code jobs have read-only repository permissions. Signing jobs receive only retained receipt bytes and do not execute candidate code. A provenance signature authenticates bytes and workflow identity; it does not turn a failed, missing, skipped or stale command into a pass. Every subsequent source or documentation commit requires new exact-candidate evidence.

## Fault and performance evidence boundaries

The inherited 22-cut test is an executable state model, not 22 physical process-kill experiments. Existing native journal child-process kill/reopen tests cover a narrower real-process set. New owner-CAS stress runs use multiple threads under the real owner mutex and assert one fresh winner, conflict on drift, retained capacity and no post-fence abort. Complete physical owner-RPC/partial-socket-write/App Server/provider fault coverage is still required.

The target-host workflow is restricted to the exact protected main candidate and a separately configured `runtime-codex-qualification` environment. It requires an independently installed issuer, provisioned fault harness and provider audit exporter. It is not automatically dispatched by this remediation. Candidate execution and attestation permissions are separated.

The target-host manifest verifier rejects duplicate keys, nonfinite values, boolean counters, zero digests and oversized/symlink files, and recomputes summaries from retained raw evidence. Re-sealing a changed p99 or deleting underlying records is rejected. A submitted `verified: true` field does not authenticate its producer: structural manifests explicitly report `authenticity: not-verified` and cannot assert real execution or independent acceptance. Independent producer verification is an outstanding integration requirement.

Empirical p50/p95/p99/RSS use 30–200 canary observations. Thirty samples are a collection floor, NOT a population p99 confidence guarantee. No real-provider latency or resource figures are claimed without the raw selected-host observations.

## Developer entry points

Read `README.md`, `QUICKSTART.md`, `DEPLOYMENT.md`, `TROUBLESHOOTING.md`, `ACCEPTANCE_CHECKLIST.md`, `CRASH_INJECTION_MATRIX.md` and `TARGET_HOST_FAULT_HARNESS.md`. This convergence note supersedes stale pre-fence descriptions in older remediation notes. The technical guide and source map point to this candidate's actual implementation.

Local verifier reproduction:

```sh
python3 -m unittest -v scripts.tests.test_runtime_codex_receipt_v2 scripts.tests.test_runtime_codex_target_host_evidence scripts.tests.test_runtime_codex_convergence
```

Native reproduction requires the pinned Rust toolchain, repository setup, verified V8 artifacts and a clean candidate checkout. Export full `SOURCE_SHA`, `TESTED_SHA` and `HEPTA_CI_LANE`; synthetic merge additionally requires `BASE_SHA` and exact ordered parents. From `codex-rs`, run `python3 ../scripts/runtime_codex_receipt_v2.py execute --records /absolute/path/outside/checkout/records`, then build and verify the receipt using the same script. A path or test source is not a pass receipt.

## Still requires actual evidence

Native exact-candidate results must be read from the completed run, not assumed from this document. The real selected host/filesystem, issuer key custody, authenticated clock/revocation distribution, process/socket/namespace identity, provider ACK-loss and restart behavior, durable quarantine application and anti-rollback, canary, rollback and independent acceptance remain distinct gates. No deployment, activation, promotion or release is authorized by this source candidate. Clearing journals, resetting revisions or switching request IDs is never a remedy for uncertainty.
