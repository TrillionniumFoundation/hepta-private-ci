# knowledge.graph second-pass audit — 2026-10-01

Reviewed source: `1a75d5f14fe7e66ee108086351917217289d43ac`, the published
follow-up to `1ed1f65ed6bffe5320beedaad4c4e5f387237632`. That review observed main
at `a126987b84737dbc2ee2592442a314117bddb4a2`. This report continues
[FOLLOWUP_AUDIT_20261001.md](FOLLOWUP_AUDIT_20261001.md) and records newly
reproduced defects rather than treating an earlier review as exhaustive.

## Documentation and project ownership

The reviewed canonical [development plan](../../docs/DEVELOPMENT.md) is v8.0.0, dated 2026-09-23, at integrated main `997e7beef8151160065df36b024bc8da5c989e93`. Detailed technical development documentation exists: the module guide has 17 sections, and the eight-section implementation dossier specifies source contracts, canonical data, algorithms, resource ceilings, failure/recovery and named acceptance cases. The update below corrects their implemented-versus-target and executed-versus-pending distinctions.

The [technical guide](../../docs/modules/knowledge.graph/TECHNICAL.md),
[implementation dossier](../module-execution-dossiers/detail/knowledge.graph.md),
native implementation map, capacity probes and target-host budget harness provide
detailed development material. Their target contracts are not execution receipts.
KG owns projection, canonical generation and query semantics. Cognitive and prompt
owners retain facts and persistence; consumers cannot acquire mutation authority
from a KG receipt. This audit extends integrity checks in those existing owners
instead of creating another graph fact store.

Agentd already has a canonical portfolio compiler/runtime-stage consumer. It does
not thereby establish the sealed prompt-factor source -> KG projection -> graph
selection route. Compilation freshness and final provider dispatch are separate
boundaries, each requiring current owner evidence.

## Reproduced findings and repairs

| Finding | Reproduction and repair |
| --- | --- |
| Cognitive history qualification cannot compile | Both remote lanes failed with six E0659 ambiguous `assert_eq!` uses. Add the explicit pretty_assertions macro import; preserve the workload and assertions. |
| Adapter and graph tests were never compiled | KG prompt_factor_tests.rs and optimizer graph_tests.rs were not declared as modules. Their stale dependency-private calls would also fail when enabled. Wire real tests using public durable owners and signed final-use admissions, with no exported fixture authority. |
| Memory FTS can diverge from source | A normal FTS UPDATE preserves quick_check and foreign keys while changing lexical recall. Verify every immutable memory revision has exactly one FTS row and that every indexed identity/content matches its source, including superseded and tombstoned history. |
| Historical entity FTS can alter current retrieval ranking | Obsolete entity rows contribute to BM25 corpus statistics but were outside current-generation comparison. Verify the complete retained entity FTS corpus against exact source identities, canonical IDs, types and labels; retain current-generation reconstruction checks. |
| Canonical selection admits candidates outside its complete graph | A graph containing only factor `b` can previously select positive-utility candidate `a`: an unknown seed yields no relation edges. Require every priced candidate to occur in the validated graph before querying; a represented relation-free candidate remains valid. Preserve the generic kernel query's unknown-seed semantics and add the counterexample regression. |
| Relation changes after selection do not invalidate exercise | Registering a governed conflict leaves selected realization bindings unchanged. Retain the enumerated registry digest in the selected portfolio, bind it into the receipt checksum, and reject source/checksum drift at exercise; prove compiler rejection separately. |
| Persisted attachments outlive their source fence | Compilation-time checks do not protect prepare/dispatch after a staged attachment is restored against a changed registry. Persist an attachment-bound registry snapshot and check the shared current owner during prepare and every dispatch claim, including cached prepare/idempotent retry; preserve unresolved-dispatch reconciliation and historical records. |
| Staged deadline can outlive selected-portfolio validity | With unchanged registry source and a longer requested deadline, an expired selection can otherwise remain dispatchable. Cap the attachment deadline at the minimum of request, portfolio validity and realization expiry. |
| A lock waiter can bypass mandatory reopen after uncertain durability | A waiter can pass the first availability check, block on runtime state, then acquire it after another commit has poisoned the owner following rename. Recheck availability after acquiring state in commit and prepare; deterministic waiter regressions must prove no stale read or successor write is admitted. The queued-poison regressions passed in the historical 16-test prompt-runtime filter at source `c3056c3`; current whole-candidate product qualification remains open. |
| Capacity wording overstates canonical cardinality | The 256-write probe contains 4,096 entity/32,768 relation revision occurrences but only 16 canonical nodes and 128 canonical edges. Describe the actual fixture and avoid claiming an executed canonical pilot-size receipt. |

