# Completed paired objective: fitting is still deficient; source dates were omitted

Date: 2026-10-14. PR #1697. This record does not change any model or study.
Paired implementation: 61111917cc99bf4645b27f34a9c8be21ba01df77.
Run38428876346 / job115405473143 completed SUCCESS, including the paired stage.
Source-session ablation implementation: 244c8b5a9c1cd574bcbfb16441b6b143b59e8374.
Its separate run38433638352 was submitted; its model outcome is not asserted here.

## Evidence checked in the restored Python runtime

Downloaded artifact11830744625:4,773,790 bytes; ZIP SHA256
0730b92828e78f09e06ae34c81624cdaa22706021f441dfabe5cd41d0d1e9370.
The actual ZIP has139 files including SHA256SUMS. All138 listed member hashes
were verified locally. Tested-commit bytes equal the paired implementation above.
The aggregate raw-generation SHA256 and all six arm-level raw seals were checked
against actual bytes, not only copied from the report.

Eight focused suite logs contain262 passing test invocations, zero skipped:
14 matrix +54 contracts +29 native +61 Group +28 response +33 adapter/counter/
replay +17 Encoder snapshots +26 pair-suite invocations. There are259 distinct
test identities, NOT262 distinct tests: three imported NativeAdapterTests are
rediscovered in the paired suite. They remain charged repeated work rather than
extra evidence. All23 newly defined pair tests passed. This is not full-repository
Rust, target-device or production validation.

## Actual completed paired execution

Six arms,24 planned rows per arm,144 successful rows in total. There are120 real
free-generation calls and24 always-refuse rule outputs. The free-generation
cohort is four TRAIN questions and four SELECT questions, not144 independent
tasks. SELECT uses conv-42 and conv-44. TEST families conv-43/conv-47 are excluded
from this new study, although inherited historical regression remains separate.
Only three SELECT questions have available benchmark reference answers.

Each of the three newly trained arms used28 examples (14 question-level pairs),
28 optimizer updates,112 actual decoder forwards,18,852 processed input tokens,
1,122 positively supervised tokens and2,244 scored response tokens. Rank4/alpha8,
q/v targets, seed and learning rate remain fixed. Base preservation and saved
adapter reload checks passed. Across new fits:84 updates/336 decoder forwards.

The paired study records2,650 free-generation decoder forwards and340 additional
teacher-forcing forwards (five model arms x17 eligible pairs x4 scores). These
are separate from336 training forwards, inherited regressions, loads, repeated
runs and fixture work. No energy/FLOP or matched-total-compute claim is made.

Paired result raw SHA256:
5ec267006e1e7edc65d0b754c10515814e8ff9abd6e464dc2eea842fb4b42ac0.
Plan SHA256:
9cdaaf9ea7d9014f07e43a7172c7eec9b13770e40419f955d28e70042bd94800.

## No demonstrated conditional-learning solution

These are means of length-normalized teacher-forced answer-minus-refusal log
scores under supported input. They are NOT calibrated correctness probabilities.

| Arm | TRAIN support margin | SELECT support margin | Both preferences positive, TRAIN/SELECT |
| --- | ---: | ---: | --- |
| Frozen | -0.915926 | -0.861946 | 0/14 ; 0/3 |
| Original saved aligned | -1.138581 | -1.067613 | 0/14 ; 0/3 |
| Paired CE | -1.240753 | -1.187506 | 0/14 ; 0/3 |
| Paired margin | -0.785023 | -0.720040 | 0/14 ; 0/3 |
| Paired margin shuffled | -0.793199 | -0.700382 | 0/14 ; 0/3 |

The objective is not met even on TRAIN, so this is not merely a demonstrated
train-success/test-transfer gap. Correct margin supervision improves some mean
scores relative to the frozen model but never makes the desired supported
preference positive on these pairs. The shuffled control does not establish a
correct-pairing advantage; do not call small mean differences superiority.

Free-generation prescribed refusals on SELECT, four questions per condition:
original saved aligned4/4 for every condition; paired CE3/4 on empty and
support-only,4/4 on support-plus-distractor and support-removed; paired margin
and shuffled margin0/4 for every condition. All arms have zero exact-body matches
and zero syntactically valid citations in this registered readout. Raw responses
include paraphrases that may be partly supported, as well as unsupported details
and copied JSON. Zero exact match is not zero independently judged semantic
accuracy; failure to emit the prescribed refusal is not automatically a valid
answer. No independent semantic adjudication was manufactured.

The frozen model also has a positive mean teacher-forced empty-refusal margin
while emitting no prescribed refusals. This directly illustrates why likelihood
margins cannot replace free-generation measurements. No checkpoint, threshold,
epoch count or candidate was selected from these outcomes.

## Separate source-session input correction and local counterexample

Before inspecting this paired artifact, the source-time implementation was fixed
and pushed. It restores actual Document.observed_at only AFTER document retrieval,
leaving source IDs/order/body, reference targets, splits, LoRA and paired-margin
objective unchanged. The four arms cross content/date representation with frozen/
trained Reader. This is source-date-plus-layout ablation, not a time-token-only
causal claim. Twenty-five pure local projection/assembly tests and compilation
passed; their source blobs match the published code. New HF outcomes remain
separate from those local tests and this completed parent.

The original archive and exact LoCoMo JSON were rehashed. Among all14 previously
admitted TRAIN questions, q6 in conv-30 and q81 in conv-48 have next-month sources
whose original session dates are20 January2023 and17 September2023, respectively.
The prior public_request omitted these dates. This is actual input information
loss; it is not proof that missing dates caused the general refusal collapse.

A local, explicitly named ARCHIVED PYTORCH REFERENCE diagnostic used the original
verified Reader weights on these two known TRAIN cases, with and without the
fixed date projection. It did not use HF, train weights, or access TEST labels.
The original reference source blob was33fd1bc640c9c2c9993f7f1b3740421cb1abd0b4.
Four calls succeeded,172 real decoder forwards. Output budget was64 each.

- Conv-30/q6 without dates returned next month. With dates, it returned20 January
  rather than the intended February: it confused session time with event time.
- Conv-48/q81 copied the input or metadata and reached the64-token output limit
  under both representations. It did not produce the expected October answer.

Raw diagnostic SHA256:
87160cca2f591c536484eb7a9e3ac2589d419d14dc75459a4301e46e945d5209.
This proves neither general model equivalence nor date-reasoning gain. These
cases were selected for an already inspected TRAIN defect, not random/unseen
confirmation. The published date prompt/plan was not tuned after these outputs.
Restoring information is necessary for these temporal targets but insufficient
for reliable reasoning in this observed frozen-reference diagnostic.

## Remaining scope

Keep both original refusal collapse and this paired outcome. The next decisions
must distinguish input completeness, weak annotation quality, ability to fit the
training relation, and actual validated answer behavior. A stronger training
score or more frequent answering alone cannot qualify the Reader. Do not silently
fix mismatched benchmark names/labels or filter inconvenient cases.

The dedicated source-time lane retains full original-model verification and all
inherited tests without triggering old fitting merely because a new projection
file was added. Its staging, model calls, new fitting and diagnostics still cost
resources. It changes no main/CURRENT/serving selection. Group/NDU gains, real
multimodal/split transfer, independently released task families, matched-quality
shared-vs-replicated lifecycle costs and native production ownership remain open.
The five independent causal experiments are not complete.
