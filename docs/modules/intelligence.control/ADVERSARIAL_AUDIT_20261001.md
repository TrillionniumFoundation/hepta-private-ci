# intelligence.control adversarial audit — 2026-10-01

## Scope and source identity

The reviewed baseline is `0f0d40527db1090b8ec3ee51acbc2412a4f99c4a`, the
actual head of PR #1219 when this audit began, rather than its stale body or
`main@a126987b84737dbc2ee2592442a314117bddb4a2`. Changes are developed on
`codex/intelligence-control-adversarial-audit-20261001`. Prior logs and source
delivery capsules do not establish execution of this candidate.

The audit covers the canonical seven-owner composition, mutable-object and
digest boundaries, time budgets, Agentd worker supervision, durable learning
and native terminal recovery, and the module's qualification record admission.
It combines independent source reviews and adversarial regressions. This is a
bounded audit, not a proof that every possible defect or optimization is absent.
Successive independent reviews continued until the inspected source boundaries
produced no new confirmed actionable findings; external qualification remains
separate from that review convergence.

## Technical documentation assessment

Detailed technical development documentation exists. The stable entrypoint is
[TECHNICAL.md](TECHNICAL.md); [PRODUCT_CLOSURE.md](PRODUCT_CLOSURE.md) specifies
the actual product composition. Recovery is covered by
[RESTART_RECONCILIATION.md](RESTART_RECONCILIATION.md) and
[ADR-001-DURABLE-OPERATION-RECOVERY.md](ADR-001-DURABLE-OPERATION-RECOVERY.md).
[OPERATIONS_RUNBOOK.md](OPERATIONS_RUNBOOK.md) and
[COMPATIBILITY.md](COMPATIBILITY.md) cover operations and compatibility.
`IMPLEMENTATION_MAP.json` and `TEST_TRACEABILITY.json` bind source and tests.

The baseline contains six dedicated Markdown guides, but several claims had
drifted: the runner/provider profile was described as production composition,
already optimized manifest/index lookups were described as future work, and
recovery documentation omitted the learning I/O process watchdog. These are
corrected without upgrading qualification, activation or release claims.

The PR body's `ACTIVE_PRODUCT_CONTRACT.md` and `REQUIREMENT_TEST_MAP.json` are
not baseline files. The current files above are authoritative navigation.
The audited source-delivery capsule has SHA-256
`bb0858c91872e4406b2e383c6a6ac362df853b76fb03dc96580bb8f1d0c9e244`.
The old delivery artifacts remain in Git history and on the original branch.
This candidate retires source-writing materializer jobs and bootstrap files;
qualification workflows have read-only repository permissions and inspect the
ordinary source directly. This avoids qualifying a checkout and subsequently
rewriting its source identity.

Some newer qualification helpers existed only inside a source-delivery capsule;
they are reviewed as proposed source, not counted as already implemented.

## Position and completion assessment

| Boundary | Source assessment | Completion evidence still required |
|---|---|---|
| Seven-owner cognition | Canonical, bounded, ephemeral composition exists | Candidate native test execution and owner conformance |
| Authority/currentness | Signed per-fence snapshots and independent rollback witness exist | Independent key provisioning and target-host review |
| Product composition | Atomic four-owner embedding profile exists | An authorized embedding, real provider execution and exact-head receipts |
| Physical dispatch | Existing Agentd/App Server lifecycle owns effects | Lost-ack, restart and terminal reconciliation product evidence |
| Learning persistence | Existing operation/ledger owners retain intent and facts | Crash-cut and successor-generation qualification |
| Operations | Worker capacity, watchdog and telemetry exist | Target-host resource/termination measurements and operational acceptance |
| Activation/release | External authority is intentionally separate | Independent acceptance, canary, promotion and release |

The ordinary CLI does not provide the authorized seven-owner invocation,
physical execution and learning evidence objects. Source composition is
substantial, but default-product composition and production qualification are
not established. A numerical completion percentage would mix incompatible
states and hide those gates.

The module should remain a composition facade. Improvements belong at its
validation and sequencing boundaries; durable facts remain with
`kernel.operations`, `learning.ledger`, `runtime.agentd` and the existing
physical execution owner. Creating a second store or a parallel provider path
would weaken these guarantees.

## Confirmed defects and remediation