New semantic FTS checks use aggregate SQL and joins. They do not fetch all history
into Rust or issue one query per revision. They still add historical scan and SQL
grouping costs: owner startup is history-dependent and needs retention/startup
budgets. The audit does not remove integrity checks or erase history to claim
bounded startup.

Registry-source invalidation is conservative: owner mutations require reselection
or recompilation even when selected realization bytes remain equal. A receipt
checksum proves binding consistency, not a signature or permission. Every graph,
portfolio and compiler claim retains its original authority boundary.

The runtime fence uses optional metadata in the existing schema-1 staged record,
with no new store or authority. Old unfenced stages remain readable and pending
dispatches can be reconciled; the bound pipeline rejects their prepare/dispatch
without inventing a source binding. Standalone generic qualification-host behavior
is preserved. Older binaries reject populated unknown metadata, so downgrade needs
owner review. Source-fence regressions are wired under
`prompt_runtime::tests::source_fence`; all seven source-fence cases and the
queued-poison behaviors passed in the historical 16-test filter at source
`c3056c3`. Complete product and source-head/synthetic-merge evidence remain
separate obligations.

## Executed baseline qualification

[GitHub Actions run 36783032514](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/36783032514)
tested both source-head and deterministic base-merge lanes. The source head was
`1a75d5f14fe7e66ee108086351917217289d43ac`; the merge candidate was
`f3b02512169b0c158625afe73c059f4b5cc23a6f` with the same source tree.

| Baseline check | Executed result |
| --- | --- |
| Canonical KG kernel | 31 passed, zero skipped, in each lane |
| Prompt registry | 55 passed, zero skipped, in each lane |
| Prompt optimizer | 32 passed, zero skipped, in each lane |
| Scoped four-owner mapping, harness checks and KG-owned formatting | Passed in each lane |
| Detailed-design conformance | Passed; this is coverage/hash/path/oracle conformance, not product execution |
| Cognitive native tests | Compilation failed with E0659; zero memory tests executed |
| Ignored crash/capacity/history, Agentd profiles and combined strict lint | Skipped after the compile failure |

The previous 118-test receipt cannot cover newly enabled adapter/graph tests or
the new owner and delivery regressions. Local memory builds had separately failed
with ENOSPC. Neither compilation failure is a test pass or evidence that recovery
works.

## Subsequent execution and third-pass repairs

[Run 36794255979](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/36794255979)
executed source `163441e047f44a1cffa3df968d4358c88821cdbf` and merge
`98369340bdaf2f9d5aa0f29121fbf55ad3875e07`; both had tree
`33635553f041ddc6404b7620eb8e9f2311ff4c87`. Each lane passed KG 35 and registry
55 tests with zero skipped, plus source mapping, harnesses and formatting.
Optimizer compilation then failed with E0252 duplicate imports. All downstream
cognitive, compiler, crash, capacity, Agentd, history and strict-lint steps were
skipped. The runner had sufficient disk space. Dependency-lock regeneration
actually passed: exit zero, empty patch and generated MODULE.bazel.lock identical
to the candidate blob. These results cover only that candidate.

