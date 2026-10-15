# Frozen Reader one-hop cardinality and source-order adequacy

Research-only, no default-model or production change. Proposed as a follow-up to the completed original one-hop [GitHub run 38254837899](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38254837899) and completed 128-token [GitHub run 38257354467](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38257354467). This diagnostic uses exactly the same frozen Reader, original question IDs and 64-token deterministic decoding. No new Encoder, training step, NDU/FBSDE solver, Riccati change, or native release.

## Observed hosted parent, not merely queued

The original one-hop Reader experiment on source `b38174570e3afe9299208945422b13f527bfd416` completed 80/80 model calls, all Python and Ruff gates passed, and produced GitHub artifact `11751763282`. Outer ZIP SHA256: `4e9e48bb266a7390089da5c80172d033d99522b1e786b05fc01973b63275ab03`. All 28 manifest entries, the Git source/tree and immutable 80-row raw seal `092b1e9dfabef0fd710fe92512a1f43215f25b67035b43bf674e01ee11f4096f` were checked locally. The original nested model archive is pinned to `07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af`.

The original four arms (20 *previously exposed* synthetic one-hop questions):

| Condition | Recognized correct target literal | Grounded/cited complete answer | Prescribed refusals |
|---|---:|---:|---:|
| Target one-fact E1 | 18/20 | 0/20 | 0/20 |
| Target E1 plus two unrelated *device-token* facts | 0/20 | 0/20 | 0/20 |
| Three unrelated device-token facts | 0/20 | 0/20 | 0/20 |
| No source | 0/20 | 0/20 | 0/20 |

Raw evidence is more decisive than source count alone: all **20/20** target-plus-two-decoy outputs were exactly the label-only sequence `E1\n\nE2\n\nE3`. In one-fact E1, 18/20 included the requested token but lacked bracketed `[E1]` citation. All 20 no-evidence outputs were exactly `"E1"`. These are actual Reader answers, not an inference or a symbolic proxy. A label-only answer is NOT a valid citation.

The 128-token experiment on 32 correlated multi-hop counterfactual questions per arm also completed: matched `joined` exact target mentions 3 to 5, reverse-joined stayed 16, missing-premise false copies declined 8 to 4; all **96** new calls had zero fully grounded citations and zero prescribed refusals. Extending length adds compute and did not qualify output behavior.

## New fixed interventions — source cardinality and relevance salience

The sole experimental input change is the **number, order and type of original source snippets**; question, Reader weights, system instruction, chat template, 64-token greedy decoding, full input token cap and source identity stay fixed. All source documents are original bytes and checked through the unchanged research `EvidenceBundle` before each use. Question-to-source matching reads only the question and source text; it never uses the generated target token or `case.answer`.

Seven registered NEW arms on the same 20 previously exposed single-hop tasks (140 planned model calls):

| New arm | Delivered evidence (in order) | Test |
|---|---|---|
| `target_decoy_two_first` | Target fact, one unrelated device-token fact | Two records, target first |
| `target_decoy_two_last` | Unrelated device-token fact, target fact | Same exact pair in reverse |
| `target_context_two` | Target fact, one unrelated non-token relation | Content rather than count |
| `target_decoys_three_last` | Two unrelated device-token facts, target fact | Exact original three facts with target last |
| `target_context_three` | Target fact, two unrelated non-token relations | Three records with fewer competing tokens |
| `decoy_one` | One unrelated device-token fact | Source cardinality one, no support |
| `decoy_two` | Two unrelated device-token facts | Source cardinality two, no support |

Historical `single_fact`, `fact_plus_distractors`, `distractors_only` and `no_evidence` outputs are reused *without new Reader calls*. This is a diagnostic, not an independent test set: all 20 synthetic worlds were already used, and new intermediate source snippets/strings come from the same fixed corpus.

### Fail-closed provenance and assessment

Before loading any new Reader, stream-verify the outer artifact digest, ZIP entry paths and modes, its **entire** internal manifest including the large nested historical model ZIP, exact generating commit/tree, immutable source IDs, source bytes, original model/tokenizer identity, original prompt and generated ID receipts, and all original scoring fields. Run the unchanged full MemoryCell regression and Ruff gates. The frozen model staging uses only that previously authenticated model archive.

Each new attempt records the planned question/arm, selected original source IDs, prompt identity, input tokens, exact response token digest, generated tokens, CPU/wall time and failure. Flush+fsync each start/result. Seal all new raw outputs BEFORE scoring. Failed calls stay unknown and retain their planned denominators; no guessed zero-cost negatives.

Separate: target-token mentions, strict single-token answer, actual [E#] bound citation to the required source, exact prescribed abstention, unsupported correct-token copying, and literal label-only generation. Historic answers are never postprocessed. In all seven arms, a task counts as a grounded Reader success only if the frozen model itself produces a correct token AND cites the actual correct source.

Before seeing model outputs, admission for *independent future confirmation only* requires **at least 15/20** fully grounded+cited successes for BOTH two-source order variants, **at least 18/20** exact refusals in BOTH decoy-only variants, and zero incomplete Reader calls. This is intentionally stricter than token-string matching. The other three positive variants are mechanism controls and cannot be selected after seeing results as a new winner.

This is NOT a new neural reasoning benchmark, not equal-token or equal-FLOP computation, not independent semantic review, and not evidence of general NDU/FBSDE or multimodal reasoning. If the frozen Reader stays inadequate under all registered controls, the next development decision should be Reader architecture/citation-training or a stronger fixed Reader baseline, rather than larger Cell search or more synthetic depth.
