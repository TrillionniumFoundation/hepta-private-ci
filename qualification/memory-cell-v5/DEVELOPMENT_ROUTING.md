# V5 targeted language routing: disclosed development attempt

This is newly authored V5 code built against the restored V3 request contract.
It is **not reconstructed V4 source or recreated V4 evidence**. Historical V3
language and V4 failure descriptions informed the research question. Historical
held examples are therefore development material, not fresh evidence. The new
independently authored V5 held directory has not been read by the training owner
or this training program.

## Contract and data

The six intents are `at`, `previous`, `change`, `mean3`, `range3`, and `peak3`.
`change` means current minus previous. All three-month operations use the anchor
month and its immediately preceding two calendar months. `peak3` returns the
maximum numeric value. Other windows, alignments, statistics, output types,
cross-series operations, and compound requests are outside this declared API.
A singleton aggregate is rejected as an unsupported requested operation even
when its numeric answer could coincide with an `at` lookup; this is an interface
boundary, not a claim that such arithmetic is impossible.

Every serving request supplies `utterance`, `series_name`, and `date`. The router
replaces only the given identity slots and then processes the complete remaining
utterance. Date/entity extraction, multilingual use, arbitrary tasks, and open
domain conversation are not established by this experiment.

All public language is synthetic and written by the training-side assistant.
There are no sampled real-user dialogues. The training grammar explicitly
generates labeled operator/window/operand contrasts; those generation rules are
not part of the deployed router. Vocabularies, IDF values, coefficients and class
intercepts are genuinely fitted on the training partition.

| Public partition | Known | Near OOD | Total | Role |
|---|---:|---:|---:|---|
| Training | 840 | 810 | 1,650 | Fit vocabularies, IDF and classifier parameters |
| Selection | 96 | 96 | 192 | Fixed candidate choice and rejection calibration |
| Development | 72 | 72 | 144 | Disclosed diagnostics; excluded from selection |

The 1,650 training rows include 120 manually authored positive seeds and explicit
grammar expansions. Generated combinations are not counted as independent
author-written conversations. Exact text checks found zero normalized cross-label
conflicts and zero within/cross-partition duplicates. This mechanical check is
not independent human validation of every semantic label.

## Fixed candidate family and selection

The six candidates were declared before the development fit:

| Candidate | Feature space | Learner |
|---|---|---|
| `word-lr-c1` | Word 1–3 grams, maximum 12,000 | Multinomial logistic, C=1 |
| `word-lr-c4` | Same | Multinomial logistic, C=4 |
| `mixed-svm-c0.5` | Word 1–3 plus character 3–5 grams, each maximum 12,000 | Linear SVM, C=0.5 |
| `mixed-svm-c2` | Same | Linear SVM, C=2 |
| `char4096-lr-c4` | Character 3–5 grams, maximum 4,096 | Multinomial logistic, C=4 |
| `unigram2048-lr-c4` | Unigrams, maximum 2,048 | Multinomial logistic, C=4 |

Logistic fits use SAGA; SVM fits use liblinear. All use balanced training class
weights, maximum 2,000 solver iterations and tolerance 1e-5. The realized feature
dimensions are 3,067 word grams, 7,212 full character grams, 4,096 small character
grams, and 337 unigrams. No pretrained model, ONNX, Torch, embedding API or keyword
dispatch table is used.

Every candidate evaluates the same 12 confidence × 10 margin threshold pairs
plus an explicit reject-all fallback: **121 actual calibration pairs**. The
primary selection first requires empirical OOD false acceptance ≤5%, then
maximizes correctly accepted known queries, with the declared deterministic
error/storage/name tie breaks. Correct acceptance ≥80% remains a mandatory,
separate gate. SVM softmax values are normalized decision scores, not calibrated
probabilities. See `v5/config.py` for the exact frozen grid and rule.

## One development batch; all failures retained

Run: `results/development/ngram-8011-8017`.
The source label is explicitly `unsealed-development-new-v5`; this is not a
retroactive formal source seal. Both seeds use the same public authored language.
They are optimizer replications, not independent language samples.

Both seeds select `mixed-svm-c2` with confidence threshold 0 and normalized-score
margin threshold 0.3:

| Measure | Selection | Development diagnostics |
|---|---:|---:|
| Correctly accepted known | 17/96 = 17.71% | 5/72 = 6.94% |
| OOD falsely accepted | 4/96 = 4.17% | 2/72 = 2.78% |
| Raw argmax known correct, without calibrated rejection | 75/96 = 78.13% | 62/72 = 86.11% |
| Raw argmax OOD accepted | 39/96 = 40.63% | 33/72 = 45.83% |
| Joint 80% correct-coverage / 5% empirical-risk gate | **Fail** | **Fail** |

These diagnostics do not show that the semantic blocker is closed. The selected
model recognizes many supported development requests before rejection, but its
near-OOD separation is poor. The fixed selection threshold removes most correct
answers to control observed risk. The two accepted development OOD requests ask
for smallest less largest and for the smallest value; both are incorrectly sent
to `range3`. Operand direction and statistic composition remain concrete failure
modes. A low observed false-accept count on a small synthetic fold is not a
population risk guarantee.

All 12 fitted candidates, both selected copies, public corpora, every calibration
grid, selection/development decision rows, warnings and cost receipts are retained.
All fits reported no solver convergence warning. At V5a completion no extra model
family, threshold search, corpus revision or held-driven repair had been performed.
The subsequently authorized, bounded V5b increment is recorded separately below.
Formal seeds 1019, 1021, 1031, 1033 and 1039 remain unexecuted by the training owner;
the root runner must execute them only after the source/protocol/held seal freezes.