The local memory run initially failed two test preconditions, and compiler
delivery initially failed one fixture. The latter used reverse-ordered endpoints
for a canonical symmetric Conflict. The FTS preconditions reused a connection
with stale FTS integrity-check cache after another pooled connection wrote; the
false positive was reproduced with the actual bundled SQLite 3.51.3 library.
Fresh read-only pools now prove healthy seed and post-update structural integrity
before real owner reopen must reject the exact source drift. Production validators
and corruption assertions were preserved. Repaired library runs passed.

The third pass integrates main `997e7beef8151160065df36b024bc8da5c989e93`,
including its latest V8 development/qualification distinction. Ordinary checks
validate current navigation and affected native packages. The explicit KG deep
workflow retains qualification-profile checks and accepts exact source/base SHA
inputs for source and synthetic-merge lanes. Its unsupported nextest `inherits`
key is removed; the existing default timeout still applies.

| Third-pass finding | Repair and verification boundary |
| --- | --- |
| Newly enabled optimizer tests cannot compile | Remove duplicate CandidateDisposition/PromptCandidate imports and the unused PromptRegistry import. |
| Agentd runtime tests import an undeclared assertion library | Add the existing workspace pretty_assertions dev dependency and regenerate Cargo.lock with Cargo; actual Bazel regeneration passed with no lock drift for the new dependency edge. |
| SQLite affinity hides an FTS identity type mismatch | Numeric TEXT or REAL revisions join to integer source revisions and pass quick_check, but SQLx integer decoding rejects them. Require canonical SQLite storage types in both retained FTS corpora; add a seeded-store regression proving the join/decoder mismatch and fail-closed reopen. |
| A selected graph view outlives clock-scoped relations | Cap selection validity at the next relevant edge or endpoint support boundary, including currently invisible future constraints. Signed enumeration/pricing/selection/exercise fixtures cover inclusive starts, exclusive ends and millisecond conversion without changing the registry. |
| A receipt can name factor A while compiling factor B | Bind the complete selected realization, inner/outer factor identities, state, objective, model and generation to the proposal checksum. Independently require canonical receipt/selection equality, exact bindings, token sum and expiry; recomputing a checksum cannot repair an inconsistent receipt. Exercise and compiler regressions use genuine compatible factors, with no mutation permission from the checksum. |

## Candidate history and current validation

Final native source `6fe8237c493b9c2a52bf2b685da1d9b1b11333cd`, tree
`bbe525f939dc110e1d0fdfa10b445f0d46b30c68`, actually passed 440 scoped tests:
KG 35, registry 55 and optimizer 49 (core 139), memory 277, compiler delivery
six, explicit crash one, explicit correction/deletion history one and Agentd
prompt-runtime 16. Memory retained eight ordinary ignored cases; the compiler
and runtime filters omitted 77/160 unrelated tests. All three genuine-owner
source-authentication counterexamples that failed on the baseline now pass, as
do all seven runtime source fences. Every executed workload had identical
before/after critical source hashes at this same source/tree. Six-owner fix
exited zero with unchanged critical inputs, while strict lint exited 101 on the
existing main-identical large-enum-variant diagnostic; its gate remains failed.

Execution receipts bind their actual source rather than every later candidate.
At source `c3056c379e5a272bb8c3037b4608f5d4341c0c01`, local execution passed
all 133 core tests, 277 ordinary memory tests, five compiler-delivery tests, one
explicit crash test, one explicit correction/deletion history test and 16
prompt-runtime tests: 433 passing tests in total. Core had zero skips; memory
had eight ordinary ignored cases; compiler and runtime filters omitted 77 and
160 unrelated tests respectively. The seven source-fence cases actually ran
and passed, rather than merely being compiled. The core inventory was KG 35,
registry 55 and optimizer 43, including newly wired genuine-owner adapter and
graph-consumer fixtures. Subsequent source-authentication tests and repairs
cannot inherit this receipt.

Earlier local native attempts hit ENOSPC, and the initial Bazel attempt had a
JDK trust failure. The third pass actually ran `just bazel-lock-update` with
Bazel 9.0.0 and normal TLS validation after adding the Agentd test dependency:
exit zero, no lock drift. A task-local repository-content cache issue was
bypassed through the supported cache option; no source dependency was patched
to fabricate the receipt. These local library receipts are not remote
whole-candidate qualification.

