# Completed SELECT content comparison on frozen saved candidates

Date: 2026-10-14. PR #1697.
Executed source: 1672d4b3debb65bf0d7198464d9dc0c55811f08e.
Executed tree: 41b1a7653fe262ac1d7c238b4742bc73ea2a68c6.
Run38496209074 / job115632423623 completed SUCCESS. Final job status,
complete decoded logs, reported result and output-artifact metadata were inspected.
This note is documentation only: no optimizer, serving selection or new model run.

## 1. Verification and coverage actually completed

All13 required test invocations/suites succeeded:31 new inventory/readout tests,
14 matrix,54 contracts,29 native,61 Group,28 response,33 adapter/counter/replay,
17 Encoder,26 paired invocations,25 source-time,25 fit-audit,20 projection and
27 content-control tests. Total390 passing test invocations,387 distinct identities,
zero skips. The three imported NativeAdapterTests repeat in the paired suite.
Compilation, dependency checks and both original/result archive SHA checks passed.
The running script additionally verified every saved-budget archive member before
extraction. These are focused Python/official-model checks, not full repository,
Rust, target-platform or prospective-merge acceptance.

The new inventory expanded only SELECT donors and retained the exact four old
SELECT generation questions. All THREE reference-bearing recipient comparisons
found same-partition/cross-family/equal-source-count donors and compiled all
four likelihood inputs under the original bounds BEFORE any Reader load.
The fourth recipient has no eligible reference-bearing comparison and remains
in both the generation and likelihood denominators. Coverage of annotated
recipients is3/3; coverage of ALL planned recipients is3/4. Do not call it4/4.
The source-count and identity selection rules were not relaxed and no shorter
replacement donor was searched after token qualification.

The old run38493158981 with no eligible SELECT donors remains unchanged. This
is a newly registered inventory after old missingness was known, not a rewrite
of old preregistered outcomes. All SELECT material remains exposed public
DEVELOPMENT. No TRAIN or TEST annotation was used as a donor or training signal
in this run. Source partition metadata, rather than non-SELECT target values,
were used to check provenance boundaries.

## 2. Actual model work, no new fitting

Three models: frozen Reader, exact saved aligned8 adapter, exact saved shuffled8
adapter from budget artifact11838105827. No new pretrained optimizer updates.
Strict original snapshot, saved adapter tensor equality, frozen base and final
resident integrity checks all passed. Every model used full-logits-v1; the
assistant-only projection qualification remains failed and unused here.

There were36 planned generation slots.33 ACTUAL model calls succeeded, with no
model execution failures;3 donor-source slots (one per model for the missing
reference recipient) remain unavailable. Each model answered4 own-source,
4 empty and3 donor-source inputs. Repeated model/condition slots are not new
independent questions. Each model scored3 recipient comparisons via12 teacher-
forcing forwards; all4 audit slots per model remain visible. No audit failure.

Observed work:633 free-generation decoder forwards and36 likelihood forwards,
plus model loading, staging, package preparation and fixture tests. Saved
weights are reused, but verification, loads and replay still cost resources.
Two adapters each have230,400 parameters/921,600 FP32 parameter bytes, attached
to the archived small Reader, not421M Laya. Distinct composed models still pay
distinct loaded instances. No measured-energy, whole-process-peak or equal-TCO
benefit is claimed. Only process measurement artifacts are retained separately;
start/end RSS is not peak RSS. The study reports new_optimizer_updates=0, not
zero optimization work in inherited tiny-model tests.

## 3. A measured SELECT content signal, not semantic-answer qualification

For own annotation a, donor annotation b, fixed question q, own nonempty source
E and donor nonempty source D, the unchanged diagnostic is:

I = [l(a|q,E)-l(b|q,E)] - [l(a|q,D)-l(b|q,D)].

l is the mean assistant-token log score, NOT a calibrated correctness
probability. Both contexts retain the same source count and local citation
labels, original body/session-date projection and the same recipient question.
Answers/provenance stay out of free generation; raw generations seal before
likelihood targets enter the scorer. An evidence-independent preference cancels
in this interaction, but source length/topic effects and weak annotations remain.

