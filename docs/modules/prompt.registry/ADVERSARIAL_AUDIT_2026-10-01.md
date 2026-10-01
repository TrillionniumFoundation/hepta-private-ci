# prompt.registry adversarial audit — 2026-10-01

Follow-up source baseline: `1321ed2658501f9a296bb858e792f666d14a9a89`,
the head of [PR #1301](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1301).
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
The map gate remains authoritative and blocking; no unrelated source receipt
or production claim is promoted to make it pass.

The first-round readiness source job
[110118085578](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/36783140262/job/110118085578)
stopped at the prompt dossier digest drift described above. An additional local
repository-contract check exposed an inherited enum mismatch: the unchanged
`kernel.operations` profile declares
`durable_source_implemented_product_execution_pending`, while
`implementation_contracts.py` accepts only its two earlier implementation-state
values. The profile row and validator are unchanged from `main`; this is a
separate baseline gate failure, not a false prompt production claim.

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

The source/merge CI workflow now also runs ledger regressions and separate strict
owner/evidence and consumer lint before the unchanged blocking map gate. No
existing gate is waived, and no production or independent-acceptance flag changes.

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
The six unchanged invalid anchors in objective.compiler, utility.ndu,
cognitive.read, learning.artifacts, automation.taskflow and control.engineering
remain blocking repository-wide failures. The separate kernel.operations profile
state mismatch and inherited intelligence enum lint also remain open.

Independent read-only re-review of the repaired source and a separate docs/workflow
consistency review found no additional concrete scoped bypass or evidence overclaim.
This is convergence of the examined native invariants, not proof that no further
optimization can exist or that the missing product composition is complete.
