# MemoryCell graph and Reader sufficiency: genuine local original-weight negative (2026-10-16)

**Research only / DRAFT / DENY_ALL / NO MAIN MERGE / NO FINALUSE.**

This is a diagnostic continuation of [source-only original-LoCoMo graph
evidence](MEMORY_META_GRAPH_ORIGINAL_LOCAL_AUDIT_20261016.md), **NOT**
production Reader integration, semantic answer certification, a stronger
Reader oracle or evidence that an evolved graph supplies usable QA.

## Frozen source and Reader identity

- Original LoCoMo input GitHub Actions staged artifact `11586991191` in
  [run 37862780268](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/37862780268).
  Original `locomo.json` SHA-256
  `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`.
- Exactly ten dialogue families; two questions per family selected using
  the existing SHA-ranked `hepta.fixed-reader.v1\0{question_id}`
  rule, **not by future answer label**.
- Original SmolLM2-135M weights SHA-256
  `5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c`.
  Original tokenizer SHA-256
  `9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c`.
- Existing `scripts/memory_cell/offline_smol_reader.py` implementation
  reproduced locally byte-for-byte, Git blob
  `c9567b43e5d15ca428baeb3a972b70435bcc7ed7`.
  `hepta.offline-original-smol135-fp32.v1` custom FP32 model, **not**
  verified bit-equivalent to official Transformers/BF16 `ReferenceReader`.
  Pinned 30-layer, 135M original model; no training or modified weights.
- Shared evidence-only prompt follows the existing system text requiring
  bounded citation markers `[E1]`, `[E2]`, etc. Greedy generation,
  maximum **32 output tokens**; evidence is label + speaker + at most 384
  characters of original source text. Original gold answers were not included
  in the model prompt. Token limits/failures are accounted explicitly.

## Important trust limitation

The local privileged worker used a **research-only retrospective input
construction**: it read publisher-provided evidence annotations to decide
which source IDs to show the Reader. The same Python process also held the
annotation file in memory while calling the model, though it did not put
answers in the rendered prompt. This is **NOT** a physically separated,
label-blinded model worker and cannot replace the existing workflow's
separate model/reviewer isolation. The annotated sources were not
independently verified sufficient; privileged performance is a diagnostic
upper-bound probe only, not a deployable retriever.

## Actually executed local results

- 20 preregistered historical question identities across ten original
  dialogues; all 20 scheduled.
- Exactly **19 original CPU generations succeeded**, one question had
  unavailable complete publisher evidence and was retained as unavailable.
  No failed model call was silently dropped.
- Only **14/19 successful generations** had a nonempty
  string-valued publisher reference answer; the rest are **unscored**.
- Diagnostic original-answer token-F1 mean among the 14 scorable questions:
  **0.12842058094585967**.
- Strict exact string matches: **0/14**. Reference-answer substring
  occurrences: **1/14**.
- Actually emitted required citation labels: **0/19**; citation precision
  is **undefined**, not 100%.
- The model frequently echoed or reproduced question/evidence JSON instead
  of issuing grounded, cited answers. No human semantic entailment was
  independently adjudicated.
- Original model generate-call time in the complete 19-call panel:
  **49.8431 s** (sum of per-request observed timings, **not**
  full system latency, training TCO, energy or hardware cost).
- The local executor initially timed out after 14 printed outputs
  **without sealing a full journal**: that failed attempt is explicitly
  excluded. A new resumable fixed panel then completed in five
  checkpointed batches with sync-before-ack.
- Complete 20-record unscored answer journal SHA-256:
  `2a691d8618a55f521241cd654160cc7f730616873cb42f2555e32707d33b8a57`.
  The answer-scoring step executed only after the final journal was
  sealed, **but the same privileged process had already loaded annotations**
  to choose publisher evidence. This does not satisfy physical label
  isolation. The journal contains original responses without correction,
  citation insertion, or semantic relabeling.

An earlier separately sealed *post-hoc* literal-in-evidence diagnostic
contained three questions × empty/BM25/publisher-evidence (9 original
generations). It gave publisher-evidence answer substring 1/3, BM25 0/3,
empty 0/3, and **zero emitted citation markers in all nine**. These three
were selected retrospectively because their published answers occurred
literally in the source. They are **not** a prospective cohort or
independent evidence sufficiency review.

## Decision and next admissible engineering work

**HOLD / NO-GO** on automatic MemoryCell split, memory parameter promotion,
unqualified learned graph routing and production Reader selection.

The actual original-source graph experiment found:
BM25 complete Top-8 sources 107/238; simple temporal window 121/238;
bounded temporal graph 125/238; graph over window +4/238 with
10-family exploratory sign-flip probability 0.3125. No robust graph
advantage over the cheaper adjacency baseline is established.

Independent next gate, in order:
1. Execute the existing **physically split** source producer, original fixed
   Reader and independent reviewer on the exact hosted HEAD, retaining all
   original failed/unavailable answer receipts. Use a *stronger reference
   Reader* and independently validated sufficient-evidence/missing-premise
   controls before optimizing Cell memory weights.
2. Keep Reader gains separate from graph/retrieval effects; enforce one
   compatible frozen Reader, prompt, input/context budget and actual costs
   per arm. Count matched TCO and unscored results.
3. Use fresh independent source families and future real windows, supported
   citations and external task completion. Ten correlated LoCoMo dialogues
   are not 200 independent samples.
4. Preserve scope, original evidence, revocations, deletion non-resurrection,
   current-generation checks, parent/child lineage, rollback and independent
   selector/acceptance. **Do not bypass `blocking-ci`.**

This report does not install or select models, create a second Memory owner
or change any HNMF production wire or release authority.
