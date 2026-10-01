# cognitive.read adversarial audit and completion review

Audit baseline: production-convergence branch `work/cognitive-read-production-convergence-20260927`, commit `8a2f9256102a7bf36fbab4f22152573ba8fb91ad` (2026-09-30). This is newer than main and the separately named development branch. Revised exact source identity is recorded by the accompanying implementation map. Date in this artifact is the audit branch identifier; it is not a target-host execution timestamp.

## Documentation and project placement

Detailed developer documentation exists: `TECHNICAL.md` has 17 sections covering the stateless read port, owner boundary, APIs, authorization, failures and qualification. Its supplements document limits, canonical bytes, owner cuts, final use, delivery, consumers and operations. These are technical development documents, but the existence of documents and source APIs does not establish normal product composition or acceptance. This audit corrects stale source identities, selected-path descriptions and consumer declarations rather than elevating completion flags.

The module sits between the durable CognitiveStore owner and retrieval consumers. It projects bounded immutable records with no write authority. Agentd composes retrieval, HNMF, optional ranking, learning preparation and publication; the native worker reacquires dependencies and an exact owner cut immediately before physical TurnStart. Memory and learning remain existing durable owners. Optimizations therefore belong at projection construction, owner witness admission, product handoffs and executable qualification boundaries; adding a separate cache or owner would weaken this placement.

## Reproducible findings and repairs

| Finding | Impact | Repair and regression |
| --- | --- | --- |
| V1 cloned all eligible heads/citations before truncation; V2 cloned/sorted arbitrary allowed-kind input before rejecting duplicates and cloned records before frame rejection. | Avoidable allocation from adversarial input; result limits did not bound result construction. | Borrow canonical current-head prefix; validate request first; count complete V2 frames before cloning. Golden/domain compatibility preserved; first oversized record is not silently skipped. |
| Fresh Agentd clients start their RPC counter at one; durable learning assignment identity reused that counter. | Distinct ordinary reads collided with an earlier durable preparation and became unavailable. | Existing learning owner issues disjoint preparation identities under its exclusive writer and witness checks. Explicit stable replay retains the previous semantics. Added ledger reopen and two fresh-client socket cases. |
| Context ingress validated a shadow before checking cheap row/omission bounds. | Expensive traversal on an envelope that must be rejected. | Bound envelope first, then full shadow validation; dedicated ordering regression. |
| Witness schema objects were missing from the owner's canonical schema inventory; existing v17 derived content was not independently re-audited on reopen. | Schema weakening or persisted witness drift escaped admission; schema oracle/recovery capture diverged from compiled schema. | Authenticate all witness objects; independently audit derived content at startup/recovery. Tests cover missing/weakened objects, content drift with restored schema and recovery capture. |
| Default non-recursive SQLite triggers admitted replacement of an existing witness identity; non-increasing frontier and same-revision head identity updates could evade expected maintenance. | An unselected mutation could be hidden from a prior cut by restoring frontier/identity state. | Migration 0018 rejects identity mutation, replacement and non-increasing frontier; maintenance uses update plus conditional insert. Head/validity identities are immutable. Independent tests run with recursive_triggers OFF. |
| Canonical scope audit materialized all expected scopes on every append. | Cross-scope history amplified write cost. | Migration 0019 adds scope expression indexes and uses indexed existence probes for unexpected scopes; old/new audit results match clean, counter-drift, missing and unexpected states. Same-scope counts remain linear. |
| Qualification accepted leaf-name filters, unrelated binary PASS output, inaccurate totals, partial receipt files and candidate tree disagreement. | A passing gate could fail to prove the declared cases or candidate. | Require exact qualified cases, binary, PASS inventory, exact totals and complete semantic receipts; reject symlinks and mismatched candidate commit/tree. Capacity executes the repository nextest gate. |
| Consumer maps described compaction/context ingress beyond actual callers and held stale blobs. | Source APIs could be mistaken for product completion. | Compaction remains registered/not composed; context V2 ingress remains source implemented/product pending; legacy caller is retained. Refresh exact source identities. |

## Verification actually executed

