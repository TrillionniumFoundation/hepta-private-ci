# Hepta V19 — Qwen3-0.6B strong reference on original 30×4 Reader evidence panel

**RESEARCH ONLY · DRAFT / SHADOW_ONLY / HOLD_NO_GO / DENY_ALL · NO MAIN MERGE · NO FINALUSE.**

Parent: V18 original 135M Reader prompt-format diagnostic, PR #2505, fixed ancestor
`392d0d3067b42dbcc9402c9ee1785de9177f4063`. This PR adds *only new research*
`research/hepta_v19_reader/**` and one read-only GitHub workflow; it does not
modify the V17/V18 producers, existing trained models, Worker, Neuron, native
NDU/FBSDE, CAS/CNS, production action owner or `main`.

## 1. Primary question and strict nonclaims

Can a pinned **different, larger pretrained Reader** answer the *same original*
LoCoMo source-first questions with the identical delivered evidence source bytes
more successfully than the previously measured 135M Reader? If Qwen improves,
record it as a **Reader-capacity / tokenizer / model-alignment difference**, not
Cell learning, shared Stem specialization, System 2, NDU or automatically
qualified semantic reasoning.

The original 135M experimental outcomes (V17/V18) showed weak literal hits but
**zero full answer byte matches** for the source-first 30 question panel. Eight
publisher targets are missing. Even the publisher-annotated 240-char excerpts
are *not independently verified sufficient*, and an answer literal in a source
does not establish entailment. V18 prompt templates did not repair this Reader.

**Current local observation:** the original 359 MB archived GitHub artifact is
available and its complete SHA256 has been physically rechecked; the original
30-case source has been re-materialized, and **two independently authored
source-first builders agree on all 120 literal requests**. The actual Qwen3
1.5 GB weights are **NOT present on this local host**; direct network model
retrieval is blocked. No local Qwen forward, Qwen answer, Qwen accuracy gain,
new end-to-end success, or human semantic review is claimed. New source tests
with fake tokenizers or fabricated numerical packets are adversarial contract
tests, never original model results.

The read-only research-branch workflow attempts genuine physical model staging,
96 native Qwen generation calls and a rerun of the original 135M comparator.
Until the exact source-head hosted workflow **terminates successfully** and
its sanitized artifacts are reviewed, there is **no real Qwen outcome**.

## 2. Strict causal/source identity

The benchmark is not prospective: ten retrospective original LoCoMo conversation
roots (`conv-26`, `conv-30`, `conv-41`–`conv-44`, `conv-47`–`conv-50`). Select
the three lowest SHA256 IDs per root before opening publisher answer text,
exactly as V17. The 30 source-first cases expand into four fixed arms:
`none`, `retrieved` (question-local BM25 Top-3), `annotated` (publisher **source
addresses**, at most three) and `lesion` (first annotated address removed).
Reference implementation must preserve original question, speaker, original
utterance ID, and the same first 240 characters of each source. **Do not copy
publisher answer labels into inference prompts**. Source text can naturally
contain an answer literal; this is not label leakage.

The V17 manual model consumes its own archived ChatML bytes; Qwen3 consumes
*semantically equivalent content* via its official `apply_chat_template` with
`enable_thinking=False` and `add_generation_prompt=True`. Qwen token IDs and
input-token counts are model-specific. Both use a maximum of 24 new tokens,
but **these are not equivalent compute/token budgets or identical encoded bytes**.
Never credit improvements to a shared Stem, learned Head, routing or NDU.

Exact source fingerprints:

- Source archive `11586991191`: ZIP SHA256 `07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af`.
- Original LoCoMo raw source SHA256 `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`.
- Original 135M weights SHA256 `5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c`.
- Original frozen V17 plan digest `6b508c3dee8fef3dd6e43ba58117baed927a358de7a02d5b47236cfbb0a64938`.
- Qwen3 source model: `Qwen/Qwen3-0.6B` publisher revision `16706fc57485378d4ffaf54139b29ccc66ae08fa` (Apache-2.0).

## 3. Material and model execution authorization boundary

Only SHA-pinned original GitHub ZIP is accepted. `v19_recover_original.py`
streams preselected original filenames from TAR; it never extracts untrusted
paths. Every known file has a byte-length and SHA256 check. No silently
substituted model weights, tokenizer or sources.