| Workload | Actual local result and source |
| --- | --- |
| KG / registry / optimizer at c3056c3 | 35 / 55 / 43 passed, zero skips; 133 total |
| Memory library at c3056c3 | 277 passed; eight ordinary ignored cases; exit zero |
| Compiler delivery filter at c3056c3 | Five passed; 77 unrelated cases filtered |
| Explicit child-process crash windows at c3056c3 | One passed; 284 cases outside the filter |
| Explicit correction/deletion history at c3056c3 | One passed; 128 corrections, eight reopen samples and three post-deletion reopens; no deleted-fact resurrection |
| Agentd prompt-runtime filter at c3056c3 | 16 passed, including all seven source-fence regressions; 160 unrelated cases filtered |
| Six-owner scoped fix at c3056c3 | Exit zero; before/after source hashes identical; existing owner warnings remain |
| Strict lint at c3056c3 | Exit 101: existing `CanonicalRunOutcomeV1` large-enum-variant diagnostic in `hepta-intelligence/src/canonical.rs`; real code lint failure, not disk failure |
| Default support-growth capacity at 676a187 | Exit 100, 30-minute watchdog; all writes, queries and contention completed, two of five reopens completed; no PERF receipt |
| Agentd default cognitive-product attempt at 2be1a1d | Build exit 101: codex-exec-server archive failed with ENOSPC; zero tests executed |
| Earlier prompt-runtime attempt at 2be1a1d | Build exit 101: darling_macro linker terminated with signal 7 (Bus error); zero tests executed; cause not conclusively attributed |
| Agentd qualification-witness attempt at 2be1a1d | Build exit 101: codex-core-plugins LLVM output failed with ENOSPC; zero tests executed |
| Dependency regeneration | Actual Cargo and Bazel runs; Bazel exit zero, no MODULE.bazel.lock drift |
| Genuine-owner source-authentication baseline at 807df523 | Two optimizer tests and one compiler test failed because omitted owner Conflict / fresh dual selection / both signed payloads were accepted; identical tree to local baseline 7af3 |
| Initial source-authentication filter invocation | Exit 4, zero matching tests; not counted as an executed counterexample |
| First repaired-source core run at 0314b2f2 | 139 executed: 137 passed, two fixture-setup failures (`StableId::InvalidCharacter` from support labels containing spaces); not a full core pass |
| Final core retry at 6fe8237c | 35 KG + 55 registry + 49 optimizer = 139 passed; zero skips; only two fixture support labels changed, with production/assertions/workloads unchanged |
| Final memory/compiler/crash/history at 6fe8237c | 277 memory, six compiler, one crash and one history passed; eight ordinary ignored memory cases and 77 filtered compiler cases |
| Preceding repaired-source runtime build attempts | Four builds exited with E0463/E0599 dependency-resolution failures; zero tests executed |
| Final Agentd prompt-runtime filter at 6fe8237c | 16 passed, including all seven source fences; 160 unrelated cases filtered; normal matching-unit rebuild resolved the observed archive dependency-hash mismatch |
| Final six-owner fix at 6fe8237c | Exit zero, 261.141 seconds; all 1,096 critical inputs unchanged |
| Final strict lint at 6fe8237c | Exit 101, 169.078 seconds; main-identical `CanonicalRunOutcomeV1` large-enum-variant diagnostic (Ready >=528 bytes, Abstained >=272); actual code lint failure, not disk failure |

The [native execution receipt](evidence/native-round3.json) binds each actual
source/tree, verbatim command arguments when captured, exit status,
ignored/filtered counts and before/after critical input hashes. Raw evidence is
retained outside the repository and bound by archive SHA and per-file manifest;
missing historical command fields are not reconstructed as facts. This history
is execution evidence, not dynamic source selection, product acceptance,
activation or release authority.

