# Source-session metadata: recover omitted public evidence before judging learning

Date: 2026-10-14. Parent: 61111917cc99bf4645b27f34a9c8be21ba01df77. PR #1697.
This is a separately registered four-arm DEVELOPMENT ablation. It does not
rewrite the old six-arm paired study, select a production Reader, or manufacture
independent sufficiency. No native implementation outside this new study changes.

## Directly verified input defect

The native LoCoMo ingress stores each session timestamp as Document.observed_at,
separate from speaker/body text. five_reader_response_trial.public_request passes
only document.content. The original source date is therefore absent from every
Reader prompt constructed by that function, including annotated-support inputs.

This increment recovered Python execution and checked the original 376,363,859-byte
archive SHA256 07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af,
then the exact LoCoMo JSON SHA256
79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4.
It also independently rehashed the previous completed native artifact11829020399
(SHA256 8263c249c630ee30d1aaf9f7c7b2defeb488157092770cebc06e95ee53f8752e)
and all83 listed internal members. The ZIP has84 files including SHA256SUMS.
All14 previously admitted TRAIN question IDs were inspected; no new TEST outcomes
were used to select a fix or a candidate.

Two concrete cases demonstrate missing context, not an inferred model defect:

- locomo:conv-30/q6, source D1:24: the source says next month; its session date is
  20 January2023; the target is February2023. The old prompt omits January.
- locomo:conv-48/q81, source D29:34: the source says next month; its session date
  is17 September2023; the target is October2023. The old prompt omits September.

Restoring source time supplies information that was available in the original
material. It does not prove that this caused the unconditional-refusal collapse,
that every target is correct, or that the Reader can now reason about dates.
For example, admitted TRAIN q24 of conv-49 names Sam while its cited source names
Evan. This is an annotation warning, not an independently adjudicated correction;
no target was rewritten, silently filtered or substituted in this increment.

## Lossless opt-in projection

source_time_evidence.project consumes the public request and its actual source
documents, not Benchmark.targets. It uses the existing source-ID digest. Source
body equality is checked BEFORE adding metadata. The content-only-v1 profile
preserves the old canonical input byte-for-byte. source-session-time-v1 prefixes
the exact JSON-quoted source session timestamp and retains the original speaker/
body as an exact suffix. Dates are not parsed, normalized or filled from another
source. They are explicitly session times, not inferred event dates.

Document selection and lexical ranking happen BEFORE projection, so the extra
date tokens cannot secretly improve retrieval or change the distractor set.
Source IDs, citation targets, modality, positions, order, question and options
remain unchanged. Removed evidence is not reintroduced. Empty-evidence controls
remain exactly empty. Missing dates in selected sources fail; no replacement
question, empty fallback or silently truncated training row is supplied.

Question.observed_at is NOT used: LoCoMo ingress derives it from the last session
and does not establish the question's real ask date. No fabricated current date
or timezone is injected. Metadata receipts remain outside model input.

## Fixed four-arm study

source_time_evidence_trial reuses the existing source-family selection,
training_examples, paired-margin objective, fit_response_adapter, official HF
loader, exact generation and readout. It does not monkeypatch them. The arms are:
content-only/frozen; date-aware/frozen; date-aware/paired-margin; content-only/
paired-margin. Training is the same original rank4/alpha8 q/v LoRA, learning rate,
seed and two epochs. Both transformed TRAIN corpora must compile on the same
admitted cohort before any model arm runs. Ineligible original questions remain
in the census without replacement; added dates cannot silently shrink TRAIN.

The registered TRAIN/SELECT split and free-generation question selection are
unchanged from the parent. TEST readout is excluded. Raw generation is sealed
before teacher forcing; validation objects stay SELECT and cannot enter training.
The full benchmark and public-input bytes are rechecked before the final report.
All failed/unavailable rows remain in the planned denominator. Actual generation,
teacher-forcing and fitting work are separate. No automatic candidate selection.

This is an ablation of restored source time PLUS its explicit metadata layout,
not a pure time-token-only causal estimate. Prompt lengths and therefore total
work differ. Equal optimizer counts are not equal FLOPs/energy or matched TCO.
The four arms are not four independent task samples. Source labels remain weak
supervision and exact-body/format measures remain diagnostic, not semantic review.

## Verification and execution

Twenty-five pure projection/assembly tests passed locally on Python3.13.5,
zero skipped. Final Python compilation and workflow YAML parsing passed. The two
implementation blob hashes are7661c31f58d7e1206cdd3864205080e6771a8545 and
9b63f1004eca44fad839e6dd1d91c66f141238e4. The local environment has Torch but lacks
Transformers/PEFT, so no local HF, LoRA, inherited-suite or pretrained result is
claimed. The new workflow requires all inherited suites and the25 new tests
before actual weights execute. Its exact-source result must be reported when
observed; submitting the code is not a passing model experiment.

The dedicated source-time workflow leaves the parent's ongoing six-arm study
and existing native workflow untouched. This prevents re-running the old full
pipeline merely to test new evidence rendering. The new study itself still pays
for staging, four model loads, two candidate fits, free generations and teacher
forcing. Original pretrained material is staged outside the uploaded evidence
directory. Plans, exact source, raw outputs, counters, checkpoints and failures
are retained. No independence, Reader adequacy, Group/NDU gain or completion of
the five requested causal experiments is asserted by these artifacts.