- `just test --locked -p codex-hepta-cognitive-read -p codex-hepta-context-compiler -p codex-hepta-learning-ledger`: 226 passed, one explicitly ignored target-host signed writer growth test. Counts are 56/49/121. Original tested blobs and log are retained in `qualification/cognitive-read/audit-20261001/LOCAL_REGRESSION.json`; this is a working-tree observation, not a qualification rebound to the final commit.
- Scoped `just fix` and strict clippy (`-D warnings`) passed for those three packages. Repository `just fmt` completed; unrelated baseline formatter churn was restored. Formatting changes do not imply a new execution receipt.
- Independent Python/SQLite adversarial suite: 79 passed. Compiled migrations match the canonical schema digest, weak definitions change the digest, legitimate maintenance remains audit-clean, replacement and identity attacks fail, and old/new audit drift categories match.
- SQLite 3.53.1 in-memory fixture, 2,000 sources across 20 scopes: target append approximate VM instructions 240,900 before migration 0019 versus 8,000 after (about 30 times fewer). Observed elapsed times 4.65 ms versus 1.14 ms. This is an illustrative fixture, not Rust owner latency, production p99 or a general constant-time claim. Machine-readable observation is retained beside the local regression record.
- Allocation probe: 4,096 heads with 64 citations, max_results=1: cumulative allocated bytes 120,811,008 to 102,158,547. V2 256-byte cap: 131,709,281 to 102,152,073 with unchanged result bytes. One million duplicate allowed kinds: 6,225,912 to 24. Full snapshot integrity validation still has a separate cost; these are cumulative allocations, not peak RSS.
- Full memory/Agentd/native builds and Bazel lock refresh were attempted but exhausted the shared 32 GB filesystem before completion. They are not recorded as passing. Internal Cargo lock edges were repaired; MODULE.bazel.lock was not manually fabricated.

## First-iteration completion assessment

This table records the first upload. The second-iteration assessment below
supersedes its preparation-handoff and execution observations.

| Layer | Assessment | Required closure |
| --- | --- | --- |
| Stateless projection and context/ledger focused behavior | Implemented and focused regressions passing | Exact committed source and synthetic merge gates. |
| SQLite witness and indexed owner admission | Source repaired; independent SQL adversarial checks passing | Execute Rust owner migration/recovery tests and workload gates on a host with enough disk. Oracle changes reject older recovery anchors; independently re-establish recovery through the owner process. |
| Agentd publication and native final use | Source composed, fresh observations retained | Complete ordinary product/native qualification, including unknown-send behavior. Observation remains distinct from a mutation lease. |
| Learning preparation | Durable identity collision repaired | Persist owner-issued preparation identity through ordinary response/native attempt and automatic delivery-to-learning ingestion. Explicit inspection is not that handoff. |
| Compaction | Authority-free candidate owner API | Integrate a normal product caller and existing-owner checkpoint publication with independent evidence. |
| Context compiler V2 | Local revision-bound ingress | Compose the provider-bound ordinary product path and prove physical use; legacy composition alone does not satisfy this. |
| Acceptance and release | Pending | Target-host measurements, signed independent evidence, external acceptance and governed activation/release. |

No numeric completion percentage is justified without an agreed acceptance denominator. All production implementation, product execution proof, independent acceptance, activation and release claims stay false where previously pending. The repeated audit converged on the reproduced source defects above; it does not establish that no future optimization or undiscovered issue exists. The remaining product handoffs are substantive development work, not documentation-only gaps, and require ordinary product contracts plus execution evidence.


## Second adversarial iteration

The same review branch was revisited after the initial upload. New reproduced
findings were repaired rather than declaring the first audit exhaustive:

| Finding | Revised behavior |
| --- | --- |
| Non-recursive `REPLACE` moved a canonical source to another scope without advancing the old scope witness; KG projection replacement could regress generation. | Migration 0020 guards 14 canonical/meta/projection identities. Atomic insert-if-absent retains legitimate source replay and its Conflict result, metadata reopen and KG initialization. Schema inventory now contains 169 objects. |
| Exact anchor capture and cold read-only recovery authenticated schema and physical integrity but omitted the independent derived-state audit. | The same capture transaction now independently audits scope/head contents before returning an anchor or admitting recovery. Drift cannot be signed into a fresh accepted cut. |
| Ordinary preparation receipt was discarded, while old inspection only understood explicit RPC identity. | Additive prepared-context RPC returns separate metadata; the normal worker persists it in the existing native dispatch journal. Witnessed lookup recomputes agent/generation/RPC namespace plus owner/sequence/predecessor. Context bytes and historical omitted-field journal bytes stay unchanged. |
| Successful test summaries could hide failure/cancellation, duplicate summaries or duplicate native PASS rows. Local qualification could compile untracked SQL under a tracked-only candidate check. | Require one complete successful terminal summary and exact unique binary/case rows. Qualification starts and seals with non-ignored untracked-input rejection; only regular evidence output paths are allowed. |
| Prompt adapter minted exact V2 tokenization evidence from registry token upper bounds and a sum that omitted framing. | Explicit tokenizer APIs measure candidates and the complete serialized payload. Compatibility entries without a backend now return ExactTokenizerUnavailable; ordinary Agentd does not stage an unsupported exact proof. No fixture tokenizer is installed as a product default. |
| Documentation CI rejected the owned fuzz package; legacy migration assertion stopped at version 14; utility map named nonexistent tests. | Register the fuzz subpackage, compare actual successful migration IDs with the compiled migration set, and correct source-test symbols without promoting completion flags. |

