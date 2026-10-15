# SELECT same-evidence question cross-check: local reference, not new training

Date: 2026-10-14. PR #1697.
Canonical remote core: `37054117511c58c55eb112fa92c8c98980b76f3f`.
Core Git blob: `e6f5aaef6a12baa9a5db161dd2a9a048e230d0ad`.

## Ownership and scope

The remote branch advanced concurrently while this local increment was running.
Its `select_question_relevance.py` already implements the required SELECT
matched-donor-question followthrough. The current increment did NOT create those
remote commits. It retains that implementation instead of adding a duplicate
production runner. The independent local prototype agreed on all three available
matched/mismatched requests and their exact answer/citation targets.

This candidate patch adds only supplementary tests, this note and a measured
receipt. It changes no existing trainer, model, input, control, numerical
tolerance, workflow, review gate or serving selection. The original upstream
relevance training result has not been assumed complete.

## Actually verified concurrent artifact

Run38514828914 at37054117 ended FAILURE at the upstream-dependency check.
Its new model-generation steps did not execute. The output ZIP11872050371 was
downloaded and locally rehashed against:
d2bea9ee411527601c71ba2985c28a66728892f4739c842de9a08d3750202bd6.
All492 listed members passed (493 files including SHA256SUMS).
Actual log census:493 successful test invocations /490 distinct identities.
The three repeated identities are retained as repeated work, not extra tests.
The dependency file records upstream run38512395172 still in_progress, with
no completed artifact. A green test phase is NOT a green whole workflow.

After obtaining this exact source snapshot, the 19 added stdlib regressions
passed locally, zero skips. They check all-answer/all-refuse/blank behavior,
joint versus marginal criteria, question-independent likelihoods, unchanged
source/date/target bytes, missing recipients and target-free public requests.
These tests are not full-repository, native-platform or semantic qualification.

## Actual local original-weight baseline

The local historical model ZIP was incomplete and was NOT used. A fresh download
of original artifact11586991191 was verified at376,363,859 bytes and SHA:
07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af.
The original staging/clean-copy and reader/encoder inventory checks passed.
Original metadata was preserved, not deleted.

Execution used the existing EXPLICIT CPU PyTorch reference:
`five_archived_torch_reference.py`, Git blob
33fd1bc640c9c2c9993f7f1b3740421cb1abd0b4,
profile `hepta.archived-torch-reference.v1`, PyTorch2.10.0+cpu, eager attention.
This is NOT a fallback embedded in the official HF runner. No LoRA or optimization
was performed. The official new relevance candidates were NOT loaded.

The question/source requests were sealed before generation. Eight planned slots
cover four original recipients. Three recipients have both matched/mismatched
inputs; the missing-reference recipient retains TWO unavailable slots.
Actual6/6 calls succeeded, producing164 measured decoder forwards.
Three are new matched questions and three are explicit paid historical replays.

All three replayed mismatched inputs exactly reproduced the historical frozen
Reader's raw answer AND input/output token hashes. This is narrow trace agreement
on those three requests, NOT universal HF equivalence or a new trained-model result.
The canonical behavior function reports3 jointly observed pairs and0 weak
selective pairs; planned denominator remains4. Nonrefusal is not correctness.

## Direct source-level observations, not independent grades

These observations were made after reading model identities and outputs:

* Dog-store evidence: the matched question received "a friendly and playful dog",
  consistent with the source. The same text under the YouTube question still
  elicited an unsupported YouTube-channel answer rather than refusal.
* Backyard-play-area evidence: the matched question elicited the actual play-area
  sentence; the book-theme question elicited unrelated book themes.
* Gaming evidence: the question asks which game the second tournament concerned.
  The source says Nate usually plays CS:GO, but this tournament was Street Fighter.
  The frozen reference answered CS:GO. This is a relation-binding failure despite
  nonempty relevant evidence. Under the unrelated pets question it still answered
  about entertainment/companionship rather than refusing.

No 2/3 semantic accuracy is inferred from these examples. The annotations and
already-exposed SELECT families are not independent confirmation. The new weak
joint behavior criterion would also accept an incorrect substantive matched
answer if its mismatched counterpart refused. Evidence-first semantic review
remains separate. Neither a nonzero likelihood interaction nor topic overlap
can be directly promoted to a Group/NDU final-outcome utility.

## Paid work and retained evidence

The six calls,164 forwards, original download/staging/loading, repeated tests and
historical replay all remain paid. Whole-process peak memory, FLOPs and energy
were not established. No shared-vs-replicated lifecycle savings or universal
latency improvement is claimed.

The delivery retains the eight raw rows, their input hashes and source texts,
start/finish journal, public-input seal, model-material verification, canonical
source reconciliation and completed local test logs. It excludes original model
weights and the full benchmark. The independent duplicate runner is not in this
patch. Raw answers and old results were not edited or re-scored.

Formal reviews received:0. New pretrained optimizer steps:0.
No Reader, SYSTEM2, NDU, multimodal/split or production admission is issued.