| Finding | Failure scenario | Remediation boundary |
|---|---|---|
| Policy and ledger candidate universes are conflated | A canonical selected action prepares successfully, but both default V2 and legacy qualification writes omit ledger's mandatory intrinsic abstain | Project fresh learning candidates before completeness/signature verification; preserve canonical bindings and historical payloads |
| Facade budget depends on adapter cooperation | A valid owner adapter ignores its budget and returns an overdue result | Measure stage and total monotonic time inside canonical composition |
| Standalone context accepts a stale decision digest | Public decision fields are changed while retaining a nonzero prior digest | Recompute the canonical decision digest before context assembly |
| Timeout/completion state is not linearized | Watchdog and request use separate counted flags; completion races publication | One shared worker state orders timeout accounting and completion |
| Provider factory can publish a late successful result | Watchdog expires while host invocation factory returns success | Check worker rejection and deadline before accepting the result |
| Native recovered terminal is not projected into Agentd | Native journal supplies a real terminal but Agentd remains indeterminate | Reconcile the same run's terminal without repeating provider effects |
| Individual run cancellation does not reach native execution | Another authenticated client cancels the dispatched run, but the embedding's global token and process health remain unchanged | Observe the exact bound run during live execution and route its cancellation through the existing interrupt/grace path |
| A known cancellation can still precede a physical send | The run is cancelled during final-use preparation after its dispatch projection, while only the global token is checked before model send | Recheck the exact run while the local pre-effect abort proof remains available; consume that proof before persisting native cancellation |
| Crash recovery can wash away durable stop intent | Cancellation is journaled before a crash but no terminal is settled; ThreadRead then reports Completed | Preserve the retained refusal boundary before journaling a newly recovered physical terminal; never mutate an already-cached terminal |
| Recovery can freeze success before observing cancellation in its owner receipt | Agentd is cancelled after a new ThreadRead status check and before terminal publication, while native has already settled Succeeded | Reconcile the exact terminal and inspect its owner receipt before the first journal settlement; allow authenticated uncancelled lost-ack recovery |
| Same-phase terminal publication can hide cancellation | Another observer publishes a late Succeeded after cancellation; an idempotent publication returns that receipt | Inspect the returned owner's retained cancellation reason before granting native success |
| Native lifecycle generation is compared to process identity | The control client uses spawn generation while the canonical run uses the next Running generation; a real admitted run is rejected | Keep the wire identity at spawn and validate run receipts against checked `spawn + 1`; reject overflow |
| Completed provider message is omitted without deltas | A legal done-only response yields a successful terminal with empty captured output | Collect authoritative completed messages by item identity, with de-duplication and existing byte bounds |
| Recovered output may be projected from a partial history view | ThreadRead Summary omits earlier messages after the stream is lost | Require a Full view before recovered output projection; reject partial views without replay |
| Duplicate recovery turn IDs can substitute output | Input authentication finds the correct turn but a later ID lookup selects another turn with the same ID | Require exactly one matching nonempty turn ID before projecting any output |
| Conflicting Agentd and physical terminals can lose reconciliation state | A terminal Outcome acknowledgement masks a different physical execution status | Require matching Agentd and physical terminal phases before producing or appending Outcome evidence |
| Direct native API can mix admission and canonical run IDs | A caller bypasses the product wrapper and names a different native operation | Require identical request/run IDs before touching reservation or dispatch state |
| Test record trusts self-reported success | Empty/failed logs are accompanied by fabricated positive counts | Recompute counts and bind record metadata to the actual checkout/invocation |
| Readiness helper is absent and proposed helper fails open | Existing workflow names a missing script; proposed `all([])` accepts an empty object | Materialize a reviewed strict readiness verifier and negative tests |
| Registry delivery can substitute owner lineage after rehashing | Public payload, exercise or compatible snapshot fields are replaced with internally consistent hashes | Compare the DTO to private admitted owner lineage and immutable serialization bytes |
| Complete registry output can be grafted across compilations | Another legal compilation replaces every public delivery field while the old private exercise lineage remains | Freeze the original complete delivery-set digest and reject the cross-output graft |
| Direct prepared delivery can substitute a complete valid serialization | Two deliveries share original context/exercise but have different framing and IDs; all public serialization fields are replaced together | Freeze the original complete prepared-delivery aggregate before its first consumer |
| Prompt delivery fabricates full-payload token accounting | Registered fragment token costs are reused as the token count of an arbitrary serialized payload | Require the model-profile-bound exact tokenizer for the complete serialized bytes; legacy APIs without one reject |
| Async journal/page ownership holds mutex guards across I/O | Recovery and physical execution keep an async mutex guard alive during owner calls | Keep serialization with a single permit; use short cursor locks and cancellation-safe journal checkout |
| Documentation and test navigation drift | Technical claims and mapped test names no longer match source | Correct the guides and validate exact source/test mappings |
| Ready publication can exceed the remaining budget | Final DTO construction and integrity checks happen after the last observed deadline check | Check monotonic and durable deadlines again immediately before Ready publication |
| Module declaration collides with project qualification schema | A source-only map claims generic v3 schema but lacks its observed execution contract | Register a distinct source-declaration schema and validate it through the owner verifier without granting execution |
| Legacy qualification appends skip Prepared integrity | An explicitly enabled qualification path records public decision fields after the prepared DTO was mutated | Validate the existing private Prepared seal before either qualification append; production learning already had this gate |
| A durable run-start regression uses an unrelated fence | The baseline fixture constructs an arbitrary digest despite requiring the composed source identity | Derive the fixture fence from its actual runtime composition; retain the production fence check and forged-fence regression |

