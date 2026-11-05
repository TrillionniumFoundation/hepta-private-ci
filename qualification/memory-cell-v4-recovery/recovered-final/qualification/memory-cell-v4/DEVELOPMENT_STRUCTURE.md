# V4 structural controller development

V3 and its results are frozen. Its formal structural outcome remains 4/20 strict
cases, convergent 4/5, and both all-flow and convergent-all-seed gates false.
Seed 331 is explicitly reused for development; it is never fresh v4 evidence.
V4 formal seeds 401, 409, 419, 421 and 431 must not run before root freezes source
and protocol. Permitted development seeds are 8011, 8017 and 331.

## Candidate and accounting design fixed before the first development run

Each write trains its own global K=1 model. If its selection MSE exceeds .25,
the same owner also trains complete K=4 raw and normalized-energy partitions.
They use the same real fitting routine as independent fixed controls. A complete
partition is allocated under 4096 serialized bytes before its aggregate domain
retention is assessed. No intermediate two-cell partition must be feasible.
All candidate bases, rejected candidates, selected models and ledger metadata
are retained and charged. No fitted baseline artifact is provided to the owner.

Fixed K=1/2/4 controls can relearn partitions and ranks at every write and choose
the best K with whole-flow selection hindsight. Natural fixed costs are saved
before separately executing the matched-work repetitions. Prices remain .02
for work and .02 for retained state, using the same normalization as v3.

The new scope is changing-flow quality gain of at least .05 normalized by
max(fixed MSE,1), lower priced loss than both natural and matched fixed controls,
and retention. Static quality diagnostics permit at most .01 normalized MSE
regret against either control; the natural priced-loss diagnostic limit is
1.10. These bounds do not imply strict zero-cost improvement and never replace
the old v3 gates. Absolute and literal relative quality differences are retained.

Other fixed settings: 256 rows, 32 columns, four maximum cells, .25 selection
fraction, 12 k-means iterations, domain retention bound 1.02 times the global
selection error plus .25. The candidate order is [K1, K4], not a tuned choice
based on held-out outcomes. Shared raw replay, schema, selection addresses and
80-byte owner bindings are counted separately from the 4096-byte model cap.

## Workloads

The original heterogeneous, convergent, stable-lowrank and random constructions
are retained with new seeds. A separately seeded recurrent_regimes flow switches
shared rank-six -> four local rank-two -> different shared rank-six -> newly
permuted four local rank-two. The latter changes row and column layouts and has
four writes, rather than a one-way convergence. It remains a synthetic numeric
family and does not imply a new natural-language memory type.

An independent pair-merge mechanism starts from four actually fitted cells
sharing a rank-two source, trains a three-cell candidate by merging exactly one
pair, and checks retention, serialized budget and coordinate migration. Parent
training and new training are both charged. A storage/quality tradeoff in this
case is not counted as dynamic-policy net benefit or global consolidation.

## First actual development run: seed 331

Artifacts and exact executed source copies are retained at
validation/structure-initial-dev-331. The supplied Git identity is the parent
commit; the saved executed-source hashes identify the uncommitted v4 source.
The run completed without changing thresholds, candidate order or prices.

| Flow | Adaptive MSE | Best natural fixed MSE | Natural priced-loss ratio | Scoped result |
| --- | ---: | ---: | ---: | --- |
| heterogeneous | .002258429 | .002258429 | 1.090997 | bounded static diagnostic passes; no strict gain |
| convergent | .111319366 | 8.428112871 | .611187 | dynamic passes |
| recurrent_regimes | .106965334 | 17.553766397 | .551297 | dynamic passes |
| stable_lowrank | .025649298 | .021455073 | .418088 | bounded static diagnostic passes; error is worse |
| random | 1370.918857880 | 1370.918857880 | 1.037946 | bounded static diagnostic passes; added cost |

The previous seed-331 reachability failure is repaired in this development
example: the owner trains and chooses four cells directly. No held-out claim
follows. Convergent cell counts are [4,1]; recurrent counts are [1,4,1,4].
Strict improvement on every flow remains false.

The pair merge actually performs one four-block parent fit and one three-block
merge fit. Serialized bytes fall 2164 -> 1900; hidden MSE rises .221971286 ->
.226165511. All 6199 hidden coordinate reads match after serialization; 192 raw
row labels change. This is a measured lossy storage tradeoff, not a free merge.

Subsequent fixes before broader development are restricted to API validation,
testability and evidence checks unless a new policy decision is explicitly
recorded. The initial executed source and results must not be overwritten.

## Broader development and independent audit

validation/structure-dev-8011-8017 retains both additional development seeds and
their executed source copies. The policy, candidate order, prices and thresholds
were unchanged. All four dynamic cases and all six bounded static diagnostics
passed; strict all-flow improvement remained false.

| Seed | Flow | Adaptive MSE | Best natural fixed MSE | Natural priced-loss ratio |
| --- | --- | ---: | ---: | ---: |
| 8011 | heterogeneous | .001616815 | .001616815 | 1.093026 |
| 8011 | convergent | .103711212 | 2.771184889 | .727505 |
| 8011 | recurrent_regimes | .089852013 | 3.860965793 | .703515 |
| 8011 | stable_lowrank | .027000808 | .026030719 | .412971 |
| 8011 | random | 1368.632012935 | 1368.632012935 | 1.038333 |
| 8017 | heterogeneous | .002096098 | .002096098 | 1.090916 |
| 8017 | convergent | .084742480 | 4.908931381 | .693640 |
| 8017 | recurrent_regimes | .106758859 | 4.817904514 | .874333 |
| 8017 | stable_lowrank | .028055466 | .025153176 | .375964 |
| 8017 | random | 1357.554498549 | 1357.554498549 | 1.038265 |

Both additional pair-merge cases really trained 4 -> 3 blocks and reduced the
model from 2164 to 1900 bytes. Hidden MSE was .229911075 -> .223120453 for 8011
and .221380200 -> .223960013 for 8017. A byte saving is therefore not described
as guaranteed quality improvement or as covering training/maintenance cost.

Five mechanism integration tests passed before final formatting. They cover the
331 failure, own candidate training, migration/consolidation, natural-versus-
matched accounting, paid random-control quality, a real pair merge, and rejecting
an invalid parent before creating artifacts. The additional audit regression
uses real trained artifacts and corrupts consistently copied summaries to check
that hidden metrics and work totals must match the independent reconstruction.

The read-only API is v4.structure_audit.audit_structure(run_or_stage, output=None,
allow_development=False). Audit output must be outside RUN. It loads and regrades
every selected candidate and hidden/domain result, checks serialized budgets and
owner bindings, independently sums recorded fit costs, verifies whole-flow
selection choices, and recomputes both new gates and the historical boundary.
It also checks that pair-merge parent training and retained parent bytes remain
charged. It performs no training or clustering rerun.

Both existing development runs passed read-only audits: 288 consumed files for
331, 570 for 8011/8017. Their snapshots predate the new auditor, so the audit
explicitly records missing historical auditor source bindings; no retrospective
formal qualification is claimed. New source snapshots include the auditor and
frozen parser/ledger helper identities. Original fit execution, diagnostic
operation traces and historical wall time are not independently authenticated
by a read-only artifact audit.
