# Genuine native-answer MultiRC audit — research handoff (2026-10-14)

Parent: \`a7a2edc6cf36c139e348d4168a5170fcfa417aed\` (#1991).
Tested code: \`2b9535b674aaab84f3619deca854640ee55049dd\` (#2010).
Branch: \`research/shared-stem-multirc-genuine-answer-slates-20261014\`.
No main merge, production promotion or old V1 study rewrite.

## Motivation and study identity
The predecessor V1 learned from the first answer ID for two questions in each
registered MultiRC passage. A swap of answers from *different questions* has
no authentic ground truth. Instead, the new additive audit recovers **all
genuinely annotated alternatives of the original two questions**, bounded
to 2–8 answers per question. The underlying exact dataset/revision, original
passage/question/candidate identity, source SHA256 and original label receipt
are verified before accepting a slate. Too few/many or missing candidates
cause an explicit failure, never a success with a silently truncated denominator.

The material owner writes an anonymous, strictly label-blind candidate slate
and a separate actual-label receipt. V1 Reader weights and original predictions
MUST already be sealed before the candidate audit. All four original frozen
Reader safetensors are loaded with exact weight fingerprints and no training.
One physical Encoder forward per source passage, one query embedding per real
answer and four Reader forwards per answer are separately metered. The former
first candidate of each question must replay its original V1 logits. Unknown
operators, invalid storage and missing weights fail closed. The owner-only
score stage joins labels **only after** the new predictions have been sealed.
It reports candidate-level accuracy, Brier, complete-answer question accuracy,
within-question answer sensitivity and paired recovered/lost correct answers.
This is **not** the official full SuperGLUE MultiRC benchmark score.

## Actual observations, never promoted into efficacy
Local synthetic MultiRC-shaped material, two source passages, four questions,
two genuine candidate alternatives per question (eight total), actual PyTorch
Reader training: one audit used 2 Encoder forwards, 8 candidate query
embeddings, 32 Reader forwards and 5,048 additional recorded ATen formula
operations. All four matched-parameter Readers scored **4/8**, with zero
within-question candidate probability span in the basic fixture. An additional
answer-aware query embedding control produced tiny nonzero spans in two
comparison Readers, but conditioned Reader sensitivity remained zero.
This is deliberately retained as a NEGATIVE mechanism observation. The basic
fixture's query encoder itself ignored answer text, so a zero cannot be
attributed to a trained Reader without the answer-aware control. No
pretrained ModernBERT MultiRC accuracy or learned generalization follows.

## Verification actually executed
15 focused tests passed on the tested byte-exact code, including genuine
labels and source IDs, frozen bank replay and external label isolation,
candidate omission/reordering, owner/model tampering, strict unsupported
ATen operations, physical tensor backing caps and failed score semantics.

A long-running legacy test partition initially exceeded the execution
wrapper time limit. That interrupted attempt is retained, NOT marked green.
The source suite was split into seven independently complete partitions,
total **612 distinct tests**. This was repeated twice: 612/612 and 612/612,
all process exit codes 0, no skips, expected failures, errors, failures or
discovery failures. All 56 source test file SHA256 inventories and test ID
inventories match across the two full runs. Exact code and workflow blobs:
- \`multirc_candidate_slate.py\` : \`99d0dc1395140c85fa70837810d09073c5558dd1\`
- \`multirc_candidate_audit.py\` : \`d3c6825a23ed7f1f0655ca719012123e7216d70a\`
- \`test_multirc_candidate_slate.py\` : \`2a571bdcc2a8e03c7ef2fe16208553ab74299885\`
- \`hf_multirc_checks.py\` : \`0f576482eec055e0934109813a2cefe813b36c7d\`
- workflow : \`b431b515d0404424c9dad3196c5a88d432bf0425\`

The portable package contains 177 SHA256-manifested entries, all checked,
and a patch which replays over the #1991 source slice with five byte-for-byte
matching paths. Package SHA256:
\`2ee0ace877f7e5b4bc609a5d0771801135e8e92644958217e04df5611acd431e\`.
Patch SHA256:
\`4c7dd6749c8318609472da7bc0986676ebb494b3fe555f1d3ea679f148e9bc0b\`.
Complete local receipt SHA256:
\`be9efe755844b0df34b153b7588ed1d3b1431fd3f3f57c7e54b58246b8c7fb57\`.
All 56 test source file digests, canonical JSON SHA256:
\`f281c6a8b2a0d7e14e09ee519987f76b5cb0364e89f49bee37d4178e1f59acc8\`.

## Hosted and science limits
The existing pinned public-weights MultiRC workflow has additive stages:
material-owner expands authentic candidates, a blind frozen-Reader evaluation,
and a post-seal human-label score. Its artifact list excludes raw text,
label vectors and model weights. It has NOT completed on this commit as of
handoff preparation. Local CPU source tests are not substituted for installed
Transformers, actual pretrained weights, full repository Rust/native/GPU CI,
energy, external data license approval, independent observer authentication,
contamination control, multi-seed statistical inference, future task learning,
NDU/System2, multimodal capability or 1024/4096-Cell serving validation.

To reproduce on a CPU source checkout:
\`\`\`sh
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python qualification/stem-cell-v1/run_checked_tests.py \
  --pattern test_multirc_candidate_slate.py --output new-candidate-tests.json
\`\`\`

For actual pretrained material (requires the pinned checked-in workflows'
Python/Transformers/PyArrow versions and reviewed network source), use:
\`multirc_candidate_slate.py --help\` then
\`multirc_candidate_audit.py run --help\` and
\`multirc_candidate_audit.py score --help\`.