The latest baseline already has final currentness fences for abstention and
slow-path terminal outcomes. An early reading of the older checkout suggested
otherwise; this was withdrawn after checking the immutable baseline. Regression
coverage is added without claiming a new source fix for that boundary.

Priority assessment: the lifecycle-generation conflict blocks the real product
path and is P0 for product completion. Budget admission, timeout publication,
prompt provenance/token accounting, recovery ordering and qualification
fail-open defects are P1 boundary correctness issues. Direct native API identity
binding and documentation/schema integration are P2 integration hardening. The
receipt-only cognition facade grants no effect authority; downstream severity
depends on an actual authorized embedding, rather than an assumed default CLI.

## Verification and remaining gates

Observed verification during this audit:

- Core cognition package: `just test -p codex-hepta-intelligence`, 104 passed,
  zero skipped, including both final private delivery aggregate seals.
- Strict core lint: a package-clean `cargo clippy --locked -p
  codex-hepta-intelligence --all-targets -- -D warnings` passed. Public v1
  by-value receipt APIs remain stable; test/benchmark fixture panic conventions
  have explicit local lint allowances.
- Audit helpers: status 19, readiness 9, fault matrix 10 and review partitions
  13 tests passed (51 total). Generic schema adapter 6 and existing provenance
  verifier 86 tests passed (92 additional tests).
- Source/test mappings, fault/review declarations and derived metadata checks
  passed. Nine Markdown documents had 89 local file/anchor links checked.