## Actual storage and computation

The complete development batch took 21.9417 seconds wall and 21.8355 seconds
process CPU in the recorded environment. This includes feature construction,
fitting, calibration, artifacts and diagnostics. Solver `n_iter_` is retained
with its algorithm-specific meaning; it is not presented as exact FLOPs or an
invented count of optimizer example updates.

The selected deployment stores 269,866 bytes for seed 8011 and 270,271 bytes for
seed 8017. Each expands to **657,912 bytes of coefficient/intercept/IDF arrays**.
These figures exclude Python/sklearn binaries and Python-object overhead and are
not a process RSS measurement. The four shared sparse feature caches occupy
4,196,915 compressed bytes and 12,887,076 bytes of CSR numeric arrays across the
three public folds. Shared caches are built once and their actual reuse is named
in each candidate receipt; repeated candidates are not charged fictitious extra
encoder calls. Pretrained encoder calls and bytes are both zero.

The run inventories 9,425,533 retained bytes before its own final summary file.
`TRAINING_RUN.json` contains the full actual file inventory and separate retained
candidate, selected-copy, training-cache and runtime-array measurements.

## Serving API and bounded artifacts

`Router.load(directory, expected_manifest_sha256=...)` loads only the bound
`manifest.json`, compressed feature metadata and compressed numeric parameter
parts. Every part is at most 480,000 bytes and is individually SHA-256 checked;
the assembled payload is also checked. No pickle or executable model payload is
loaded. The training corpus and numeric memory targets are absent from the model.

`router.decisions(requests)` requires exactly the three serving fields per request.
Each result exposes the raw label, accepted intent or null, acceptance flag,
linear scores, normalized scores, confidence, margin and rejection reason.
`read_router.py` provides a fresh-process JSON interface and records unchanged
parameter digests, actual process CPU/wall time, and request count. The separate
graph owner connects accepted intents to restored parameter cells.

Four mechanism tests passed: strict request fields, public-fold conflict/overlap,
real-fitted-model fresh-process reload with artifact tamper rejection, and coverage
counting that requires a correct answer rather than any accepted label. These
tests are implementation checks, not semantic qualification evidence.

## Subsequent V5b: negative subclasses did not close the blocker

The root authorized exactly two additional candidates using the five negative
families already present in V5a's training metadata. No public text or support
label changed. Each example retained its original seven-class balanced training
weight, preventing an increase in the total negative weight from confounding
the comparison. The complete pre-fit declaration, source bytes and hashes are
in `validation/routing-v5b-predeclared-source/`; the declaration SHA-256 is
`b9683c8f97a294c8a3478c0d3147eae91265f61f630b19f789d6d59d8e0dda85`.

V5b run: `results/development/negative-families-8011-8017`. Exactly four additional
fits ran. Both seeds give these same query counts:

| V5b candidate | Selection correct / known | Selection OOD accepted | Development correct / known | Development OOD accepted |
|---|---:|---:|---:|---:|
| `word-lr-c4-negative-families` | 10/96 | 4/96 | 4/72 | 1/72 |
| `mixed-svm-c2-negative-families` | 6/96 | 1/96 | 2/72 | 0/72 |

Both candidates fail the 80% correct-coverage requirement. Without calibration,
the word candidate has 61/72 correct known and 63/72 false-accepted OOD on the
development fold; the mixed candidate has 64/72 correct known and 45/72
false-accepted OOD. Splitting the negative labels with the predeclared maximum
negative-score mapping did not improve the required coverage/risk tradeoff.
These measurements do not establish that every alternative negative-subclass
method must fail; no additional mapping or model family was tried.

Applying the original primary selector to all eight retained candidates still
selects V5a's `mixed-svm-c2` for both seeds. V5b is retained as a failed candidate
family and is not promoted on raw known classification alone. Its complete
development increment took 4.7247 seconds wall and 4.7227 seconds process CPU.
The four V5b artifacts occupy 1,025,673 compressed bytes; the two selected copies
add 275,615 bytes. A word-subclass model has 294,520 bytes of numeric arrays;
a mixed-subclass model has 986,872 bytes. V5b's actually rebuilt word/character
caches occupy 2,222,538 serialized bytes and 6,791,160 CSR array bytes; this extra
construction and retention is charged rather than described as reuse of V5a.

All four new models were independently loaded in fresh processes and reproduced
the saved public development decisions **576/576, all fields exactly equal**.
Together with the V5a selected-model check this gives 864 exact development
readouts, with explicitly separate source/model identities. These are the same
authored queries repeated through implementations, not 864 independent language
observations. The six final routing mechanism tests include 11-class mapping and
formal admission rejection for a missing freeze, wrong commit, or incomplete
source binding. The readouts and complete comparison are recorded in
`validation/routing-v5b/DEVELOPMENT_FINDINGS.json`.

After the V5b development fit, only formal admission and identity binding were
added: the formal CLI verifies `FREEZE.json` before and after fitting, requires
the exact frozen commit and complete required source inventory, and binds each
model manifest to its seed, source commit and training-source inventory digest.
This does not retroactively change or reseal either development run. The original
V5a/V5b artifacts and pre-fit source snapshots remain unchanged. No third repair
family was added. No independent held request was read, and no formal seed was run
by the training owner.