| Fixed model | SELECT family-macro I | SELECT task-mean I | Positive I /3 scored |
| --- | ---: | ---: | ---: |
| Frozen Reader |5.326765|4.845151|3/3|
| Aligned8 |8.229691|7.657232|3/3|
| Shuffled8 |4.927253|4.748412|3/3|

Same-recipient/donor paired differences:

| Comparison | Task-mean delta | Family-macro delta | Positive/negative differences |
| --- | ---: | ---: | --- |
| Aligned8 minus frozen |2.812081|2.902925|3 positive,0 negative |
| Aligned8 minus shuffled8 |2.908821|3.302438|3 positive,0 negative |
| Shuffled8 minus frozen |-0.096739|-0.399512|1 positive,2 negative |

These are means on the same3 scoreable SELECT questions/two recipient source
families out of4 planned. The missing reference is not a zero effect. Correctly
paired eight-epoch training is associated with stronger SELECT content
interaction than both controls on every scored comparison in this bounded
run. Unlike the earlier empty/nonempty likelihood proxy, these measurements
provide a content-sensitive development validation signal worth pursuing.
The frozen Reader already has positive content interactions, so this is not
proof that content sensitivity suddenly emerged from zero.

This does NOT establish statistically significant transfer, independently
reviewed semantic accuracy, a universally better Reader, reasoning emergence
or completion of any of the five formal efficacy experiments. Donor annotations
are not proven wrong for the recipient; source lengths differ; directed donor
reuse and only two SELECT families limit independence. No confidence intervals
or p-values are asserted. No checkpoint or numerical threshold was selected
from this outcome. The old TRAIN and new SELECT mean levels use different
comparison sets and must not be treated as directly interchangeable effects.

## 4. Free-generation correctness remains unresolved

Aligned8 and shuffled8 each emitted the prescribed refusal on4/4 empty inputs,
and0/4 own-source or0/3 available donor-source inputs. The frozen Reader had
no prescribed refusals. All registered exact-body and citation-syntax counts
remain0. This is not independent semantic accuracy: no raw answer was edited
or automatically re-scored into correctness, and missing targets are not judged
errors. The stronger content interaction has not yet translated into a proven
improvement in grounded final answers. Neither adapter is adopted or admitted.

## 5. Retained evidence and source boundaries

Artifact11863981474: hepta-select-content-development-not-confirmation.
GitHub reports1,540,902 bytes and499 uploaded files. ZIP SHA256:
aeb4113b6d2baace0a042f960876861c78b5449b6d9dac404dee2e5c041e46fa.
Plan SHA256:
77940e3d8e04106f9390fc0fc363c8b3df228213f8397b2c87ea49d867297568.
Inventory-plan file SHA256:
fc825d382b1686f47efa4aa40c7d366b1f9f3a80457b78412dde7dcccea73ba5.
Raw-generation file SHA256:
df6b77484d73ceda023e946d791d8244d1777506eeaf211a5c450a7dc8280adf.

The archive retains exact source, all logs, full donor/candidate/compilation
censuses, raw answers/seals, all paired scores and model integrity receipts,
without original pretrained model bytes. It was downloaded in this session,
but local Python/container returned ClientError, including the rehash attempt;
NO local verification of this new output ZIP is claimed. Hosted original/input
archive checks and reported output hashes are distinct evidence from a local
rehash. No independent human signature or semantic approval was issued.

All old training, projection-failure, source-date, content-swap and unavailable
validation records remain. New code is five added paths only; this result note
changes no executed source. No main/CURRENT/serving, external Reader gate or
original22-arm/15-contrast/768-position plan change. Stronger answer generation,
independent grounding and future task families, trained Group/NDU benefits,
multimodal/split transfer, shared-versus-replicated lifecycle cost and native
FinalUse/target-device adoption remain separate work.
