# Fixed-model reconciliation: TRAIN decoding gains with more joint errors

The single registered diagonal-support probe passed its predefined **TRAIN
joint-decoding** primary gate. At fixed log2, both model families improve exact
rho1.5 CE and joint success on the768 used inner TRAIN rows per seed. **Both-wrong
and wrong-agreement probability also increase.** Greedy accuracy is unchanged.
This is neither improved parameter training nor dynamic superiority to the best
static complete system. All prior CORE/r2 failures and consumed tests remain.

Rule/protocol source was committed at33ced6062ebf, freeze/execution at
cfb61bc44148 before the only probe. No alternative pT(t)/pI(i) rule was tested.
The exact local rule compares D(t)=p(t)q(t) and D(i)=p(i)q(i), i.e. support for
two consistent hypotheses. It does not know which is true. Twelve local hand
tests passed, including ties/zero/subnormal boundaries with exact float ratios,
joint pushforward, both CE-helper branches, asymmetric semantic indexing,
wrong-agreement partition, old-head greedy versus joint/marginal MAP, aliases,
caps and one final PNG render. See [protocol](PROTOCOL.md), [freeze](frozen-probe-v1.json)
and [unit log](../runs/content-reconcile-unit-v1-20261023.txt).

## Exact primary and visible correctness tradeoff

All six strong saved H/A models and original decoders are fixed; there is no
optimizer or fitting. All log2-minus-KEEP CE and joint-success seed means are
positive. Values below are exact finite-law expectations, conditional on those
models/inputs. Used inner rows selected the original models, so these are not
independent generalization/confirmation intervals or formal alpha expenditures.

| Family | KEEP CE | log2 CE | CE change | KEEP joint success | log2 joint success | Joint change |
|---|---:|---:|---:|---:|---:|---:|
| H | .96007703 | .98681543 | +.02673840 | 97.188375% | 98.742172% | +1.553796pp |
| A | .96517824 | .98783151 | +.02265328 | 97.462411% | 98.836522% | +1.374112pp |

| Family/seed | CE change | Joint-success change | Both-wrong change | Wrong-agreement change |
|---|---:|---:|---:|---:|
| H11 | +.02530959 | +.01527883 | +.00240004 | +.00262119 |
| H23 | +.02764053 | +.01597917 | +.00183738 | +.00213365 |
| H47 | +.02726508 | +.01535588 | +.00109124 | +.00128716 |
| A11 | +.02174027 | +.01329056 | +.00198613 | +.00224397 |
| A23 | +.02501409 | +.01549833 | +.00229573 | +.00251978 |
| A47 | +.02120546 | +.01243446 | +.00146550 | +.00173209 |

| Family/law | Only text correct | Only image correct | Both wrong | Wrong agreement | Semantic disagreement |
|---|---:|---:|---:|---:|---:|
| H KEEP | .963768% | .998649% | .849207% | .821519% | 1.990106% |
| H log2 | .113670% | .117330% | 1.026829% | 1.022919% | .234910% |
| A KEEP | .831412% | .860523% | .845655% | .819859% | 1.717730% |
| A log2 | .061545% | .064699% | 1.037233% | 1.036387% | .127090% |

Text/image marginal correctness also improves: H+.00703697/+.00672477;
A+.00604245/+.00578288. Thus the observed gain is not agreement alone. However,
both-wrong rises by.177622pp for H and.191579pp for A: the chance that at least
one modality is correct decreases. The rule turns many single-correct outcomes
into jointly correct outcomes and some into jointly wrong outcomes. It is not
a universal factual-correction mechanism.

Wrong-agreement absolute increases are .201400pp for H and .216528pp for A.
Per-seed head correctness changes and original-contract greedy observations:

| Family/seed | Text-correct change | Image-correct change | Greedy KEEP = log2 |
|---|---:|---:|---:|
| H11 | +.00641969 | +.00645910 | .98828125 |
| H23 | +.00765939 | +.00648240 | .98828125 |
| H47 | +.00703184 | +.00723280 | .99088542 |
| A11 | +.00557319 | +.00573123 | .98828125 |
| A23 | +.00715746 | +.00604514 | .98828125 |
| A47 | +.00539669 | +.00557227 | .99088542 |