`v19_qwen_material.py` requests the exact publisher commit and *complete
publisher file metadata*. For ordinary files, require published blob OID and
byte length and verify actual Git blob SHA1. For LFS/Xet weight/tokenizer data,
require published LFS SHA256 plus byte length; copy to private *regular* local
files and verify again before and after inference. No mutable tags, unsupported
files or symlink escape. Pretrained dependency imports occur only after strict
preflight; no fake-model fallback. Only `torch.generate` with deterministic
sampling disabled is qualified in this experiment. The module counts root-model
forward-hook calls, input/output tokens, actual CPU and wall time; this is NOT
GPU usage, full FLOPs, kernel-level trace or independent signed model-host proof.

A private `0600`, `O_EXCL` journal is fsynced **before every physical model
invocation**; interrupted runs have unsealed/partial results and cannot be
published as a completed population. Duplicate native model inputs are
computed once; distinct physical inputs are bounded to the original 96 unique
messages, with 120 logical arm outcomes. Shared cost is counted physically
once; assigning a shared call to its first alias is bookkeeping, not a
causal intervention or matched-policy cost comparison.

## 4. Independent postseal review

`v19_reference_review.py` does not import the V19 inference planner. It
independently reconstructs original questions, support addresses, question-local
BM25, all four arms and the native-model message bytes. It verifies the original
publisher corpus, source-owner manifest, source-first selection, original V17
request hashes, Qwen revision, model bytes, tokenizer-produced input IDs,
output token IDs, decoded original answer bytes, journal identity, citation
syntax, real forward counters and actual recorded costs. Tampering remains
denied even if untrusted hashes are recomputed.

Publisher labels are first reopened **after both pretrained model processes
exit and seal**. To avoid leaving unrestricted original gold on disk while
model code executes, the workflow deletes hidden labels and original raw corpus
before inference and re-downloads/re-authenticates the original ZIP **after**
both model seals. This is process-stage separation, **not hardware-enforced or
cryptographically independent isolation**. Github runner owners and code could
in principle access the public dataset by other means.

Report, separately by original arm, the correct denominator of available
publisher targets, strict raw text equality, weak answer-substring occurrence,
valid citation addresses, foreign citations, input/output tokens, physically
charged CPU/wall and declared unsupported metrics. Label-missing cases remain
`unknown`, not false errors. A citation marker within delivered sources proves
only syntax and address consistency, **not independent semantic entailment**.
The published artifacts contain **only sanitized numeric/digest results**.
Original questions, dialogue, target answers, source packets, model weights,
private raw answers or per-question generated texts are never uploaded.

## 5. Falsifiable gates and stopping decisions

- **Reader adequacy:** independently human-reviewed sufficient evidence plus
  human/externally adjudicated answer correctness and cited-evidence entailment.
- **Capacity attribution:** keep models and initial evidence identical. If Qwen
  improves, record as Reader/model capacity, not as learned Cell or retrieval.
- **Actual cost:** physically compare full inference/initialization costs and
  observed input-token differences; no equal-cost inference claim until matched.
- **Future generalization:** independent source families and prospective time
  windows remain absent; all questions are retrospective, correlated within 10
  original roots. Multiple arms are repeated questions, not new independent
  roots.
- **NDU:** never activate FBSDE, System 2, split/fusion, preference optimizer,
  FinalUse, CNS/CAS writes or main merge from weak literal/citation scores.
- **Negative/abort:** source pin, publisher model SHA, original source bytes,
  role-string, tokenizer, preflight file-set, journal, counted forward, missing
  answers, duplicate logical inputs, source-list contamination and authority
  mutation failures all **fail closed**.

No results in this file certify a model winner. `HOLD_NO_GO` is mandatory.

## 6. Reproducibility

From the selected V19 branch:

```bash
export PYTHONPATH=research/hepta_v17_reader:research/hepta_v19_reader
python3 -S -m unittest discover -s research/hepta_v19_reader -p 'test_v19_qwen_reference.py' -v
python3 -O -S -m unittest discover -s research/hepta_v19_reader -p 'test_v19_qwen_reference.py' -v
python3 -m compileall -q research/hepta_v19_reader
```

Exact-HEAD CI: `.github/workflows/hepta-v19-original-qwen-reference.yml`.
Source tests never download model files or claim physical Qwen inference.
A single research-branch push triggers the physical Qwen stage; PR validation
only runs nonnetwork source/adversarial tests. `blocking-ci`, architecture and
other governance checks retain their original meaning and cannot be bypassed.
