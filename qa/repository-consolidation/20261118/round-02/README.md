# Reviewed ordinary histories and required-CI repairs — round 02

**This is an integration checkpoint, not final main-merge qualification.** The
source merge is `35db0d7a7f73bf3f5c9757deb7e570bb52ee9890`, tree
`0b8a95d7b42a795a1b61612a9609407eeffa4424`. Its fourteen original ordinary
history parents are recorded in [source-merge-commit.json](source-merge-commit.json).

## Scope and preservation

The fresh advertisement has 7,490 names: 7,237 ordinary names, 252 protected
HIA/Cell names, and main. Another actor added three HCSN research names and
advanced one existing HCSN ref during the audit. Their complete parent chains
exclude both protected roots. They remain pending; no external advance was
overwritten. [Ancestry](ancestry.json), [advertisement manifest](branch-advertisement-manifest.json),
and [external changes](external-ref-changes.json) preserve this distinction.

The source merge represents 1,990 ordinary names, including 37 newly covered
names. There are 5,247 pending ordinary names and 1,825 independent frontier
heads. All 258 protected initial/current pins and both protected marker roots
are absent from its ancestry. Main remains
`732e934ba496d90fbe042b8d41d479ef901643e5`; no branch has been deleted.

## Source decisions

- **Fleet dispatch time:** use the verified dispatch witness's time for the
  allocation ledger, preserving the legacy caller argument for API compatibility.
  The restored regression proves that a caller cannot backdate an already expired
  allocation. It failed on the old code with an issued receipt, then passed on
  the repair. The full Fleet package passed 46 tests.
- **Metrics WAL:** combine exclusive creation and before/after file identity
  checks with the current Unix `O_NOFOLLOW`, mode 0600, owner lock, and locked
  link-count guard. Preserve both original and newer alias regressions. Six
  focused native tests pass. This does not establish Windows parent/path custody.
- **Supervisor recovery:** preserve independently signed production recovery and
  its quarantine. Reject the older unsigned digest-only auto-abort design. Restore
  the missing public exhausted-budget claim check, exact journal-byte invariance,
  and a second recovery without weakening the current typed event assertions.
- **Existing stronger implementations:** retain the current explicit Bazel YAML
  alias, unified rustix resolution, Windows WAL repair plus Unix hardening,
  localized V8 allocator initialization, and already formatted source. Each
  preserved path has its own reviewed historical delta and rationale; there is no
  blanket side-selection merge.
- **Missing regressions and historical evidence:** restore the rustix regression,
  bounded credit/MEM cross-mechanism cases, and complete dated MEM11 and V3 cost
  analysis packages. The V3 calculators were inspected and run on exact frozen
  inputs; all three outputs match the originals byte-for-byte. This validates
  recorded arithmetic, not new training or scientific acceptance. The MEM11
  historical source commit cannot be found in the complete graph or by the GitHub
  commit API (422); its internally matching source pins are not independently
  verified against that missing commit.
- **Diagnostic CI topology:** the old metrics-specific automatic workflow is
  explicitly retired under the existing aggregate/deep-qualification contract.
  Its exact original bytes remain in the merged parent history. No new automatic
  native result is inferred from that decision.

The five single-head batches are [01](reviewed-batch-01.json),
[02](reviewed-batch-02.json), [03](reviewed-batch-03.json),
[04](reviewed-batch-04.json), and [05](reviewed-batch-05.json). The multi-commit
reviews are [Fleet/metrics and related paths](fdd-full-source-review.json),
[the second metrics history](metrics-family-review.json), and
[MEM11 evidence](mem11-evidence-review.json). Baseline blob identities in those
proposals refer to `6ffe9e1`; the final merge also composes the other reviewed
changes described here.

## Required-CI repairs and validation

| Area | Observed result | Limit |
| --- | --- | --- |
| HNMF fuzz harness | Explicit calls for 12 HNMF protocols plus the write receipt; verifier, self-test, development-docs gate and locked fuzz compilation pass | Original decode/re-encode/equality assertions and gate files unchanged; isolated fuzz lock is temporary and untracked |
| Agentd material helper lint | Three missing-host unwraps now propagate contextual errors | All scenarios and deadlines retained; current native Agentd acceptance remains unresolved |
| Four other canonical consumers | Four original integration tests pass; scoped `just fix` passes | Memory retrieval, cognitive read/store, compact engine; all schema/contract/flow and adapter assertions retained |
| Fleet | 46 passed, zero skipped | Linux native only; old-code regression failure also retained |
| Metrics WAL | 6 passed; 369 outside-filter tests not run in this focused invocation | Complete Neuron qualification is not claimed |
| Supervisor recovery | Exhausted-budget test 1 passed; signed-intent recovery 3 passed | Same-process recovery fixtures retain their stated limits |
| Scoped Clippy | Fleet, Supervisor and Neuron `just fix --locked --offline` exit 0 | No automatic source edits observed |
| B4 source rules | All 160 modules, 1,345 tests, zero failures or skips; checkout unchanged | Every module ran in its own Python process against fixed tree `c46d97b1e6acb237035c715f904d3e591f0a553b`; the four consumer error-style fixes followed this snapshot |
| Development document gate | `PASS_HEPTA_DEVELOPMENT_DOCS_V8` on that fixed source | Historical evidence and lease activation are explicitly not requalified by this profile |
| Caller closed-set verifier | Previous checkpoint passed; rerun for changed Fleet/metrics source started separately | Do not infer a new-source pass before its terminal receipt |

The B4 [summary](validation/b4-all-modules-summary.json) and complete log/receipt
[archive manifest](validation/b4-all-modules-manifest.json) bind every result to
the immutable source snapshot. The earlier interrupted run remains labelled as
interrupted; it was not relabelled as successful. All validation files are listed
with lengths and hashes in [artifact-manifest.json](artifact-manifest.json).

Full Neuron qualification first exposed eight missing real-helper metadata
errors in the unmodified baseline. Attempts to prepare the actual compiler-bound
helper then encountered a missing C include path, a later rustc SIGKILL, and a
third explicitly cancelled resource-limited attempt. No substitute helper was
used. See the complete [helper receipt](validation/neuron-helper-gate-receipt.json).

The isolated ROG Agentd/worker build did not produce a successful native result.
Its partial log ends in a linker failure; the exact owned systemd-unit journal
records disk exhaustion while the supervisor attempted to publish its terminal
receipt. The empty receipt and later free-space observation are not success
evidence. Original logs and the diagnostic result are retained.

## Remaining blockers

The hosted `6ffe9e1` run still fails. The captured jobs establish the HNMF and
fixture lint defects repaired here, but also Agentd timeout/next-use evidence
failure, Windows peer authentication refusal, unqualified elevated Windows
sandbox boundaries, a Windows scope-WAL test failure, and other Core/TUI and
process regressions. New candidate platform results are required.

Cargo-deny 0.19.0 was reproduced with unchanged policy and lockfiles. Its only
error is the RustSec `RUSTSEC-2026-0543` unmaintained-chrono advisory; bans,
licenses and sources pass. The official advisory lists no patched version.
Migration is being reviewed separately; this checkpoint adds no advisory ignore,
security exception or dependency substitution. The complete 13,687,000-byte
diagnostic is preserved in ordered gzip parts with a full restoration hash.

The existing required `CI required` and `Architecture required` gates remain in
force. Focused local successes do not authorize merging a red candidate into
main, deleting unintegrated refs, or treating unresolved review/security findings
as resolved.
