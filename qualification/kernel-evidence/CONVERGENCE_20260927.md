# kernel.evidence convergence execution note — 2026-09-27

## Scope and provenance

This change set is on `codex/kernel-evidence-converged-20260927`, PR #1081,
based on the existing production-closure implementation in PR #1009 at
`d35c5ebb6af739eeb9106cfd24fd89c69281efa1`. It does not modify the original
#1009 or #1050 branches or any unrelated module branch. Main has not been
merged or declared qualified by this work.

The canonical source anchor is `38e54289c0cbe0177769b4ccaaadcdf90d85ac0d`, tree
`ac7aa53cca04f1b41155a61786c3c7b2926b3cc0`. Documentation/status changes are a
separate commit, avoiding the impossible requirement that a file contain its
own commit identity. Exact-source and deterministic-merge execution receipts
must still bind the final checked-out candidate, not merely this source anchor.

## Existing implementation retained and reviewed

The base supplies frontier v2, the latest/CAS/history/backend-identity trait,
locked external-file backend, immutable local acceptance, Agentd fail-closed
production admission, threshold signer policy, SQLite runtime authorizer,
denial triggers, cursor paging, fault/multiprocess fixtures and the canonical
status projector. These are inherited capabilities, not all newly authored in
this convergence pass. A different device and a private directory are necessary
checks for the selected file adapter, not proof of an independent physical
rollback domain or arbitrary network-filesystem durability.

## Convergence fixes

1. Add a direct qualification/regression workflow without PR path filters.
   Reject empty or skipped Python suites. Keep exact tracked source and partial
   diagnostics even on failure. Expose `Kernel evidence convergence required`.
2. Isolate reusable workflow concurrency by caller name. Initialize diagnostics
   before setup/merge operations; require at least one observed passing test in
   each Rust test command. Final artifact-bearing false qualification exits
   nonzero while retaining failed diagnostics.
3. Restrict external history range construction and add accessors, a compile-fail
   API test, inclusive-limit tests and overflow/boundary cases.
4. Bind each execution record to its exact command, clean Git identity,
   workflow run/attempt/job and retained raw log. Reject duplicate JSON keys,
   non-finite values, boolean/float success codes, unsafe paths, symlinks,
   hard links, file replacement, missing test execution and log substitution.
5. Recompute synthetic merge trees; bind retained artifact metadata to the exact
   repository/run/id; distinguish pre-upload diagnostics from final retained
   qualification; synchronize the canonical source and all five status views.

## Executed verification and limits

The two newly added Python suites were executed locally with:

```sh
python -m unittest discover -s /mnt/data/evidence-convergence/scripts/tests \
  -p 'test_kernel_evidence*.py' -v
```

Result: **42 tests passed**, no failures or errors. This local directory held
the four new/revised Python implementation/test files, not a full checkout.
It therefore does not claim that the six pre-existing canonical-status tests,
all repository validators, Rust tests or production integration tests ran.

The revised reusable workflow also passed local YAML parsing and structural
assertions for job inventory, caller-specific concurrency, minimum-test checks
and final qualification enforcement. No local Rust compiler, rustfmt or full
repository build was available. The added Rust unit and compile-fail tests
remain subject to the final remote qualification runs.

GitHub Actions were triggered by pushed commits and the draft PR. No successful
final source/merge receipt or artifact digest had been obtained when this note
was committed. All persistent qualification and external gates remain false;
workflowRunId and artifactDigest remain null rather than borrowing a prior
candidate's results.

## Unresolved gates

- Finish exact-source, deterministic-merge, general CI and architecture checks
  on the final candidate; diagnose any failures without weakening security
  assertions. Do not merge on pending, skipped or cancelled checks.
- Configure server-side branch protection. The active integration returned
  HTTP 403 `Resource not accessible by integration` on the required-status-check
  protection endpoint. Writing a workflow is not the same as enforcing it.
  An administrator must preserve existing requirements and require the stable
  convergence fan-in after validating its final check context.
- Provision and qualify independently retained external storage, its owner and
  signer/key-rotation policy, authenticated access and durable backup publisher.
- Obtain witnessed stale-DB/frontier/trust rollback rejection, backup/restore,
  power-loss and storage-failure drills on the actual platform. Source fault
  fixtures and a bounded contention test do not establish those operations.
- Measure capacity, p95/p99 contention latency, growth, RPO and RTO. Complete
  independent acceptance, canary and release through distinct authorities.

The file adapter's bounded mutation and contention fixtures are not a claim of
an exhaustive long-running fuzz campaign or of safety on every filesystem.
Those validation dimensions remain explicit operational qualification work.

## Status discipline

`STATUS_SOURCE.json` is the persistent source of truth. Its sourcePaths include
the new workflow, validator and tests. The technical guide, current
implementation, traceability matrix, execution dossier and release dashboard
share the same generated block and canonical digest. Capabilities describe
source presence; only retained exact-candidate evidence may advance execution
or operational gates. This note cannot grant independent acceptance or release.
