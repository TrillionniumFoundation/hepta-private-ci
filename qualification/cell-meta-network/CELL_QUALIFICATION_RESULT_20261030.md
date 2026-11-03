# Final cell qualification: native language, independent maintenance and freshness

The cell candidate based on `ca77c10b25cf6eb1de91537c938a2beba597c886`
has now passed the native bilingual parity, actual bilingual owner, independent
Semantic/Skill maintenance, and request-local federation pool gates below.
These measured results supersede the pending qualification status in the
[earlier review snapshot](CELL_REVIEW_20261030.md). The frozen language model,
calibration, datasets and completed experiments were not changed after their
held results. This is candidate qualification; it does not assert a deployed
daemon performing bilingual online learning or an autonomous general agent.

## Gate outcomes and their distinct scopes

| Gate | Observed result | What it establishes |
|---|---|---|
| Frozen Python language comparison | New 400/400; expanded old 381/400 | Better known-request head coverage inside the shared declared grammar |
| Rust head and live encoder parity | 400/400 head parity and 400/400 live parity | The frozen model behaves consistently in the native implementation |
| Actual bilingual owner path | 10/10 cases; six accepted, four abstained | MiniLM, Rust head, signed selected release and canonical owner reads work together in the qualification fixture |
| Independent Semantic and Skill maintenance | Each 8/8 corrected/retained reads; other model bytes unchanged | Source correction, clean retraining, explicit publication/selection and withdrawal preserve the per-model dependency contract |
| Federation/final-use selected tests | 19/19 passed, including six new pool guards | Connection reuse meets the existing 16-peer two-second fixture without removing fresh preflight/postflight checks |
| Equal-budget structure study | Rank increase 377/384; split 355/384 | This split configuration does not justify automatic activation |
| Two-worker warm locality control | Local median 44.735 ms; distributed 46.178 ms | This small matched comparison does not establish a reliable distributed advantage |

The language and maintenance rows are separate experiments. The maintenance
test deliberately uses `PolicyResolver`, whose digest names
`owner-learning-qualification-no-language-claim`, and previously frozen feature
rows. Its success must not be combined with the bilingual owner fixture into a
claim that one deployed natural-language service already learns online.

## Frozen bilingual candidate: native parity and actual owner

The candidate model SHA256 remains
`5b6bec4e6f13958d3572bee68b03977fbc7064fac4be47959f1b7f0b1ecc8522`;
the protocol SHA256 remains
`21c109a75b1c98f52fcc567e1f59a5cad56300c95e754007e09bc6cec1165d24`.
The run root is `/tmp/hepta-cell-bilingual-continuation-20261030-01`.

The native evaluator explicitly checked its result fields, rather than treating
exit code zero as parity. Semantic, Skill and Compose each returned 32/32
correct known requests. All 304 unknown requests abstained with zero false
accepts. Head parity and live parity each covered all 400 rows. The encoder
started once, made 96 requests, validated all 96 and truncated none.

Native evaluation wall time was 5.612794 s. The report separately measured
3.368050 s encoder startup, 0.039286 s head loading and 1.751619 s query loop.
Its outer child CPU counter was 0.681855 s; encoder requests reported
1.489023 s CPU. These are distinct attribution windows and are not added to
produce an asserted process-tree total. Startup CPU and complete descendant
resource attribution are not established by that sum. The evaluator binary
was a debug qualification artifact of 809,984,504 bytes, SHA256
`df4efbff2a245987323081c86bee8e21edad77d7083dc3ac99cc1eab9deb021b`;
this is not evidence of a small release deployment footprint.

The subsequent `inventory_semantic_actual_owner_path` ignored test passed all
ten v2 cases. English and Chinese policy reads produced reserve 11, pack 3 and
limit 14; procedure reads produced `[5,4,3,6]`; composition produced 13.
Negation, an extended unknown entity name, an unknown workflow and a request
that added deletion all abstained. The actual encoder started once, attempted
and validated six requests, and truncated none. The selected bundle and owner
were used for each accepted read; rejected language did not grant an effect.

