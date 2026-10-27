# V5 formal result: parameter readout works; language addressing remains unqualified

**The frozen V5 experiment completed, but it did not pass the joint qualification.**
All 20 seed/domain cases passed exact parameter readout with a supplied oracle
intent. None passed the semantic gate or both composition-ablation gates. The
independent frozen auditor found no discrepancies in 112,493 checks. A successful
execution and audit do not turn these negative scientific outcomes into passes.

This increment trained actual language-routing parameters. Its numerical memory
parameters and typed graph layout are unchanged, recovered historical artifacts;
V5 did not newly train numerical memory cells, invent cell types or discover new
arithmetic primitives. All changes remain research qualification work.

## Identities and order of execution

| Boundary | Exact identity |
|---|---|
| Executed source | `21da14adf9910fa5218696f6451f517fa0ef46a7` |
| Remote source-freeze receipt commit | `bca6a05b6dbffd92a8626d697b103847030469f8` |
| FREEZE SHA-256 | `9e10b723c13a0243aa8d652a192809f73b8c4dc8e7ae41959625383e4ec80afa` |
| Selected-model checkpoint, before held execution | `3426c50f2d867335b75c866320f4afb350dc7868` |
| SELECTED_MODELS SHA-256 | `6c2ef25c56a3a4562bcbab00b0e408ebe8f13d24e577b3792c17d8abfcddbf3e` |
| Independently authored held seal SHA-256 | `287762002bef1892f22e8672345354c61db142fe68f654767b0ff0bf90bcb75b` |
| Held corpus SHA-256 | `d48195b3bc3a4f639db31a7a400a3e6eb79b3d879e7ba19ae96217224aeaacbf` |

The held checkpoint was first saved remotely at
`9616e81ec3f66d734c9f430801ec2f4c4e908adb`. The training owner did not inspect its
wording. Source formatting then ran in hosted workflow 40468682945: repository
`just fmt`, pinned Ruff formatting and Ruff checks all passed. The 35 new source
files had identical ASTs before and after formatting; all sealed held and unchanged
vendor files retained their bytes. Sixteen targeted mechanism tests passed before
that final formatting, and no unit tests were rerun afterwards.

All 118 files in the source project subtree were matched to their actual remote
Git blob identities. The frozen source/configuration inventory contains 47 files.
After formal training, all 36 files in the selected-model checkpoint were again
verified against the remote tree. That verification completed at
2026-10-27 07:47:27 UTC, before the held evaluation command began. These records
are retained under `validation/format/` and `validation/formal-training/`.

## Experimental scope

The independent evaluation assistant authored 216 English templates: 144 supported
requests, 24 for each of six operations, and 72 near-domain unsupported requests,
six in each of 12 families. The operations are the value at the supplied month,
the immediately preceding value, current-minus-previous, and mean/range/maximum
over the three months ending at that month. Entity and date are explicit slots.

The same 216 templates were instantiated in four numerical domains: CO2,
temperature, sunspots and unemployment. Five training seeds were fixed in advance:
1019, 1021, 1031, 1033 and 1039. Thus the main arm executed 4,320 requests, with a
further 4,320 separately executed strong-control requests. There are **216 authored
language templates**, not 4,320 independent language observations or five
independent language corpora. Authors were assistants, not independent human
annotators; the queries are synthetic, not real-user traffic.

Training, selection and diagnostic development partitions contained respectively
1,650, 192 and 144 rows. All eight candidates were fitted for all five formal
seeds, with the original selection rule and confidence/margin grid. The same
`mixed-svm-c2` candidate won every seed. It uses genuinely fitted word/character
TF-IDF state and linear classifier coefficients; it has no pretrained encoder.
Its minimum normalized-score margin is 0.3. Those normalized SVM scores are not
calibrated probabilities.

The public selection result was 17/96 correctly accepted known requests and 4/96
false-accepted OOD requests. Selection already failed the 80% coverage requirement.
It was retained as the declared risk-feasible primary, without replacing it after
seeing the independent held result.

## Formal held results

Every one of the 20 seed/domain cases produced the following counts:

| Metric | Actual result | Prespecified requirement | Status |
|---|---:|---:|---|
| Correctly accepted supported queries | 12/144 = **8.3333%** | At least 80% | Fail |
| False-accepted unsupported queries | 2/72 = **2.7778%** | At most 5% | Observed-rate pass |
| Parameter oracle: exact number and ordered support | 144/144 = **100%** | 100% | Pass |
| Actual connected graph: exact composed queries | 12/120 = **10%** | Used for both gains below | Measured |
| Removed-edge graph: exact composed queries | 0/120 = **0%** | Comparison arm | Measured |
| Type-compatible node permutation: exact composed queries | 6/120 = **5%** | Comparison arm | Measured |
| Connected minus removed-edge gain | **10 percentage points** | At least 10 points | Pass |
| Connected minus permuted gain | **5 percentage points** | At least 10 points | Fail |
| Actual parameter result minus same-router strong planner | **0 percentage points** | No superiority presumed | Tie |

The semantic gate requires both coverage and OOD conditions, so its total is
**0/20**. The composition gate requires both ablations, so its total is **0/20**.
The parameter-oracle gate passes **20/20**. Overall qualification is **false**.

Both numerical equality and ordered provenance are required. Matching a scalar
with the wrong source months does not pass. All 120 supported non-`at` queries
remain in the composition denominator, including refusals. The 10-point boundary
uses the difference in successful counts divided by 120; it is not the subtraction
of two rounded percentages.

The twelve correct accepted requests are six `previous`, four `mean3` and two
`range3` templates. All 24 `at`, all 24 `change` and all 24 `peak3` supported
templates were rejected. No accepted supported request had an incorrect label.
The two false accepts are unsupported requests routed to `change` and `mean3`.

Before confidence/margin rejection, the selected classifier has only 97/144
correct known labels (**67.3611%**) and falsely assigns a supported label to 32/72
OOD requests (**44.4444%**). Consequently, **keeping these argmax labels and only
changing acceptance thresholds cannot reach 80% correct known coverage**: an
acceptance filter can retain at most the existing 97 correct labels, whereas at
least 116 are needed. This is a deduction about these selected models, not a claim
that every other routing architecture or data distribution must fail.

The oracle-to-actual gap is **91.6667 percentage points**. The exact codec plus
supplied planner has the same gap under the same actual router. This localizes the
principal end-to-end failure to language addressing under this contract; it does
not establish a generally adequate numerical memory capacity or automatic graph
formation.

## Real execution, comparison and costs

The parameter and strong-codec arms were loaded in separate fresh processes for
each seed/domain case: 40 actual reader processes. Each query row carried only
`utterance`, `series_name` and `date`. Gold labels and numerical targets stayed in
the grader and explicit oracle controls. The two fresh readers reproduced exactly
the same full routing decisions. The actual connected parameter graph performed
720 hop calls; including its two ablations, the parameter processes performed
1,720 hop calls. The strong planner performed 720 actual hop calls.

The source freeze binds the value-free `assets/ASSETS.json` inventory rather than
including codec payloads in the list of source files. The parameter reader therefore
does not open codec or residual payloads merely to hash its source. Each reader
loads and verifies its own permitted immutable serving files. The Python open
whitelist covers the serving phase; this is not an operating-system sandbox or a
complete operating-system I/O trace. Source-hash verification reads source bytes.

| Seed | Four-domain parameter deployment | Four-domain strong-codec deployment | Parameter excess |
|---|---:|---:|---:|
| 1019 | 301,423 B | 291,933 B | 9,490 B |
| 1021 | 301,169 B | 291,679 B | 9,490 B |
| 1031 | 300,915 B | 291,425 B | 9,490 B |
| 1033 | 301,125 B | 291,635 B | 9,490 B |
| 1039 | 301,345 B | 291,855 B | 9,490 B |

Each row is the actual union of serving files across four domains, counting shared
router and metadata files once. The parameter deployment is approximately 3.25%
larger and gives the same actual answers as the strong comparator. These are
natural deployment costs, **not a controlled same-budget single-cell/multi-cell
or adaptive/fixed-structure experiment**. Runtime binaries, Python object overhead
and complete RSS are not included in these serialized-file totals.