The prompt defect was reproduced with the current production function: both 9-byte
and 100009-byte serialized inputs were recorded as 4 tokens under a 4-token budget.
The fix removes metadata-derived exact counts. A source harness directly including
the current prompt pipeline, registry bridge and runtime modules plus their tests
passed 19 cases, using existing dependencies. This is an isolated source observation,
not an exact complete-crate nextest or physical-provider qualification.

Second-iteration Python/SQLite regressions passed 94 cases. An additional repository
Hepta Python run passed 685 cases. The module registry and derived-document check
passed after fuzz registration. Global document verification still rejects its
historical cleanup base because that base is not an ancestor of this development
branch; this audit does not rewrite history or relax that independent governance
condition. The prior exact-head CI subsequently completed with failures. Its
downloaded evidence revealed stale Rust test API calls, a legacy-only writer
fixture, obsolete KG physical-table assumptions, missing native fixture executable
configuration, two incorrect consumer fixtures and mixed Rust toolchains. These
failures are being repaired; the prior candidate is not qualified.

The local memory `just fix --locked -p codex-hepta-memory` completed, compiling
its test targets after the audited dynamic-SQL fixes. Complete new Rust execution
was attempted twice, but the shared filesystem filled during linking and again
during a narrower build. Neither attempt executed the new test suite or counts
as a pass. Logs preserve the resource failures rather than substitute an earlier
candidate's successful execution.

Independent repeated source review found no further reproduced SQLite, receipt
handoff or gate-parser defect after these repairs. This is bounded convergence on
reproduced issues, not a proof that all possible defects or optimizations are absent.

### Follow-through on the previous exact-head CI

The retained old-candidate bundle was downloaded and its ZIP, tar and complete
file checksum manifest verified. Its 43 gates include 16 failures, grouped into
nine causes in `qualification/cognitive-read/audit-20261001/REMOTE_EXACT_HEAD_35DC_FAILURES.json`.
The subsequent source repairs cover those causes:

- Audit-added dynamic SQL fixtures now use literals or explicitly audited SQLx
  strings. This corrects their compilation error without removing the attack.
- Default plasticity fixtures seed signed decisions through the existing
  production learning writer and independent witness; no legacy write feature
  is enabled. Dataset source sets use event digests, while the head retains its
  chain digest. The dispatch fixture supplies its required current clock.
- The physical native fixture receives an actual Codex CLI path. Qualification
  first builds the candidate's locked CLI, then supplies that binary consistently
  across Cargo and Bazel runfile environments. The ordering fixture recognizes
  the current authorized TurnStart call.
- The KG oracle independently counts the immutable active cut for
  `revision_facts_v1`, retains the legacy physical-row oracle, rejects unknown
  storage modes and reads the evidence in one transaction. It no longer demands
  obsolete physical copies or uses receipt counts as their own proof.
- Objective decoding explicitly retains the contract's empty caller action set;
  intrinsic abstain is compiled separately. NDU maximum residual includes the
  initial solve state. The corrected fixtures preserve both contracts.
- Every qualification command and version receipt uses the committed Rust pin,
  target directory and candidate CLI. Relevant memory formatting is repaired
  under that pin; root-directory Cargo cannot silently select a newer toolchain.

After these runner changes, the Python suite passed 99 cases. Scoped `just fix`
also compiled the infer-core, learning-ledger, intelligence, objective and NDU
test targets; subsequent strict clippy for these five packages passed with
`-D warnings`. Host `just fix` was attempted but stopped at a dependency with
ENOSPC. Compilation and lint checks are not test execution. The old CI
passes are retained only as observations of `35dc`; none are rebound to the
new source or used to elevate acceptance flags.

The subsequent `just bazel-lock-update` and `just bazel-lock-check` both completed
successfully. The existing lockfile required no change. This closes dependency-lock
resolution for the current inputs; it does not establish Bazel compilation or test
execution. Scoped second-iteration observations and the Python/prompt logs are
retained in `qualification/cognitive-read/audit-20261001/SECOND_ITERATION_OBSERVATIONS.json`.

### Revised remaining completion boundary

The preparation identity handoff is now source implemented and normal-worker
composed. Automatic training ingestion still must reacquire memory, learning,
consent/withdrawal and outcome owners; the join grants no training authority.
Compaction remains an authority-free candidate with no ordinary durable checkpoint
publisher. Context V2 still requires normal provider-bound ingress and an actual
model tokenizer/serializer backend. The exact tokenizer source APIs do not prove a
normal provider integration: a missing backend fails explicitly instead of issuing
fictional evidence. Complete committed source and synthetic merge execution,
target-host measurements, signed independent acceptance and release
remain separate requirements. None of their flags are elevated by this iteration.