The test execution was 8.395 s. Its enclosing command measured 13.659268 s wall
and 5.511412 child CPU seconds. Encoder startup was 4.096638 s and request CPU
was 0.118306 s; these are nested/component observations, not extra totals to
charge again. The report contains `all_expected=true`, canonical owner cut
`9be4f30a46ea309ac85a0d606bf1fa7eaad5ca040c2e7137e8829818c4ae0dec`
and encoder configuration SHA256
`86be459c7ee6c875e05ab988b910d8c13a3950e2e46759fe21fc656778c6a97e`.

The evidence is bounded to 51 declared templates and registered aliases. The
304 unknowns are rejected by the shared grammar, so their zero false accepts
are not independent evidence of learned open-domain rejection. Native parity
replays the frozen held reference to check implementation; it creates no new
statistical sample and was not used for tuning. The historical 480-case set
remains intact, but its 120 known rows were explicit training replay and no
longer supply candidate generalization evidence. Base wording families and
texts are separated across phases; boundary perturbation operators/family
labels are shared. See the [original bilingual result and costs](../memory-cell-adapters/BILINGUAL_RESULT_20261030.md).

## Independent maintenance: actual training, publication and withdrawal

`inventory_native_retraining_owner_cycle` passed for both Semantic and Skill
in one 22.355 s test execution. For each kind it corrected one canonical row,
observed that the old affected model became stale, and verified that the other
model remained usable. It rebuilt only the affected model, published generation
2, required explicit selection after publication, and read the corrected row
plus seven retained rows successfully. The other model's artifact digest stayed
unchanged. Withdrawal then produced `status=stale` and a null value.

| Actual rebuild | Semantic | Skill |
|---|---:|---:|
| Current canonical rows | 8 | 8 |
| Corrected / retained rows | 1 / 7 | 1 / 7 |
| Fixed steps / batch size | 600 / 32 | 600 / 32 |
| Sample presentations | 19,200 | 19,200 |
| Adapter / head parameters | 3,072 / 4,620 | 3,072 / 10,780 |
| Total trainable parameters | 7,692 | 13,852 |
| Training receipt CPU seconds | 2.629035 | 2.464351 |
| CPU including checkpoint/export | 2.647984 | 2.479602 |
| Wall including checkpoint/export | 3.243773 | 2.493542 |
| Exported native artifact bytes | 62,792 | 112,069 |

Both used seed 731, a clean rank-4 initialization, trainable heads and pinned
encoder feature bindings. The outer trainer timer starts after imports, input
parsing/validation, feature construction and thread configuration. It covers
model construction, fitting, checkpoint/export and the retention diagnostic;
it does not measure Python startup, all fixture work or complete service cost.
The smaller fit timer is nested inside it. The 8/8 diagnostic is fit/retention
coverage on these eight canonical rows, not a held generalization result.

The Semantic result's new native artifact digest is
`7de433cf0289b3326e514cab2ebed11287ddae04ee88eaa9edeaed8cc3f12a6f`;
the Skill result's is
`09840ad501785152162cac2690269bb87f80c3698b93b10d8a8b1bec17184607`.
The complete per-kind training cuts are respectively
`d7884a13d0a9067793438e53066763097d46d0fea0c83181cb7fba9766508c69`
and `c554528a44dadb8c3dc8e8924090a24779b4bc8ddb1f4245ca0f2170aa6139ce`.
Original raw result identities, before the review copies' extra newline, are:

- Semantic `RESULT.json`: 10,562 bytes, SHA256
  `ab200ecaa537a1ab782c653de752a2199d6b08ee8cda3c057ec266d902f43e38`.
- Skill `RESULT.json`: 10,723 bytes, SHA256
  `a87eccb167f7dec7a48c249d9de792f426a17818c11997886ca9bbfbbc018d33`.

The complete source dependency set belongs to the model, not only to the
address currently queried. Publication still validates both lineages, and
composition requires both valid models. Query binding, selected release and
acquired owner-cut revalidation remain enforced. Release validation followed
by an awaited owner read is not an atomic cross-store authorization token;
the final action owner retains authority over effects.

## Federation budget repair and preserved failed attempts