Final strict lint's failure is `hepta-intelligence/src/canonical.rs:463`,
`CanonicalRunOutcomeV1` large_enum_variant: Ready is at least 528 bytes,
Abstained at least 272 bytes, and the whole enum at least 528 bytes. Candidate
blob `c610f073b47939acf15e7e76aad59883ac13fad4` matches the same path on main
`997e7beef8151160065df36b024bc8da5c989e93` exactly. It is an actual code lint
failure. No public API or lint flags were changed to suppress the diagnostic.

### Continuing adversarial finding: incomplete owner relation projection

The post-selection freshness repair rejects registry mutations after selection.
It does not authenticate the completeness of relations supplied before selection.
A real durable owner can register Conflict between two genuinely admitted,
signed factors before enumeration. A caller can then construct a structurally
valid graph using the correct nodes, vector and claimed owner source/profile
while omitting the Conflict edge. Candidate membership passes; the registry
digest is already current; a consistent two-factor portfolio with a recomputed
checksum can pass final exercise and reach the compiler. The complete sealed
owner projection provides the positive control and selects only one factor.
This is an API-boundary defect inside the canonical source-binding contract.
It is not explained away by the separate lack of Agentd KG-route composition.

The baseline tests actually executed at published source
`807df52331ae76fe84bf9ecf4f16031161f70868`, whose tree exactly matches local
baseline `7af3`. Two optimizer tests failed with an accepted omitted-edge
selection of factors A+B at token cost 2 and an `Exercise` decision for the
fresh, consistently recomputed conflicting portfolio. The compiler regression
also failed because it accepted both genuine signed payloads. The complete
owner graph positive control selected a legal single-factor portfolio. An
initial invocation selected zero matching tests and exited 4; it is not counted
as a reproduced counterexample.

Source `0314b2f2ac8219a28bf8cf20e85a382d068d2b6b` implements the repair in
private `canonical_source.rs` (228 non-test lines). A private boxed
`EnumeratedSourceV1` captures the complete sealed `PromptFactorGraphSourceV1`
and the factory's original registry snapshot digest. Validation requires that
original snapshot, registry revision/digest, model and generation vector;
changing public frontier fields and recomputing snapshot/candidate receipts
cannot replace the captured seal. Pricing/selection also recompute candidate
bindings, receipts and pricing-table consistency. This is same-boundary
consistency hardening, not independent Evaluator credential reauthentication;
review has not shown an additional dispatch exploit from candidate mutability.

Selection rebuilds the registered owner projection and requires every owner
relation and corresponding endpoint to match exactly, including support
revision, confidence, time validity and tombstones. Graphs claiming the owner
factor-source digest, registry digest or owner profile must equal the complete
owner generation. Supplemental relations with a distinct source/profile may
preserve temporal Requires/Dominates capabilities without removing or altering
a registered constraint. The check authenticates only registry-registered
Complements/Substitutes/Conflicts and their exact endpoints; it does not
authenticate every supplemental producer or source cut. Those still require
their own trusted read/projection owner composition.

Interaction digest v2 binds the sealed owner source digest. The original
supplied graph remains unchanged, rather than being silently merged, preserving
its generation digest for authenticated PairEvidence. Final exercise also
independently rejects current registered Conflicts with `RejectStale`, even for
consistent portfolio/checksum data. Canonical Substitutes retain signed numeric
PairEvidence semantics rather than becoming unconditional exclusions.

The private enumerated-source field intentionally blocks external Rust
struct-literal construction and exhaustive destructuring of
`EnumeratedPromptCandidatesV1`; public enumeration factory and method signatures
remain unchanged. This source-compatibility change requires review. The repaired
source adds six optimizer regressions overall and one compiler regression. The
first core run at `0314b2f2` actually executed 139 tests: 137 passed, and two
failed during fixture setup because support labels with spaces were invalid
`StableId` values. Those failures did not reach a production assertion. Final
source `6fe8237c493b9c2a52bf2b685da1d9b1b11333cd` changes only the two support
labels to valid hyphenated IDs, with all assertions, workloads and production
code unchanged. Independent source review found no residual reproducible defect
in this registered-owner binding scope. The exact-source retry passed all 139 core tests; the scoped native chain
passed 440 tests, including six compiler cases and 16 runtime cases. All three
actual failing baseline counterexamples now pass. These are new executions at
the final source, not coverage inherited from the historical 433 passes.
The final six-owner fix exited zero without changing any of 1,096 critical
inputs. Strict lint exited 101 on the existing main-identical large-enum-variant
diagnostic; the passing tests do not make that lint gate green.