### Same-decoder training-contribution decomposition

The descriptive A−H CE gap shrinks from +.005101206773 under KEEP to
+.001016082129 under log2, a difference in differences of −.004085124643.
The corresponding joint-success gap shrinks from +.002740352482 to
+.000943507585, difference in differences −.001796844897. H improves more.
These comparisons add no selection or readiness criterion. They do not establish
an independent content-parameter training gain, and contain no NDU comparison.

| Seed | A−H CE KEEP | A−H CE log2 | CE difference in differences | A−H joint log2 |
|---|---:|---:|---:|---:|
| 11 | +.00491648 | +.00134717 | −.00356932 | +.00117494 |
| 23 | +.00458117 | +.00195473 | −.00262644 | +.00190669 |
| 47 | +.00580597 | −.00025365 | −.00605962 | −.00025110 |

All absolute head/error cases, per-seed A−H and differences in differences are in
[descriptive-decomposition.json](../runs/content-reconcile-probe-v1-20261023/evidence/descriptive-decomposition.json),
computed only from saved summaries by the adjacent `describe.py`.

The unchanged original R recovery confirms
`R(y,k,k)-R(y,y,k)=.05` for wrong k, within floating precision, in all three
decoders. Wrong agreement also exceeds the other one-correct outcome by about
.001367-.042071 depending on codes/pixel quality. No scorer or decoder changed.
All original R tensors/decoded semantic tables and these contrasts are retained.
CE/consistency improvement must therefore be read with the complete case table.

## Exact joint law, greedy and secondary results

Static144-state Q and original-pair-plus-repair give the SAME law. For each
finite threshold, the probe independently scores R gathered at repaired source
pairs against original p*q and checks it against CE(R,Q). Maximum observed
requestwise CE difference is7.771561172376096e-16, below1e-12. Raw reward/joint
success/mass parity also passed. Repaired marginals were never multiplied;
`joint_value_and_grad` was never used on Q. Original KEEP raw endpoints match
the saved legacy TRAIN outputs within1e-12.

The greedy metadata is original per-head argmax then the SAME repair, not Q MAP
or repaired-marginal argmax. For both families, greedy success stays
.98828125/.98828125/.99088542 across seeds11/23/47. No greedy improvement is
claimed, and no old formal greedy contract is relabeled by this probe extension.

tau0 is only the registered secondary: H CE .98806860/joint .98866904,
A CE .98828203/joint .98879854. Both-wrong rises further to1.133096%/1.120146%,
with essentially zero disagreement. It was not substituted for log2 or selected
after scores. All three thresholds and every request/seed are retained.

## Real calls and implementation costs

The frozen [CALLS.json](CALLS.json) completed exactly36 actual64-request batches:
18 calls/1152 rendered requests per family,2304 total. Each model executes
Q_zero/T_zero/Q_log2/T_log2/Q_infinity/identity once. Per family, explicit Q
identity has3 calls/192 requests and efficient identity has3 calls/192 requests.
The original KEEP/two-stage infinity/efficient-static-identity names are three
receipt aliases of that one identity execution, adding ZERO calls/charges.
Each request has one fresh original head forward and one final model image
render. No original image was rendered and discarded for padding.

| Profile, per request | Declared kernel units | H timed head/law/render CPU | A timed head/law/render CPU |
|---|---:|---:|---:|
| Efficient identity | 19,236 | 82.08 us | 98.06 us |
| Explicit Q infinity | 19,748 | 117.39 us | 103.20 us |
| Q log2 | 23,937 | 110.24 us | 127.04 us |
| Two-stage log2 | 19,263 | 90.21 us | 99.10 us |