The initial broader run completed 559 of 561 tests successfully. One failure
required the built Codex App Server test executable environment. The other had
zero completed peers in the 16-peer fixture, even after explicitly closing the
fixture writer pools. Actual phase diagnostics showed successful data reads
followed by fresh connection setup/verification that could not finish before
the unchanged two-second deadline. These failures and unsuccessful fixes remain
in the attempt history.

The final candidate reuses each request's already opened read-only pool while
repeating integrity, owner, schema and current capability-head queries before
and after transport. Read transactions do not survive across transport. Unix
main-database pathname device/inode checks reject observed replacement or
symlink redirection; they are not descriptor-bound recovery or an ABA witness.
The [freshness implementation note](FEDERATION_POOL_REVALIDATION.md) records
the exact scope and six new regressions.

The selected final `federation-pool-reuse-v5` run passed 19/19 tests in
34.464 s test execution. It included the unchanged 16-completed/one-truncated
peer assertion under the original two-second budget, the six new pool guards,
and `memory_prediction_reaches_real_untrusted_context_and_final_use_races_stop_before_effect`
with the required built App Server configured. Its outer command measured
182.673038 s wall and 304.099412 child CPU seconds, including compilation.
Those are build/qualification costs, not per-request latency. The whole
original 561-test group was not rerun after these scoped fixes.

The temporary production phase diagnostic was reversed before the final
pool change. The first pool patch was rejected atomically because its local
base had a different trailing newline; no portion of it was applied. The
exact-base replacement patch SHA256 is
`d8c665d43b8d991e1a9201ab0f097925fefc8241ec21ed9c688dc1a7dbce9663`.
The test-only coverage message and explicit fixture close remain. A successful
final run does not turn earlier failures or setup time into zero cost.

## Structure and physical distribution decisions remain unchanged

The [equal-budget study](BUDGET_RESULT_20261030.md) still favors rank increase
over this dynamic split: 377/384 versus 355/384 held correct. Fixed experts
reached 368/384; pruning reached 120/384. Positive conditional local credit did
not predict the best final task result. Two seeds, reused held expressions and
partial cost accounting do not establish a universally optimal structure.
Automatic splitting and pruning remain disabled.

The [matched warm locality result](LOCALITY_REBOUND_RESULT_20261030.md) retained
all sixteen trials and matched two concurrent workers per arm. The local and
distributed task medians were 44.735129 and 46.177961 ms; the paired median
distributed-minus-local difference was +1.527128 ms. The paired mean was
-2.388980 ms, and distribution was faster in three pairs and slower in five.
These mixed, small observations do not justify a general speedup claim.

The three replacement workers all have complete direct-child lifecycle
receipts and Runtime `timed_out`/124 terminal results after their 240-second
holding budgets. Their worker CPU totals sum to 1.468332 s and wrapper CPU to
4.440767 s across the entire lifetimes. The holding time is not task latency;
direct-child reaping is not proof of arbitrary descendant/cgroup cleanup.
Original transfer, prior 900-second worker lifetimes, failed dependency setup,
new startup, warmup, coordinator and terminal costs remain separately visible.
The result is a warm source-integrity task comparison, not a cold-cost,
inference-speed or distributed-learning result. `full_cost_exact=false` remains.

Cells should therefore remain logical parameter, memory and routing units
within shared runtimes. A logical split need not clone an OS process, encoder,
database or full agent harness. The new positive gates support bounded language
coverage, independent maintenance and lower validation setup overhead. They
do not demonstrate spontaneous general intelligence, indefinitely beneficial
cell growth, or the replacement of the whole Codex execution contract.

## Receipt provenance

The final review used `NATIVE_EXECUTION.json` plus its checked native result,
`bilingual-actual-owner-RESULT.json`, the two original-digest maintenance
results above, and the two-stage `pool-and-bilingual-owner-v5.json` command
receipt. Review copies are not all byte-identical to remote originals; where
an original digest is not available, this note makes no such identity claim.
The earlier model/protocol hashes and exact experiment raw bytes are preserved.
Commands, source definitions and code review are kept distinct from measured
passing outcomes. Formatting source or prose after qualification does not
rewrite any frozen artifact or create a new held evaluation.