- Agentd/native host `cargo check --locked ... --all-targets` passed after
  generation, API identity and cancellation-safe journal-owner repairs.
  A completed `just fix` also compiled all three packages and their test targets,
  including the completed-message collector and Full-only recovery gate. This
  is compilation evidence, not execution of their assertions.
  The later duplicate-turn, terminal-phase, direct-delivery seal and legacy
  qualification-entry repairs require their own final compilation/execution
  result; current closing results are recorded on [draft PR #1290](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1290).
- `just fix` was run for all three modified Rust packages. Existing Agentd
  automation/cognitive/plasticity lint debt remains outside this module and
  can still block the repository's broader strict lint gate; it is not hidden
  by weakening that gate.

Earlier native test attempts ran out of shared disk while compiling dependencies.
Another local retry was terminated by SIGKILL in the `codex-config` dependency
before native assertions ran, while shared disk capacity was also exhausted.
Remote source-head CI at `12a3bbb7c74fe0dc78cd6e3e244537ffd96dff1b`
passed cognition, operation-owner (52 tests) and ledger (119 tests) stages.
Its native stage had 36 passed and one failed assertion in an existing real
App Server fixture. That fixture omitted streaming text frames; investigating
it also exposed the completed-message collection defect above. These partial
results do not qualify the later corrected candidate. Final native assertions
and exact source-head/base-merge CI remain pending unless recorded separately.

Subsequent source-head run `36784727055` at `cc49113e8fec61c3c1ca955d3fd5bf3cc168f26f`
and base-merge run `36784733685` at `4c20734afe7861dfa6b63276e955d0efa854c667`
both passed 104 intelligence, 52 operation-owner, 119 ledger and 53 native
tests. Operations and ledger each had one ignored test; native had none. Their
default Agentd stage had 219 passed, one ignored and one failed: the baseline
durable run-start fixture used an unrelated fence. This iteration corrects that
fixture without changing the production identity check. These results predate
the new individual-run cancellation bridge and cannot qualify that change.
The final cancellation iteration adds ten native regressions covering pre-send,
live, terminal-publication and recovery cuts. Two independent closing source
reviews found no additional confirmed actionable issue. The final focused
verifier run passed all 143 Python tests, and tracked declarations and derived
metadata checks passed. Scoped Rust formatting and `git diff --check` passed;
both latest local `just test` attempts failed during `codex-core` dependency
compilation with SIGKILL, before their assertions ran. The scoped `just fix`
attempt failed during `codex-otel` compilation with ENOSPC. The ten new native
regressions were not executed locally. Exact-candidate CI and required
production gates remain pending until their actual command records exist.
The historical development-documents run at
`cc49113e8fec61c3c1ca955d3fd5bf3cc168f26f` passed all 691 Python tests;
its final integration gate failed on other modules' historical source
observations/anchors. Strict diagnostics failed on existing memory-extension
and codex-core dependency lints. No failing gate is weakened or reported as a
success. Those historical results do not qualify the latest cancellation
candidate. This final report-only correction changes no Rust source or test.

Source references, added tests and successful declaration checks are not
substitutes for native test execution. No historical receipt, bootstrap artifact
or self-reported counter grants production readiness.

Recovery also requires the host factory to reproduce the original owner evidence
and exact prepared envelope. The facade has no durable prepared-object archive;
changed context/envelope lineage is rejected rather than applied to a historical
provider result. This audit does not claim automatic recovery of arbitrary owner
evidence drift or cross-generation adoption.

The registry staging adapter extracts developer fragments from a binary source
envelope. Its tokenizer receipt covers that source envelope; the host must count
its final provider serialization separately. A source-envelope count is not a
physical request count. Concrete model-specific tokenizer implementations and
authorized live factories remain embedding responsibilities.

Seven-owner freshness and provider final-use authority are separate boundaries.
Deployment must prove that owner revocation after Decision acknowledgement and
before model send is rejected by the composed final-use issuer; a current
provider grant alone is not proof of current seven-owner inputs.

The audit cannot create independent operator acceptance, live owner credentials,
provider observations or target-host measurements. Those remain explicit gates
in the module's implementation map and operations runbook. Further optimization
should be driven by those measurements, including manifest verification cost,
worker saturation, learning recovery age and cancellation-to-stop latency.

## Follow-up: exact execution and current-main integration

The formerly pending candidate `23d351d9bf13171cb55e734e1d54e0c6b95d7a68`
has now executed in push source-head run `36795787378` and PR source-head /
base-merge run `36795792948`. The independent synthetic merge is
`f69d1a74491f9d5f3a3297b4420181853144964c`, with the same tree as that source.
Each lane passed 104 intelligence, 52 operation-owner and 119 ledger tests;
operations and ledger each had one ignored test. Each native stage had
62 passed, one failed and none ignored. The ten new cancellation regressions
therefore have nine observed passes and one failure, rather than remaining
entirely unexecuted.

The failed live-cancellation fixture initialized its mock App Server with
`userAgent: test-app-server`. The real client parses the version after `/`,
so the mock supplied no version while its admitted binding required
`test-app-server`. The terminal correctly failed with
`CorrelationMismatch("app server version")`. This follow-up changes only that
fixture to `codex/test-app-server` and asserts its parsed handshake version.
The production correlation check remains intact. The subsequent candidate
`d6961948cccb9b91d649a04232e9471408de75b3`, tree
`02380265e96b9b350f0c442c1c3067b7958ccc29`, executed in PR run `36818789033`.
Both source-head and independent base-merge lanes passed all 63 native tests,
including all ten new cancellation regressions, and all 220 default Agentd
tests with one ignored. The actual durable-fence regression also passed.
The independent merge `a311f0cf9aa4bfcf3e5e1824215ea0417c9ff31c` had the same
tree as that source; this evidence does not apply to the later main integration.

That run then exposed an E0061 compilation error in the explicitly enabled
`qualification-legacy-learning-write` fixture: its old `mark_dispatched`
call omitted the now-required clock argument. No qualification-feature
assertions ran. The integration repair passes the same fallible wall clock
used for product admission, retaining the production dispatch-deadline gate.
It does not restore the legacy no-clock API or enable legacy learning writes
by default. The repaired feature still requires its own execution record.

Diagnostics run `36818788949` again passed 57 filtered default Agentd tests
(one ignored, 163 filtered) and compiled all default targets. Strict lint
still failed at the ten previously identified memory-extension/core sites.
The readiness projection retained the feature compilation failures and did
not turn them into qualification success.

Diagnostics run `36795792676` passed 57 default Agentd intelligence-filter
tests (one ignored, 163 filtered) and compiled all default Agentd targets.
Its ten strict-lint errors originate from memory-extension and core files with
the same blobs as baseline `0f0d40527db1090b8ec3ee51acbc2412a4f99c4a`.
The corrected durable-fence assertion is outside that filter and was not run:
the independent default Agentd stage was skipped after the native failure.
Later qualification-only and independent all-target / lint gates were also
skipped. A successful readiness-manifest job preserves those failed or missing
results; it does not upgrade them to successful execution.

Qualification-host run `36795792690` passed 32 probe executions covering
22 distinct tests. Its records explicitly keep production target-host
acceptance, independent semantic/security acceptance and activation/release
false. The probes do not execute the ten new cancellation cases or a real
provider embedding. Admission timings were rounded to `0.00`; those values
do not establish zero latency or useful end-to-end performance measurements.

The source document job in run `36795792744` passed 691 Python tests before
the broad document verifier rejected source-observation drift and missing
historical anchors in other module mappings. There was no
`intelligence.control` failure in that list. Shared `runtime.agentd` and
`inference.worker` mappings are affected by this PR's source changes, so the
remaining failures are not all unrelated. The separate document merge
`6747f679597deeb8f9c10ee03391af2fa33c3cf4` ran only its verifier, not another
691-test suite. Neither job produced a successful qualification receipt.

Current main is `997e7beef8151160065df36b024bc8da5c989e93`, newer than the
reviewed main baseline. Its development/qualification profile separation and
SQLite dependency changes require an independent integration check. Existing
old-base receipts do not establish that integration. In particular, preserve
the dedicated intelligence source-declaration adapter and cancellation test
mappings alongside main's new verification profiles; replacing them with the
generic map would discard the reviewed source declarations.

The integration worktree now resolves all seven actual merge conflicts with
that main. It retains the audited owner implementations, transaction-local
clock reads, immutable learning facts and dedicated pending declaration. The
main SQLite helper's canonical parent-path handling is retained with the
operations owner's established four-connection bound, rather than silently
raising capacity to five. The dependency lockfile includes both sides' actual
dependencies; offline locked Cargo metadata validation passed.

Current development navigation also exposed two stale aggregate caller paths
in the NDU and Context module maps. Both now identify the real adapters in
`intelligence_product_ports.rs`, with source-only caller states and the actual
split-file blob. Qualification flags, top-level conservative composition
states and historical observations were not renewed. The utility adapter
remains policy-bound and read-only; a consumed Context owner attachment is not
proof of complete authenticated V2 provider ingress.

The fused worktree passed development verification of all 40 module maps and
the full development document system. Both explicitly decline to revalidate
historical qualification or prove production implementation. Six source-only
adapter regressions now exercise both development and qualification profiles,
including rejection of every execution/acceptance/release promotion. Those
six tests and all 86 implementation-map regressions passed. Pending fault and
review declarations and derived-document checks also passed. These were
pre-commit integration/navigation checks, not native execution receipts for a
new merged source identity. New exact-head native, full Agentd, qualification
and lint command records remain required for the integrated candidate.

The integrated candidate `3de5e76dbb2bfeb5b19b951db7fa915a48422cd2`, tree
`9a0d587e32dc1286d747a2bf884ff033fd0b83b5`, exposed two further source
integration omissions in blocking run `36821206913`: Codespell rejected
a missing hyphen in a test assertion message, and the closed caller proof omitted
the real learning reconciler's final-use claim/dispatch calls. The spelling
is corrected. `CALLERS.toml` now declares only that exact caller for both
canonical boundaries. Browser-specific guards remain checked on the browser
file; learning-specific guards check the existing destination-first,
fresh-grant and exact-binding dispatch path. Raw/witness caller sets and all
authority flags remain unchanged. The caller verifier and lexical self-test
pass on this follow-up worktree; all twelve guard-removal/unregistered-caller
attacks are rejected. The shared manifest is included in the pending review partition;
old automation source observations are not relabeled as new execution.

Recovered local `just fmt`, the main-relative formatting check and the bounded
Bazel batch lock refresh returned exit zero, with no dependency-lock drift.
An integrated owner-test attempt failed in `clap_builder` dependency compilation
with ENOSPC before assertions, after the shared filesystem filled. It provides
no owner-test pass. Earlier execution-session interruptions likewise do not
provide successful command outcomes. Exact remote candidate records remain
the execution authority; development navigation and source proofs do not
replace qualification, independent acceptance or release.

All three integrated independent lanes subsequently completed their ordinary
stages: 104 intelligence, 52 operations, 119 ledger, 63 native and 220 default
Agentd passes. Operations, ledger and default Agentd each retained one ignored
test. The actual PR merge was `ad58a213662a30d04344f4092ddc9d03a7e5c9c5`, with
the same `9a0d587e32dc1286d747a2bf884ff033fd0b83b5` tree. The repaired clock
call compiled with the qualification feature, but that suite executed with
220 passed, three failed and one ignored. All three old positive fixtures
omitted signed evaluation input and host trust; their common failure digest
binds the exact missing-session label, not a metric-policy failure.

The three explicit legacy-qualification fixtures now reuse the existing
real signed-evaluation fixture and install its activated host-root trust.
That fixture rebuilds the evaluator-key-bound snapshot and binds the actual
context, legal candidate set and current clock. The unsigned global fixture
remains available for negative tests. Existing revocation and Prepared-mutation
assertions remain unchanged. Only the test child's existing helper gains
parent-local visibility; production signed-session checks and canonical-profile
installation gates remain intact. These repaired assertions require execution
on the next candidate; their former failures are not relabeled as passes.

The recovered scoped `just fix` for intelligence, Agentd and the native worker
host exited zero after compiling default test targets, with existing warnings.
It removed one redundant clone in the owned delivery-graft regression.
Formatting then passed. This is compilation/lint-fix evidence, not execution
of the repaired feature assertions or a successful strict `-D warnings` gate.

The next published candidate `b1f7fac4b33d34ccc78eaf142aac91acbbd6d74c`, tree
`c63abaebc7936cd117da3bed9e4b0621b815849c`, executed all three independent
lanes. Their ordinary intelligence/operations/ledger/native/default Agentd
counts remained 104/52/119/63/220 passes. The feature suite reached 221 passed,
two failed and one ignored; the revocation assertion now passed. Its two deeper
failures exposed a one-action mutation fixture and a real candidate-universe
adapter defect. Default `ProductionDecisionV2` construction had the same defect
as the feature path: it copied only policy actions, while the ledger requires
its intrinsic abstain. The actual base merge was
`33aa51a79734431b499982fec50bda24a016f98b`, with the same candidate tree and
main baseline. These failed results remain historical evidence, not passes for
the follow-up repair. Later all-target/lint/projection steps were skipped.

Both fresh learning adapters now use one private projection that reserves the
intrinsic abstain slot, rejects reserved-ID collisions/duplicates/overflow and
produces a sorted unique ledger universe. Canonical/evaluation action digests
remain unchanged. The default adapter verifies the provider's inclusive
completeness and signature before persisting any payload; it never supplies
missing proof fields. Recovery does not invoke the projection or alter any
historical candidate, completeness, signature or operation identity. The owner
shadow adapter already uses this separation. The integrity fixture now has a
real second action in legal, NDU and intuition inputs, with updated completeness
and actual signed evaluation binding.

New regressions cover the 127-action capacity boundary and a real durable
`LedgerWriter`: action-only completeness and corrupted signatures must leave
the ledger empty; inclusive signed evidence must append once and replay
idempotently without changing the prepared canonical result. These new tests
require execution on their own published source identity.

The `b1f7fac` diagnostics lane subsequently passed 156 intelligence/operations
assertions, 57 filtered default Agentd assertions (one ignored, 163 filtered)
and default all-target compilation. Its strict gate again reported the same
four memory-extension and six core lint errors. This confirms the prior source,
not execution of the newly added candidate projection regressions.

On `b1f7fac`, the core caller scanner and its lexical self-test passed. Blocking
QA separately found one failure and one error in the existing kernel-authority
closed-world inventory (an over-escaped regex and a missing advertised boundary).
Its manifest, test and production boundary blobs match reviewed main. Existing
Objective empty-action fixture failures and ten strict lint failures also match
main; these project-wide qualification blockers are not suppressed or changed
by this module audit. Codespell rejected a historical spelling quoted in this
report; that quotation is corrected in the follow-up candidate.

The learning repair `fe42a27b09551649f3a73afc543d29c5bdf30f69`, tree
`db768271a78bccb2e70e466fd06eea61426060f3`, passed all six package commands
in push, source-head and base-merge lanes: 104 intelligence, 52 operations,
119 ledger, 63 native, 223 default Agentd and 226 qualification-feature tests.
Operations, ledger, default Agentd and the feature each retained one ignored
test. The three new candidate/writer regressions and both previously failing
qualification assertions actually passed. All-target Agentd compilation also
passed. The tested merge `bddfabc4f6b2a5f0e39de6966c0ce1bc8531ebf8` has the
same source tree and ordered main/source parents. Strict lint still failed on
the same four memory-extension and six core baseline errors; later execution
projections were skipped. Codespell and both caller checks passed.

The macOS diagnostic lane separately exposed a portability omission in the
new writer regression: its authority path retained the OS temporary-directory
alias, so the production no-follow reader correctly returned
`FreshnessUnavailable`. That run recorded 59 passed, one failed, one ignored
and 163 filtered default tests; all-target compilation passed. The fixture now
canonicalizes its directory before creating authority, ledger and witness
files, matching the existing signed fixture's provisioning contract. Production
no-follow checks remain unchanged. The corrected fixture requires its own
macOS execution; the former failed result is not relabeled as a pass.

The fresh local scoped lint-fix attempt first lacked automatic OpenSSL discovery.
Using the dependency's supported explicit system include/library directories
recovered that setup, but compilation then exhausted the shared filesystem
while building `rmcp`, before the changed module. Both attempts exited 101 and
provide no lint or test pass. Only this task's compiler cache was cleared.

### Final source results and process-measurement correction

The canonical macOS fixture repair `1873ffcc8cf2622ac227d6e894d489f7c1561422`,
tree `f664ae7cdc534e2471c4061a5c259d402a6bb576`, passed all six package test
commands in push, source-head and actual base-merge lanes: 104 intelligence,
52 operations, 119 ledger, 63 native, 223 default Agentd and 226 feature
assertions, with the four documented ignored tests retained. The actual tested
synthetic merge was `6f2abf6b103862efbd75b5d4ac1544a116ac449a`; its tree matches
the candidate and its ordered parents are reviewed main and that source head.
macOS passed 156 intelligence/operations and 60 filtered Agentd assertions,
including the repaired writer fixture, with zero failures and one ignored
Agentd test. All-target compilation and formatting passed. Strict lint still
failed on four memory-extension and six core diagnostics at sites unchanged
from main. Execution projections skipped; both actual readiness manifests
remain `mergeReady=false` and `productionQualified=false`.

Qualification-host run `36827814499`, job `110257639262`, succeeded on that exact
source. Its release binaries executed 32 assertion invocations covering 22
distinct tests, including five semantic conformance cases, with zero failures.
It retained 2,000 signature samples and nine real-child hard-kill samples in
artifact `11147978901` (SHA256
`c8d4251ae9cc7966e45eb943e91fe522c91220b2f6a1adc2c939404486fd0b0a`).
Signature p50/p99 were 54.031/74.179 microseconds; hard-kill spawn-to-exit-70
p50/p99 were 45.956784/46.165455 milliseconds. These are observations on that
GitHub host, not production-target or real-model acceptance.

The same raw artifact exposed a measurement defect: GNU time reports elapsed
and CPU seconds to two decimals, so every short owner-admission sample became
`0.00` and the derived CPU percentage was uninformative. Those historical
measurements cannot establish zero cost. The follow-up replaces GNU time with
a fresh Linux Python parent for every sample: `perf_counter_ns` wall timing,
terminated/waited-child resource accounting, full decimal CSV and explicit
method metadata. It kills the sample process group and reaps the direct child
on timeout; nonzero or timed-out samples produce no successful row. The summary
rejects zero/nonfinite wall time, negative CPU, duplicate/reordered samples and
CSV/metadata disagreement. Wall time includes process startup, fixture work,
IO and parent wait scheduling; RSS is the largest child peak, not total tree
RSS. Decimal representation does not promise nanosecond measurement accuracy.
Real-process helper regressions cover successful execution, CPU/log capture,
failure, timeout cleanup and invalid inputs. Fresh workflow measurements must
retain their own source identity; the prior run is not relabeled as their pass.