The repaired-source runtime initially had four build failures with E0463/E0599
and zero test execution. Metadata inspection showed that the intelligence
archive referenced an optimizer dependency hash different from the current
optimizer unit. Standard unit-clean attempts did not resolve the mismatch, and
a successful intelligence library build with a different dependency/feature-unification unit graph was not counted
as Agentd execution. A normal rebuild of the matching intelligence library unit
with `--emit=metadata,link` resolved the observed dependency-hash mismatch; the
actual Agentd prompt-runtime command subsequently executed and passed 16 tests.
Its critical source hashes remained unchanged. The original stale-archive root
cause is unknown, so no cause is attributed to code, disk, deletion or a source
file timestamp change alone. The failed builds remain in the evidence history
rather than becoming passing runtime receipts.

The earlier small performance change in source `2be1a1d66e0e235818d0e6a7fc3705e6d5372e00`
removes duplicate shape-string allocation and computes node kind/payload digests
once per canonical node. Each support is still validated, exact shape equality is
required and original digest framing is preserved. Full source reconstruction,
predecessor/publication validation and the selected complete-generation writer
remain unchanged. Independent review of this memory refinement found no new defect; its
memory library run passed all 277 tests on that exact source. The timed-out capacity baseline predates this change,
so it cannot measure its latency improvement. Its 256 writes took 1,459.811
seconds, with the last write taking 10.502 seconds. Query and contention phases
completed; fresh reopen samples took approximately 12.8 seconds each before
the watchdog stopped the third sample. These shared-host partial timings are
not a completed capacity or approved target-host receipt. The workload retains
256 writes, 20 queries, ten contention rounds with four readers, and five reopens;
no count or assertion is reduced to obtain a pass.

The subsequent refinement at source `c3056c379e5a272bb8c3037b4608f5d4341c0c01`
reuses the existing support sort for adjacent duplicate-identity rejection and
borrows canonical node/edge identities during validation. Every support remains
validated before tombstones are removed, and the existing duplicate test now
proves that a tombstoned duplicate cannot bypass rejection on a node or edge.
Complete sorting, digest framing, lineage, predecessor/publication checks and
the durable writer are unchanged. Two private cognitive correction/outcome
helpers now take named input values; their transaction bodies, error order,
owner fencing and replay checks are unchanged. The newly wired signed adapter
and graph fixtures return explicit errors without removing their assertions.
Scoped fix also removes two unnecessary clones. This historical source passed all
133 core and 277 memory tests, five compiler-delivery tests, the explicit crash
and history workloads, and 16 prompt-runtime tests, with unchanged before/after
source hashes. No capacity speedup is measured by
those correctness runs.

Ordinary blocking-ci run `36820078134` tested source `676a187` and merge
`4fed329` with the same tree. It was not green: Authority QA lacked two boundary
registrations and had malformed regexes, four Python SDK formatter tests were
out of sync with main's formatter CLI, and the Windows Bazel Clippy driver failed
to launch Python because its argument list was too long. All ten implicated
files match main `997e7be` exactly. No actual Windows lint result follows from
that launch failure. These existing aggregate failures are separate from the
executed KG library results; they were not suppressed or represented as passes.

Architecture run `36820967024` tested source `2be1a1d`. Its optimizer filter
actually passed all 43 tests. Agentd compiled 176 library tests, and the browser
filter passed three while filtering 173. The runtime-image gate then executed
zero matching tests and correctly failed its minimum-one requirement. The intended
`runtime_executable.rs` and its four tests are not declared in `lib.rs` and have
no consumer; the workflow, module, tests and crate root match main `997e7be`
exactly. Changing a selector cannot supply the missing composition. The seven
source-fence tests were compiled but were not selected or run by that remote
workflow; the later local source `c3056c3` ran and passed them as recorded above. The identical-tree
base-merge lane skipped native execution and required source-head success, so its
green job is not a second passing native receipt. The existing owner integration
failure remains separate from the new KG runtime regressions.

