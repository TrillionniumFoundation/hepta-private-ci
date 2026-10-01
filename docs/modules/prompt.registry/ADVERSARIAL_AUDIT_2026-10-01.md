# prompt.registry adversarial audit — 2026-10-01

First follow-up source baseline: `1321ed2658501f9a296bb858e792f666d14a9a89`,
an earlier head of [PR #1301](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1301).
The original `main` baseline remains `a126987b84737dbc2ee2592442a314117bddb4a2`.
The [2026-09-30 audit](ADVERSARIAL_AUDIT_2026-09-30.md) preserves the first
repair round and its local resource failures. This record separates subsequent
CI evidence from new source changes. It grants no production, activation,
independent acceptance or release claim.

## Latest development documentation

The module has a detailed [technical guide](TECHNICAL.md), an
[implementation dossier](../../../qualification/module-execution-dossiers/detail/prompt.registry.md),
an implementation profile and a source implementation map. They document native
APIs, final-use mutation binding, V1–V3 persistence, locking and commit boundaries,
recovery, resource limits, test locations and the partial Agentd consumer path.
Target product contracts and unproved deployment capabilities remain separate
from implemented native entrypoints.

Follow-up inspection found a documentation regression: the first round changed
the dossier without updating its `DETAILS.json` SHA256. The old hash matched
`main`, but no longer matched the revised dossier, so readiness CI correctly
reported `prompt.registry: design digest drift`. The follow-up synchronizes the
exact final dossier bytes and retains the existing false acceptance/execution
claim fields. Blanket source-status wording was narrowed to identify actually
executed candidate checks; intelligence delivery test references were added.

## Verified first-round CI execution

GitHub Actions run
[36783140332](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/36783140332)
ran the following checks before its unrelated mapping gate failed:

| Candidate | Identity | Registry | Optimizer | Intelligence prompt | Agentd prompt |
| --- | --- | --- | --- | --- | --- |
| [Exact source](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/36783140332/job/110118083781) | `1321ed2658501f9a296bb858e792f666d14a9a89` | 67 passed | 32 passed | 9 passed, 73 filtered | 9 passed, 160 filtered |
| [Deterministic merge](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/36783140332/job/110118084135) | `b94054750b10dddb24ca60fb62806e6726b1df67` | 67 passed | 32 passed | 9 passed, 73 filtered | 9 passed, 160 filtered |

The registry/optimizer command was
`just test --locked -p codex-hepta-prompt-registry -p codex-hepta-prompt-optimizer`.
The focused consumer commands were
`just test --locked --lib -p codex-hepta-intelligence -E 'test(prompt_)'` and
`just test --locked --lib -p codex-hepta-agentd -E 'test(prompt_)'`.
The owned Rust formatting step also passed in both lanes. The later strict KG
lint step was skipped after the map gate failure; no lint pass is inferred from
the successful tests. These results establish execution for the named first-round
candidates, not later edits or target-host acceptance.

The prior local Agentd test/lint interruptions remain historical resource
failures. The CI results above subsequently executed the nine focused Agentd
tests successfully; they do not retroactively make the interrupted commands pass.

## Repository-wide gate failures and attribution

The development-docs jobs and final KG mapping gate rejected seven unchanged
module anchors: `objective.compiler`, `utility.ndu`, `cognitive.read`,
`learning.ledger`, `learning.artifacts`, `automation.taskflow` and
`control.engineering`. In the local branch-history checkout their historical
objects were missing (`git cat-file` exit 128). CI fetched all branch/tag refs,
resolved those objects and rejected them as non-ancestors of the tested candidate
(`git merge-base --is-ancestor` exit 1). These are different observations of the
same inherited invalid candidate bindings, not prompt.registry test failures.
The qualification map gate was blocking for those historical candidates; no
unrelated source receipt or production claim was promoted to make it pass.
The later main-policy integration and current development-profile checks are
recorded below rather than inferred from these earlier failures.

The first-round readiness source job
[110118085578](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/36783140262/job/110118085578)
stopped at the prompt dossier digest drift described above. An additional local
repository-contract check exposed an inherited enum mismatch: the unchanged
`kernel.operations` profile declares
`durable_source_implemented_product_execution_pending`, while
`implementation_contracts.py` accepts only its two earlier implementation-state
values. At that inspection the profile row and validator were unchanged from
the original main baseline; this was a separate gate failure, not a false prompt
production claim.

## Follow-up bounded-input repair

Protocol factor-dimension validation previously cloned the complete caller vector
and serialized it before enforcing its 8,192-byte encoded bound. Admission shape
validation similarly copied untrusted identifier strings before enforcing the
stable-ID bound. The follow-up validates borrowed inputs first, accumulates exact
canonical JSON byte cost with checked arithmetic, and checks dimension ordering
without an owning vector clone. Public APIs, wire versions and existing shape
errors remain unchanged. New protocol fixtures cover encoded sizes 8,191, 8,192
and 8,193 bytes, plus full-size round-trip and reversed/duplicate ordering. Their
source location is `protocol_bounds_tests.rs`; source presence alone is not a
pass receipt for the new candidate.

## Exact-cut recovery check

The ordinary constructor has no external freshness input, so a complete older
internally valid backup could restore a pre-revocation image. The follow-up adds
`PromptRegistryRecoveryAnchor`, `recovery_anchor()` and
`open_state_dir_with_recovery_anchor(...)`. The anchored path requires existing
selected state and exact equality of revision, lifecycle/revocation frontiers
and semantic digest, rejecting a different cut before migration or payload-tail
cleanup. It never falls back to initializing missing selected state.
Missing selected state cannot create a directory or lock marker. An existing
legacy image may create its missing lock marker while obtaining ownership;
cut rejection still preserves metadata and payload bytes. Recovery fixtures
cover old backups, equal-revision semantic forks, missing state, mismatch before
tail cleanup/migration, matching V1/V2 migration and poisoned-owner capture.

The same pass found that a failed parent-directory sync left a directory behind,
and a later ordinary open could skip syncing its name because it already existed.
Open now repeats the parent fence for existing directories too. The regression
injects a first parent-sync failure and verifies that the retry attempts it again.
Independent re-review then found a second parent-fence defect: deriving the parent
from the supplied path can select the wrong directory for `.` or
`owner/child/..`. The final implementation opens `..` from the validated owner
descriptor. `owner_alias_path_syncs_its_actual_parent_directory` checks actual
parent and owner device/inode identity through an alias path. No API or wire
version changes are needed for this correction.

This closes a native verification seam, not independent witness provisioning.
An anchor copied from the suspect backup cannot establish currentness. The host
must independently authenticate and retain a new cut for each acknowledged
mutation; this exact-cut API cannot prove arbitrary later-prefix extension.
Agentd still uses the ordinary constructor and has no trusted anchor provider or
cross-domain acknowledgement/recovery procedure. Those product gaps remain.

## Optimizer provenance and runtime time ordering

The first compiler repair sealed actual registry delivery bytes, but upstream
pricing and selected-portfolio fields were still public and lacked an internal
record of verified construction. A caller could change those fields and rehash
public receipts without executing the signed pricing/selection path. The follow-up
adds private process seals to priced candidates and selected portfolios, full
candidate/receipt/model/profile validation, verifier-objective matching and public
`validate()` methods. Selection, exercise and registry compilation enforce those
checks. Callers cannot reconstruct the private seals from wire fields; there is
no serde reconstruction route. All authority remains deny-only.

Enumeration metadata now has its own private process seal too. Its omitted count
and snapshot can no longer be changed and publicly rehashed to hide omissions or
claim another source enumeration. Pricing validates this seal before signed
completeness verification. The regression is
`rehashed_enumeration_metadata_cannot_hide_omissions`.

Independent re-review then found that selection could combine a priced set with
pair evidence verified for another objective or trust epoch. The pricing seal
now includes its original verifier trust digest, and selection requires that same
objective and trust snapshot. The regression is
`selection_cannot_mix_pricing_with_another_objective_or_trust_epoch`.
Current trust/revocation refresh at exercise or physical send remains separate;
sealed prior verification does not authenticate a permanently current trust state.

A later independent probe found a concrete freshness escape: evidence admitted
at time 100 with expiry 200 could still be selected at 201 on the no-pair path;
known signer revocation at 150 could similarly be crossed without changing the
trust snapshot. The optimizer now seals verification time and the minimum
evidence deadline, and selection requires its current time to remain within that
half-open validity window. The ledger dependency adds
`VerifiedLearningEvidenceV1::valid_until_unix_ms()`, which converts inclusive
signed/principal expiry to an exclusive endpoint and caps it by known revocation.
Saturating conversion conservatively excludes `u64::MAX` where no exclusive
successor exists. Portfolio validity cannot exceed any completeness/pricing/pair
evidence horizon, requested horizon or selected realization expiry. Privately
sealed selection time also rejects exercise-time rollback as `RejectStale`.
This preserves ledger/host evidence ownership and does not refresh a later changed
trust snapshot at physical send.

The added optimizer fixtures are
`selection_obeys_pricing_verification_time_and_exclusive_horizon`,
`pair_evidence_expiry_caps_selected_portfolio_horizon` and
`exercise_cannot_use_a_portfolio_before_selection_time`. Dependency coverage in
`signed_evidence_horizon_tests.rs` checks inclusive expiry conversion, known
future revocation and conservative saturation. These source references do not
claim execution for the final edited source candidate.

`canonical_signed_pricing_tests.rs` adds
`actual_signed_pricing_preserves_expiry_and_known_revocation_through_selection`,
which executes durable registry enumeration and actual independent generator/
evaluator signatures before pricing and selection. Signed expiry 200 yields
deadline 201; a known revocation at 150 yields deadline 150. The test admits the
last valid instant, rejects the cutoff and rejects time 99 before verification.
It protects the real construction path alongside the mutation-focused fixtures.

Runtime journal validation also accepted recorded dispatch at/after the staged
deadline and terminal observation before dispatch. A shared validator now requires
dispatch strictly before the deadline and terminal time greater than or equal to
dispatch, at commit and applicable staged-record recovery. This validates recorded
timestamps; terminal-versus-dispatch ordering is also checked after stage cleanup.
It neither authenticates wall-clock truth nor refreshes registry
revocation at provider send. Completion after a valid dispatch does not authorize
another dispatch.

`canonical_integrity_tests.rs` adds rehashed pricing/portfolio mutation,
candidate-receipt integrity and selected factor/token/expiry fixtures. Intelligence
adds `portfolio_expiry_and_utility_tampering_is_rejected_before_compilation`.
`prompt_runtime_integrity_tests.rs` adds exclusive-deadline and failed-claim
atomicity fixtures, pending-dispatch restore, terminal-order equality and
terminal-order restore after stage cleanup. Consumer fixtures now execute the
real signed pricing/graph/selection constructors rather than create portfolio
objects directly. Their test-only KG dependency is part of the source/lock update.

## Individual prompt-fragment bound

An admitted realization could declare more than the repository's 10,000-token
individual context-item ceiling even when the portfolio aggregate budget allowed
it. Compilation and compiled-output validation now reject a selected fragment
with declared `token_cost` above 10,000 using `PromptFragmentTokenLimit`.
`signed_prompt_fragment_declared_token_cost_obeys_individual_item_cap` covers
10,000 and 10,001 through real signed pricing and selection.

This is a declared-cost constraint, not actual tokenizer attestation. A fragment
declared above 1,000 tokens remains subject to the repository's P0 manual-review
requirement; the applicable review receipt is not supplied by the unit test.
Exact-tokenizer attestation and target qualification remain open evidence gates.

## Completion boundary

The module has substantial deterministic and durable native implementation and
real source consumers. Agentd opens the owner and attaches the runtime host, but
actual turn ingress still does not invoke enumeration or compilation/staging.
Final-use mutation APIs still lack a named authenticated product ingress and
deployed independent trust/scope configuration. Live dispatch still requires a
current registry/revocation check. Governed durable relations, bounded retention
and compaction, exact-tokenizer cost attestation, PIM-3 evolution and target-host
acceptance remain distinct work items. No percentage conceals these missing
composition and evidence gates.

## Follow-up local validation

The final logical repairs were tested in the working tree before the required
automatic lint fixes and formatting. These local results are not exact-head or
synthetic-merge execution receipts for a later commit.

| Check | Observed result |
| --- | --- |
| Registry package | 79 passed |
| Optimizer package, including real signed pricing expiry/revocation propagation | 42 passed |
| Learning-ledger package | 121 passed; 1 pre-existing ignored test skipped |
| Intelligence prompt integration | 11 passed; 73 unrelated tests filtered |
| Agentd prompt integration | No local test execution: dependency compilation of unchanged `codex-protocol` terminated with SIGKILL |
| Strict registry/optimizer/ledger lint, all targets | Passed with `-D warnings` |
| Strict intelligence consumer lint | Blocked by inherited `large_enum_variant` in unchanged `canonical.rs::CanonicalRunOutcomeV1` (528-byte versus 272-byte variants) |
| Agentd lint/fix | Attempted separately; dependency checking stopped in unchanged `moxcms` with `No space left on device`; no Agentd lint pass claimed |
| Bazel dependency lock update/check | Both passed; `MODULE.bazel.lock` unchanged |
| Detailed-design/dossier validators | Passed: 40 modules, 253 named designs and 49 analytic fixtures |
| Product caller proof | Passed: 49 boundaries, 27 protected files, 2,867 production Rust files; the four prompt mutation APIs still have no product callers |

The Agentd attempt ran with one build job, incremental compilation disabled and
the repository's `dev-small` profile. The shared 8-GiB cgroup recorded OOM kills;
the compiler's SIGKILL is a resource interruption, not a passed test or a source
diagnostic. The missing `pkg-config` prerequisite was separately resolved before
that attempt. A new token-cap fixture initially used equality on an error type
without `PartialEq`; its assertions were corrected, after which all eleven
intelligence prompt tests passed.

That source/merge CI workflow added ledger regressions and separate strict
owner/evidence and consumer lint before its blocking map gate. No existing gate
was waived and no production or independent-acceptance flag changed. The later
main-policy integration below preserves applicable checks under the explicit
development/qualification split.

The full `just fmt` command completed successfully. Its unrelated Python-baseline
rewrites were restored to keep the patch scoped; owned Rust formatting passed.
The four-package automatic fix completed; the separately attempted Agentd fix
remains resource-blocked as recorded above. No local Rust tests were rerun after
automatic fixes or formatting.

## Follow-up source-navigation checkpoint

The coherent source/docs checkpoint is
`7abcf31217ee6cff0d7742f8a63a980c3decd002`, tree
`83290941ef17a5ddc4aabcdcb6d53f7a13a06398`.
The changed source and two test-only dependency additions affect thirteen map
observations: prompt.registry, prompt.optimizer, intelligence.control,
runtime.agentd, kernel.operations, runtime.supervisor, knowledge.graph,
learning.ledger, learning.operator, learning.plasticity, platform.types,
memory.retrieval and memory.federation. Their exact current-source bindings are
refreshed without transferring execution evidence or changing claim flags;
the plasticity source-identity projection is synchronized too.

The changed learning.ledger map previously had an invalid inherited sourceBase.
Its current source receives a new real checkpoint binding. The original identity
and the two distinct local/CI rejection observations are retained explicitly in
`historicalInvalidSourceBase` as diagnostic metadata. This does not make the old
identity valid, repair its historical qualification or grant product execution.
At candidate `b440399a1210222505c086761a74b6efa507a359`, the six inherited
invalid anchors in objective.compiler, utility.ndu, cognitive.read,
learning.artifacts, automation.taskflow and control.engineering still blocked
repository-wide qualification. The separate kernel.operations profile failure
and inherited intelligence enum lint were also unresolved there. These are
candidate-specific historical observations; latest main subsequently changed
those source bindings and development verification policy.

Independent read-only re-review of the repaired source and a separate docs/workflow
consistency review found no additional concrete scoped bypass or evidence overclaim.
This is convergence of the examined native invariants, not proof that no further
optimization can exist or that the missing product composition is complete.

## Completed follow-up CI execution

Run [36796131356](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/36796131356)
completed both follow-up lanes against the original main base
`a126987b84737dbc2ee2592442a314117bddb4a2`:

| Candidate | Commit | Registry | Optimizer | Ledger | Intelligence prompt | Agentd prompt |
| --- | --- | --- | --- | --- | --- | --- |
| [Exact source](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/36796131356/job/110159888059) | `b440399a1210222505c086761a74b6efa507a359` | 79 passed | 42 passed | 121 passed, 1 ignored | 11 passed, 73 filtered | 13 passed, 160 filtered |
| [Deterministic merge](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/36796131356/job/110159887884) | `531b2f2c8bf772306eb397c4c322287e7b827811` | 79 passed | 42 passed | 121 passed, 1 ignored | 11 passed, 73 filtered | 13 passed, 160 filtered |

Both candidates have tree `6c037d10ce254c1e22f8ae2c8a9293928d01beab`.
Each lane executed 266 passing tests. Owned formatting, strict native
registry/optimizer/ledger lint and source-preservation checks also passed.
Strict consumer lint failed on the inherited
`hepta-intelligence/src/canonical.rs::CanonicalRunOutcomeV1`
`large_enum_variant` (528-byte Ready versus 272-byte alternatives).
The implementation-map gate and later KG checks were then skipped; they did not
pass. The enum's bytes are also unchanged in latest main.

These Agentd results establish execution of all thirteen focused tests for the
named follow-up candidates. Earlier local OOM and storage failures remain failed
or interrupted local attempts. The completed CI does not retroactively turn
them into successful commands, and does not prove execution of subsequent
main integration or repairs.

Historical readiness run
[36796131246](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/36796131246)
failed in source and deterministic merge
`e99dfccae64e83b69505fddb6ec1793c2eabe26e` on
`kernel.operations: false source or deployment closure`.
Historical development-docs run
[36796131311](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/36796131311)
failed in source and deterministic merge
`087ec6cfd5a9343497e083e5d4eebffec31ca75f` on the six non-ancestor
map bindings listed above. prompt.registry was absent from those failure lists.
These exact observations do not substitute for checking the later main-policy
integration candidate.

## Latest main policy integration and renewed audit

The next review began from source
`b440399a1210222505c086761a74b6efa507a359` and latest main
`997e7beef8151160065df36b024bc8da5c989e93`.
The local integration checkpoint is
`0e0723746d016d782f0813e1b2bda1f5fda6a9e3`, tree
`93abf5de9ce7f7b7c7a1dba3e6e6c765d0812cd1`; its second parent is that
latest main commit. Subsequent working-tree repairs are not part of this checkpoint.
Main's development policy distinguishes ordinary ownership/schema/path/reference
checks from explicit historical qualification. Automatic native checks use
dependency impact selection; deeper qualification workflows are reusable or
manually runnable. Workflow integration preserves that policy, the added ledger
and focused consumer tests, separate strict lint, and a single development-profile
map check. It grants no runtime authority or production/acceptance claim.

The integrated caller scanner and registrations preserve 49 boundaries and 27
protected paths while checking 2,900 production Rust files. This is caller-set
closure, not proof of a live prompt write or turn-ingress caller.

Renewed adversarial review found eight further source issues:

- V1 migration enforced collection capacity after traversing restored records.
  Malformed oversized input could therefore reach decoding before its record
  count was rejected. `migrate_v1` now rejects excess factor/realization count
  with `CapacityExceeded`, and excess bindings with `Corrupt`, before element
  decoding, index construction or imported-event synthesis.
- Final-use realization payload registration checked its byte ceiling after
  hashing and grant handling. `register_realization_payload_final_use_v2` now
  rejects empty or over-65,536-byte payloads immediately after owner availability,
  before factor cloning, hashing and grant claim. This preserves original grant
  claimability on shape rejection without refunding an entered effect's nonce.
- Knowledge-graph relation supports were not yet carried through selection's
  evidence-time and portfolio-expiry constraints. Future-dated or expiring graph
  support could authorize a longer-lived selected portfolio. The private
  `canonical_temporal.rs::graph_valid_until_unix_ms` now caps selection at the
  next relevant prompt-edge or endpoint-support transition, including supports
  not yet visible and overlapping support-cut changes. KG inclusive starts and
  exclusive ends convert from seconds to saturating millisecond boundaries.
  The sealed portfolio carries this cap into compilation and Agentd staging;
  unrelated and non-prompt facts do not shorten its lifetime. New graph
  generations still require current host revalidation.
- The public lower-level `compile_exercised_prompt_context_v1` could compile a
  fragment declared above 10,000 tokens. The registry-backed V2 compiler already
  rejected that value, protecting the current Agentd staging path. The lower
  compiler and `prepare_prompt_delivery_v1` now validate the sealed portfolio
  and enforce the shared `MAX_PROMPT_FRAGMENT_TOKENS = 10_000` bound before
  construction or receipt rebinding, with typed
  `PromptPipelineErrorV1::PromptFragmentTokenLimit`. They do not certify actual
  tokenizer cost or supply manual P0 review evidence.
- `exercise_v1` returned `NoIntervention` for an empty portfolio before enforcing
  its horizon and exact state/vector/model scope. It now rejects backdated or
  expired time and those scope changes as `RejectStale` before the empty branch.
  Only a current in-window empty portfolio yields `NoIntervention`; nonempty
  portfolios continue to current registry/lifecycle and value revalidation.
- V3 payload hydration accessed payload files before rejecting some metadata
  configuration, capacity and reference-shape failures. Ordinary and anchored
  constructors now pass configured capacity into `PayloadState::hydrate`; shared
  `validate_stored_metadata_bounds` rejects metadata headers/revision,
  configuration and count problems before sorting or payload open/read/hash.
  Reference count cannot exceed realization count, and borrowed reference-ID
  validation precedes index cloning. `ConfigurationMismatch`, `CapacityExceeded`
  and `Corrupt` are preserved. Bounded typed JSON decoding still happens first;
  semantic restore and anchor comparison still precede migration/tail cleanup.
- `prepare_prompt_delivery_v1` traversed caller serialization for selected-byte
  occurrences before the context compiler's aggregate byte ceiling was applied.
  It now rejects input above the existing 16-MiB ceiling after portfolio/receipt
  binding checks and request destructuring, before exercise, materialization,
  occurrence scanning, hashing or serialization copies. The existing
  `ContextCompiler(SerializedPayloadTooLarge)` classification is preserved.
- The source-byte occurrence helper used naive slice-window equality. A
  64-KiB needle consisting of 65,535 `A` bytes followed by `B`, searched in
  16 MiB of `A`, entails roughly `2^40` repeated byte comparisons in worst-case
  analysis. This was a source-complexity finding, not a measured runtime result.
  The private `prompt_serialization_search.rs::find_subslice` now uses KMP,
  with `O(H + N)` work per search and an explicit 64-KiB needle ceiling. Its
  prefix table is bounded to 512 KiB on 64-bit targets; first-match, cursor order
  and missing-occurrence semantics are preserved. Execution and benchmark
  evidence for this new Rust source remain pending.

The registry repairs add `durable_input_bounds_tests.rs` with
`legacy_record_capacity_precedes_decode_and_preserves_selected_bytes`,
`legacy_orphan_bindings_are_rejected_and_exact_capacity_remains_migratable` and
`payload_shape_rejection_preserves_registry_and_signed_grant_claimability`.
They cover malformed-record precedence, unchanged selected/unselected bytes,
exact-capacity migration and real signed zero/65,537/65,536-byte payloads.
The fourth registry fixture,
`v3_metadata_bounds_precede_payload_access_and_preserve_recovery_inputs`,
covers configuration, aggregate capacity, bindings/events/supersessions/reference
counts and a 257-byte reference identifier. Missing payload-file cases establish
typed rejection precedence; existing-file cases establish unchanged manifest,
payload and orphan tail under ordinary and anchored constructors.
The graph/exercise repairs add `canonical_temporal_tests.rs` with ten cases using real
durable enumeration, signed pricing, selection and exercise. Named regressions
include `future_conflict_caps_portfolio_before_the_edge_becomes_visible`,
`expiring_complement_cannot_preserve_its_pair_utility_past_support_expiry`,
`future_required_factor_outside_candidates_also_limits_the_cut`,
`second_transitions_have_exact_exclusive_millisecond_boundaries` and
`future_support_in_an_already_visible_relation_still_bounds_the_query_cut`.
The other cases cover endpoint visibility/expiry, unrelated facts and negative
or unrepresentable second bounds. All new-candidate execution remains pending;
the completed earlier tests do not establish execution of these repairs.

`empty_portfolio_obeys_the_same_time_and_scope_currentness_checks` creates a
genuinely signed zero-token-budget portfolio selected at time 1,000 with deadline
1,100. Times 1,000/1,099 return `NoIntervention`, while 999/1,100 and valid nonzero
state, vector or model-version drift return `RejectStale`. It awaits execution
for the repaired candidate.

The lower compiler adds `prompt_pipeline_fragment_bounds_tests.rs` with
`public_prompt_compiler_enforces_declared_fragment_bound_before_compilation`
and `public_prompt_delivery_checks_fragment_bound_before_receipt_rebinding`,
using genuine admitted and signed-selection portfolios at 10,000 and 10,001
declared tokens. These fixtures also await new-candidate execution.

The same file's third fixture,
`public_prompt_delivery_rejects_oversized_payload_before_occurrence_scanning`,
passes 16 MiB plus one byte without the selected bytes through a genuinely
signed preparation, requiring size rejection before missing-occurrence failure.
Its new-candidate execution is pending too.

Two further genuine public-path regressions,
`public_prompt_delivery_handles_maximum_repeated_prefix_missing_occurrence`
and `public_prompt_delivery_records_the_first_of_multiple_source_occurrences`,
cover that exact maximum needle/haystack missing case and the first occurrence
range at offsets 6–9. Their declared token costs do not attest actual tokenizer
cost. `prompt_serialization_search_tests.rs` adds three smaller cases:
`first_match_handles_prefix_fallback_and_overlapping_occurrences`,
`advancing_the_cursor_selects_the_next_non_overlapping_occurrence` and
`empty_or_absent_needles_preserve_missing_semantics`. None has been executed or
benchmarked for the repaired candidate.

Current local documentation checks pass the module-execution dossier verifier.
The detailed-design verifier initially stopped at an inherited `inference.control`
digest drift from latest main: selected dossier bytes hash to
`6838830412e0558d33b48d795dc4d5b0c2301af470d292e48d41cae24c243d82`, while its
DETAILS row recorded
`9b08c658eea5d069ed10123b4afb89a7f978511afba8e7bcb8018fe9b260c65f`.
Both were unchanged from the integrated main checkpoint. The prompt and inference
dossier hash rows are synchronized to their actual bytes without changing other
fields or transferring execution, qualification or production evidence. Rechecking
the detailed-design verifier then passed for 40 modules, 253 named product test
designs and 49 analytic fixtures. The module-execution dossier verifier also
passed; its product execution/runtime composition claims remain false.

## Latest main qualification attribution

Read-only inspection verified the complete non-shallow latest-main ancestry
(33,793 commits, without missing ancestry). Neither declared sourceBase SHA
below appears in the ancestry of `997e7beef8151160065df36b024bc8da5c989e93`.
The corresponding historical objects are locally missing; they were not resolved
or independently validated. Complete candidate ancestry establishes that these
declared identities cannot serve as ancestor bindings for this candidate, rather
than proving that their objects do not exist elsewhere.
The current affected qualification inventory has nine maps, distinct from the
six failures executed in the older follow-up CI:

| Inherited non-ancestor sourceBase | Maps on latest main |
| --- | --- |
| `8914a46dfc5984532f03dd2d559bf547ca4f1e69` | automation.taskflow, cognitive.read, control.runtime, runtime.codex, utility.ndu |
| `e8e81b7d541a81e75635cc1c0a713edaedb999d5` | control.engineering, inference.control, learning.artifacts, objective.compiler |

These nine histories are not renewed as if their invalid provenance had passed.
Current-source observations causally affected by the scoped repairs may receive
a new real source checkpoint, with execution/production/acceptance flags unchanged.
Development-profile navigation checks remain separate from historical
qualification, so their success cannot certify these sourceBase identities.

## Renewed local validation and resource interruption

The repaired working tree attempted
`just test --locked --offline -p codex-hepta-prompt-registry -p codex-hepta-prompt-optimizer -p codex-hepta-learning-ledger --cargo-profile dev-small`.
The shared memory cgroup remained at approximately 8,589,860,864 bytes against
its 8,589,934,592-byte ceiling. After more than ten minutes the build had only
reached prerequisite compilation (`version_check`, `generic-array`, `typenum`,
`proc-macro2`, `unicode-ident` and `quote`), and had executed no test cases.
The task's own tool session was interrupted and exited 130. This is an
interrupted build attempt, neither a passing suite nor a failed test result.
No source diagnostic or final-candidate test pass is inferred from it.

All twenty-two new fixtures remain execution-pending: four registry input/recovery
cases, ten optimizer graph/exercise cases and eight intelligence compiler/delivery/
search cases. The earlier 266-per-lane CI passes apply only to the named
`b440399a1210222505c086761a74b6efa507a359` and
`531b2f2c8bf772306eb397c4c322287e7b827811` candidates; they do not execute the
renewed repairs or integrated latest main.

Current development-profile document and implementation-map checks passed.
Detailed-design validation passed for 40 modules, 253 named designs and 49
analytic fixtures; the execution-dossier validator passed too. Caller-scanner
self-test and the renewed full scan passed across 2,901 production Rust files;
all four protected prompt mutation APIs still have empty product-caller sets. These checks
grant no production, runtime-composition, independent-acceptance or release claim.

The first required four-package `just fix` attempt was interrupted with exit 130
under the same resource conditions and emitted no source diagnostic. The first
formatting attempt lost its execution-backend connection; no formatting pass is
inferred.

The final scoped four-package `just fix` subsequently completed with exit 0,
compiling implementation and test targets without executing runtime tests.
Its output still contained the inherited intelligence `CanonicalRunOutcomeV1`
`large_enum_variant` and 29 pre-existing library-test lint warnings. Successful
automatic fix is not a strict consumer-lint pass.
The separate native command
`just clippy --locked --offline --profile dev-small -p codex-hepta-prompt-registry -p codex-hepta-prompt-optimizer -p codex-hepta-learning-ledger -- -D warnings`
passed with exit 0; the repository recipe supplies `--tests` automatically.
The twenty-two new fixtures compiled, but none was executed.

Fresh full-dependency consumer library strict lint stopped in unchanged
`hepta-context-compiler/src/v2.rs`, on `empty_line_after_doc_comments` at line 99
and `too_many_arguments` for `observe_delivery` at line 1,995. It did not reach
the intelligence package's own strict lint. A `--lib --no-deps` follow-up then
failed during `intelligence-eval` dependency compilation with
`No space left on device` (OS error 28). Neither is a fresh consumer-lint pass,
and the first failure is not attributed solely to the intelligence enum. The
enum and old library-test warnings were separately observed in the completed
automatic fix output.

Final `just fmt --base origin/main` completed successfully with exit 0.
Local Rust tests are not rerun after automatic fixes or formatting; later CI
must establish execution for its actual source and merge candidates.

Source changes are prepared as reviewable commits for the existing draft PR.
The eleven scoped implementation-map observations may be bound to a real
current-source checkpoint. That metadata work preserves the nine invalid
historical anchors and all production, execution, qualification and acceptance
flags; it cannot supply missing runtime test evidence.
