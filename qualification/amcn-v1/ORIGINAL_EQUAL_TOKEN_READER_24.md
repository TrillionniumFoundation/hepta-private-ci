# AMCN real Reader: 24 naturally equal-input-token historical tasks (DENY_ALL)

**2026-10-15 · PR #2085 · SHADOW only; NOT an independent Reader/Head/graph qualification.**

## Rationale

The original 10-family LoCoMo TRAIN-only physically learned six tiny Head tensors improved retrospective *publisher-weak support Hit@3* over BM25 by 10 of 400 questions, but typed and equally sized pooled Heads were tied. An earlier real six-question Reader trial deliberately selected Head route disagreements and had **unequal actual Reader input Token counts**. That does not answer whether trained parameters improve end-to-end task success under equal Reader context.

This separate cohort fixes a **natural** per-question input Token budget *without* truncation, padding, substituting evidence, or opening publisher answers: among all 400 original questions in the two retrospective heldout families, use only original three-arm prompts whose authentic archived ByteLevel BPE token counts are exactly equal. Select the twelve lowest SHA-256(case_id) questions in **each** historical heldout source family. **73 eligible in conv-49; 78 in conv-50** (151/400 total). This is a reproducible length-conditioned diagnostic cohort, **not a random representative sample of 400** and not 24 independent source families.

Arms: BM25 frozen, TRAIN-only AdamW *two-head pooled / untyped*, and equal-trainable-parameter *two-head typed*. Reuse the exact frozen source snapshot, all original 1,986 rank decisions, 829 heldout physical Head rank predictions, same 30-layer BF16 archived Llama Reader/ByteLevel BPE/tokenizer/config/prompt, three final evidence slots, deterministic greedy maximum **48 generated tokens**, context<=1024. All original Head material is physically SHA-pinned; no new Encoder/Head training, source mutation, serving activation or production authority. **Reader input tokens exactly match for each of the 24 questions across all three arms.**

Only 8/24 BM25 vs learned Head final source Top-3 sequences change; **0/24 typed vs untyped sequences differ**, so this cohort has no power to distinguish typed and pooled Reader behavior. The stronger earlier six-question contrast intentionally retained those disagreements but lacked equal actual Reader token lengths. No merging of these separately selected cohorts is allowed.

## Physically executed local run (isolated container, not user's dot host)

Original user-owned GitHub source artifact `11586991191`, outer SHA-256 `07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af`. Original raw model weight and tokenizer bytes used, not synthetic answers. Actual CPU Torch 30-layer greedy generation: **72 successful calls / 72 attempts / 0 interrupted**. `starts.jsonl`, `raw_answers.jsonl`, and immutable `seal.json` retained in the private working directory; entire raw model text, dialogue, publisher gold and weights are intentionally not committed or uploaded as Actions artifacts.

* Source-only original 1,986-case roster SHA-256: `ac5f95085e5b223f81e888236e2c162f1ef45a3d1f52ad3e903fde48a629a633`.
* Frozen 1,986-case original rank file authoring-run SHA: `25bd9754e1da4ee5ddf620e7f3c734f06650568278c6aab51916d55046baef99`; stable scientific rank decisions `bd63d0555a8e5b0cde444023d40da4570987226451fb97a2284d0bd285614a66` (per-run elapsed wall is intentionally not fixed).
* Physically generated heldout Head rank prediction file: `a937d4fd91e0c75cf4ddd265760c0b6c4cf1ed0947ad0c5be323686aca7391a3`.
* Precommitted 24-case label-blind Reader plan (canonical raw file SHA): `19ee2274e8db89fba8526b2f7d6f711eebd3ebae5c28c8612d6096adf919bd09`. Two independent plan construction processes produced the same hash.
* Complete original Reader `seal.json` (SHA): `664842c0cf4feeef8319bd134ba56ca82eff99bdeef1ea347f9a59b1a5104da0`. Publisher labels first opened *after* this seal existed.
* Post-seal raw publisher evidence and answer file (private, never uploaded): `f2046ec20eba22a36478eb9f881e84072b1a2d9408635d40f81eef38d26f09d1`.

| Real heldout historical cohort / metric | BM25 | Pooled two-Head | Typed two-Head |
|---|---:|---:|---:|
| Original questions / Reader calls | 24 | 24 | 24 |
| **Actual Reader input tokens** | **5,744** | **5,744** | **5,744** |
| Original Reader output tokens | 701 | 709 | 709 |
| Publisher weak any-supported Top-3 | 12/24 | 12/24 | 12/24 |
| All publisher weak supports Top-3 | 10/24 | 10/24 | 10/24 |
| Literal answer equality to original publisher label field | 0/24 | 0/24 | 0/24 |
| Hit 48-new-token generation ceiling | 10 | 10 | 10 |
| Standard publisher `answer` questions | 20 | 20 | 20 |
| Separate category-5 `adversarial_answer` questions | 4 | 4 | 4 |

Publisher category-5 examples do **not** include the ordinary `answer` key. The separate post-seal score retains those as `adversarial_answer` labels, never reclassifies them as `answer` or as independent semantic truth. No answer text was reclassified as model success; strict string equality is **not** a semantic evaluator.

**Negative result:** Trained Head changes 8 originally served retrieval sequences, but does **not** improve weak support in this natural exact-Reader-input-token cohort; no observed literal-match improvement. The original pooled/typed Heads are identical in final Top-3 selection for these 24 cases. Numeric input-token equality does **not** imply equal total pipeline compute, because BM25-only does not pay for MiniLM and Head training. Reader generated token counts also differ (701 vs 709), so actual total inference compute is not exactly matched. This is still only **two original historical families**, no genuinely prospective calendar windows and no independent semantic answer/citation adjudication.

## Reproduce, retain and refuse

The research module `amcn_equal_token_reader.py` exposes separate `plan`, `generate`, `resume`, and `score` phases. `plan` consumes only original source/unchanged Head prediction material with independent file SHA pins; its output contains **no gold answers**. `generate` verifies actual original Reader weight and tokenizer SHA, makes one physical model call per registered case/arm, appends+fsyncs attempts and answers and seals only after all 72 completed; incomplete attempts must be recorded and retried. After success seal, a separate scorer may open original publisher targets and source labels with SHA lock, recount every raw answer and tokenize it with the original tokenizer, compare against the immutable seal and original journal SHA, and retain all twenty-four cases in denominator. A BPE decoded string is **not a one-to-one commitment to the original token sequence**; integrity is established by externally pinned raw journal plus original immutable sealed token IDs, not by a self-hash after re-tokenization.

The read-only `.github/workflows/hepta-amcn-original-equal-token-reader.yml` independently downloads the original fixed SHA archive, recomputes 1,986 frozen Encoder ranks and physical Head training/forward outputs before constructing the plan, executes all 72 real Reader forwards, opens publisher gold only after successful seal, then runs the full actual-material tests and uploads **source/test/negative/sanitized receipts only**. It must not publish raw dialogue, model weights, Head tensors, publisher answers, original prompt packets or unredacted Reader text.

Local same-exact-original-material regression: **15/15 tests pass**, including two tests that require the physically completed original journal, tamper rejection and correct standard/adversarial publisher label isolation. This local run is **not from the user's dot host**, and official Transformers/Tokenizer parity is not independently approved. GitHub `blocking-ci`/Architecture and this exact-HEAD Reader workflow must pass independently. No E1 full-task gain, E2 type differentiation, E3 learned-graph incremental task benefit, auto-fission/fusion, Model Selection, FinalUse or production use is authorized.

**DRAFT / SHADOW / DENY_ALL.**