The later blocking run `36820967378` tested source `2be1a1d` and merge
`c4788d7`, again with identical source trees. Its observed failures also include
an existing redundant-clone lint in `hepta-intuition` and the `hepta-fleet` Bazel
target missing `MODULES.json` as compile-time data. All implicated source/build
files match main exactly. The [ordinary CI evidence](evidence/ordinary-ci-round3.json)
records the actual run status, command results, raw-log hashes and main-blob
comparisons; ordinary CI cannot replace the separate deep workflow.

Required CI retains the original cognitive recovery, crash, history, performance
and Agentd workloads. It expands scoped source truth to six owners and adds
intelligence compiler delivery, Agentd prompt-runtime library regressions,
dependency-lock consistency, scoped `just fix` and strict lint. Free-space receipts
supplement actual step logs; no workload or integrity check is relaxed to make CI
pass. Full-history FTS, canonical and runtime repairs require current-candidate
source-head and deterministic base-merge execution.

An earlier documentation candidate passed derived-index freshness, local
link/hash checks and detailed companion conformance, including 49 analytic
fixture tests. The updated guides require fresh consistency checks before their
final publication. These checks do not execute native code or establish product
acceptance.

Continuing independent review found the reproducible owner-relation omission
above after earlier kernel, temporal and runtime-source reviews. The repair is
implemented at `0314b2f2` and independent source review found no residual scoped
registered-owner binding defect; the initial core run has two recorded fixture-setup failures, repaired by label-only
changes at `6fe8237c`. The final exact-source native chain passed 440 tests, including the three
previously failing source-authentication counterexamples; six-owner fix
passed without source changes and strict lint failed on the main-identical enum
size diagnostic. That lint failure remains a separate gate. Product
integration, a true 4,096-node/32,768-edge canonical pilot, retention/startup
budgets, approved target-host acceptance and manual deep source/merge execution
remain distinct gaps. All five module-wide claims stay false:
`productionImplementation`, `productExecutionProved`, `independentAcceptance`,
`activation` and `release`. No finite passing suite proves that the module has
no possible further optimization or grants independent acceptance.

## Review and landing stages

Final documentation checks passed `refresh-derived --check`, module-document
verification with the development profile (40 modules/source bindings), and
`hepta-technical-closure.py verify-details` (40 designs, 253 named product-test
designs and 49 analytic oracle tests; no product execution). The separate
`implementation_contracts.py verify-bundle` returned 1 with
`kernel.operations: false source or deployment closure`: that row uses
`durable_source_implemented_product_execution_pending`, while the validator
accepts only its two older state names. The kernel row is identical to main
`997e7beef8151160065df36b024bc8da5c989e93`, retaining false product/deployment
claims; the validator blob `8821a91d2418a2c4744ed1952f50d616e6fdd3d9` is also
identical. This adjacent-owner/global vocabulary mismatch remains a failed
check, not a KG execution failure or a passing bundle receipt. No allowlist or
closure assertion was relaxed for this audit.

The accumulated candidate spans several owners and exceeds the repository's
preferred single-change size. Keep the repair commits reviewable by boundary.
The smallest independent first split is retained memory/entity FTS validation
and its corruption regressions in `cognitive_store.rs` and
`cognitive_store_tests.rs`: it requires no new prompt/runtime API or dispatch
authority. A split must rerun its scoped memory checks rather than inherit the
combined candidate's receipt. Kernel generation/query bounds and the cognitive
verified-query consumer form the next dependent stage. Durable prompt relation
ownership, canonical selection/expiry, staged runtime source fencing, and
qualification/documentation can then be reviewed as separate stages, with their
explicit source and test dependencies retained. No stage is merged or activated
by this audit.