The five selected router artifacts individually occupy 270,177–270,685 B. Their
loaded numerical coefficient/intercept/IDF arrays occupy 657,912 B each. The full
formal training directory contains 339 files and 23,901,273 B, including all
candidate alternatives, diagnostics and shared feature caches. All 40 candidate
artifacts occupy 7,049,096 B; the five additional selected copies occupy 1,352,287 B.
The shared CSR cache is 4,196,915 B on disk and 12,887,076 B in numeric arrays.

Formal training took **68.124512 s** outer wall and **68.095237 s** child CPU,
including interpreter startup. Actual estimator fitting accounts for 54.962782 s
CPU; candidate calibration accounts for 5.830962 s. No solver warning occurred.
The full joint command took **91.886653 s** outer wall and 91.857155 s child CPU;
the evaluator's inner wall timer was 89.728630 s. These are separate measured
scopes, not interchangeable timings. All original memory/layout training costs
belong to historical studies and are not claimed as new V5 fits or zero-cost
origins.

The two development increments are retained: V5a ran 12 fits and V5b four more.
They took respectively 21.9417 s and 4.7247 s wall. V5b split the five pre-existing
negative training groups into learned subclasses while retaining original
per-example weights. It failed to improve the required coverage/risk tradeoff.
All 56 declared development/formal candidate fits and failed alternatives remain
available. Mechanism tests and post-training artifact inspection are separate
activities, not additional independent semantic evidence. The latter inspection
recorded its own 11.547713 s inner wall overhead, excluding initial inspector
imports. Its internal reader CPU measurements are not presented as full process
CPU. Detailed ledgers are in `validation/formal-training/REPORT.md`.

## Audit and interpretation

The independent auditor was included in the frozen source before held execution.
It uses only the standard library, imports no project model/executor/grading code,
and does not read the held corpus file. It independently decodes and verifies raw
record envelopes, recounts exact values and ordered support, checks all denominators
and gates, verifies source/model identities and recovers deployment file unions.
It completed **112,493 checks with zero failures**.

Its numerical gold is the sealed grader record. It does not independently re-decode
the original numerical source codec, authenticate the historical creation of every
process, prove timing authenticity or inspect all operating-system I/O. It is a
computational audit by another assistant, not an independent human assessment or
a population-level safety certification. In particular, an observed OOD rate below
5% on 72 authored queries is not a guarantee that population risk is below 5%.

A separately retained posthoc check compared all 216 held templates with the
actual saved public train/selection/development corpora, using runtime NFKC,
case folding, explicit-slot replacement and whitespace normalization while
preserving punctuation. Exact normalized overlaps and label conflicts were zero
in every partition. Its independently calculated normalized-request hash matches
all 20 formal cases. This check did not select or modify a model; zero literal
overlap does not establish independence of the semantic distributions.

V5 is a new, fully recorded increment. The earlier V4 recovery restored only
155 of 6,181 original formal output files; 6,026 remain unavailable. This study
does not rename V5 outputs as recovered V4 evidence. Earlier V4 language results
use a different corpus and are not a paired performance baseline for this run.

The result supports continued work on parameter readers and typed execution as
bounded components. It does not close the original six-stage objective. Reliable
language addressing, a same-budget advantage, more general type composition,
continual maintenance, costed adaptive structure and transfer to genuinely new
task families remain distinct obligations. `QUALIFICATION.json` and `BLOCKERS.json`
retain those open states; production admission and the general-memory claim remain
false. There was no post-held model change, threshold adjustment, candidate
reselection or replacement evaluation.

## Reproduction and evidence

`README.md` gives the source/selection sealing and execution commands. The complete
raw formal run and validation records are delivered in `evidence/v5-formal/`.
Concatenate and restore using the supplied `maintenance/evidence.py` utility,
which verifies every part, the whole archive and every restored file. The two
development archives remain separately available and retain their original source
snapshots. Archive transport is separate from memory-system compression claims.

After this report is public, replaying the same held corpus is a reproducibility
exercise; it cannot become a new independent test for a modified router.