These are fixed64-row FIT-cohort, single-wave component timings. In particular,
the primary two-stage profiles happened to repair ZERO sampled pairs on that
easy service cohort, despite positive repair mass on the full inner-law analysis.
The only actual finite repair was secondary A/seed23/tau0, row42, `[8,10]→[10,10]`
(TRUST_IMAGE). No extra draw or favorable cohort was sought. This limits observed
repair-path timing evidence. The vectorized policy still executes its support
comparison for every finite-threshold row, including agreeing pairs; its recorded
27-unit overhead is not a measured adaptive-compute saving.

The component timer starts after reference/cap/ledger setup and ends after
head/law/sampling/final-output work. Setup/return/trace/export overhead is paid
in full in family CPU below, but was not separately timed per runtime profile.
Consequently the original analysis field named `complete_CPU_net_CE` is only
component-timed service plus amortized family build, not fully instrumented
recurrent guard/setup latency. The [combined interpretation](../runs/content-reconcile-probe-v1-20261023/evidence/combined-analysis.json)
states this limitation. There was no repeated service timing to repair it.

Two-stage has a lower declared sampler inventory than the explicit Q compiler
here. Its exact quality is still a static joint law, and a stronger static
compiler can implement an equivalent sampler. Static reallocation of saved
budget into training was not tested. This does NOT establish dynamic superiority
to the best static complete system or close the parent research goal.
The actual Q-minus-two-stage inventory is 4,674 units/request in each family;
the observed component CPU difference is 20.025 us for H and 27.938 us for A.
The untimed per-profile overhead and zero primary service repairs prevent a
complete recurrent-service cost comparison from these observations alone.

## Evidence reconstruction and complete costs

The original run retained inner p/q but omitted fit-cohort runtime p/q. This
recording omission was identified and preserved transparently. A separately
committed/frozen [evidence audit](../runs/content-reconcile-probe-v1-20261023/evidence/PROTOCOL.md)
reconstructed those probabilities once on each fixed model/cohort:192 extra
capture rows per family. It verified the existing two-stage actions, static
output support, all2304 saved PNG hashes/captions/decoded code semantics, and
saved derived runtime p/q/Q. These are reconstructed evidence, not claimed
original memory captures. No random behavior draw, new model image render,
service-call repeat, retiming or new quality evaluation occurred. Original
1152-request denominators and primary arrays are unchanged.

All audit work consumes the SAME remaining budgets. Final combined accounts:

| Family | Added CPU including audit | Added units including audit | Complete CPU | Complete units |
|---|---:|---:|---:|---:|
| H | 1.567176439 | 183,606,120 | 6.590750701 | 11,847,956,433 |
| A | 1.527452479 | 183,603,672 | 6.937385920 | 11,847,662,223 |

Each remains below added3 seconds/250M AND complete10 seconds/12B. Full original
nine-candidate search/preparation costs were inherited (H5.023574262s/11.664350313B,
A5.409933441s/11.664058551B); no old failure is a credit. Shared probe/audit setup
is attributed fully to both families. Capture, all Q/CE/greedy and wrong-case
observations, original R, exports and actual service are charged. Batch kernel
receipts reconcile into family totals. Admission envelopes are not consumed
work. Exact-integer boundaries have operation/call/operand-bit metadata and
actual CPU; byte/memory primitives use actual CPU, not fabricated hardware FLOPs.
Administrative lossless receipts/descriptive summaries are separately reported.

The sole probe execution and primary analysis exited0. The supplemental audit
exited0. There were no failed/replacement probes, alternate rules, ratio/threshold
sweeps or new training. Physical original new-run CPU was1.829581106 seconds
before its final receipt; attribution totals are larger because common work is
fully billed to each family. All source/model/input identities remain bound.

Review [original budget/calls/quality](../runs/content-reconcile-probe-v1-20261023/build.json),
[original analysis](../runs/content-reconcile-probe-v1-20261023/analysis.json),
[combined audit budgets](../runs/content-reconcile-probe-v1-20261023/evidence/audit-result.json)
and all heads/quality/R/service files in that run. The result supports a narrow
TRAIN joint-output decoding change with explicit error concentration. It does
not confirm the original training, NDU or dynamic claims; those require the
parent's separate unified design and independent evidence.
