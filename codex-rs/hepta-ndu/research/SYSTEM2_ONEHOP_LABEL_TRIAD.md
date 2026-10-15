# Pinned three-presentation Reader audit: E1/E2, R1/R2, no labels

**Scope:** Research-only, draft PR #1546. All 200 underlying responses are **already completed** on the same 20 exposed synthetic one-hop questions. This audit invokes **zero** models and makes **zero** new answer claims. The old Reader weights, answer-only system instruction, question, trusted original excerpts, source order, greedy 64-token decoding, and scoring are unchanged.

## Immutable provenance

Three separately completed hosted artifacts are read-only and externally pinned:

| Record | Hosted ZIP SHA256 | Generating commit | Raw output SHA256 |
| --- | --- | --- | --- |
| Original cardinality 140 rows | `9f4a4ed9429212b98befffca27a297780d61317eaed8be519b1cb6880037f121` | `0abf776c...` | `cc04bd7fd7ecc5aed4234f9512c344eb6feffe8dd0e858507bf1688dff4cda61` |
| E-labeled and unlabeled 140 rows | `a278014bae564336fc4d63335154cadbf14febc73620d958f45648b17ca0622a` | `24a11759...` | `6f630a86d374658049377d4611f92fd6c0dd6626c267eef7c37d77f07f5aeaa2` |
| R1/R2 labeled 60 rows | `7341c519fc80b66a0156f0b349516ff260042dce9e5c9b94e9af49e362bf9e9b` | `838da1f5...` | `1cbcdfbc6512d93ee11f9a2cafb5414f0987d0fcfd0b07b1a0d9e576b258b04b` |

The implementation validates every outer ZIP against the external pin and every inner file against SHA256SUMS, checks exact generating commit/tree and original raw output seals, replays the existing **full 140-row E-code audit** against the original cardinality archive, and separately replays the entire **60-row R-code score, model/source identities and complete start journal**. For every E/R matched condition it requires the R-code receipt's compiled *original E-code* input-token digest to exactly equal the archived E-code Reader input-token digest. Every presentation must bind to the exact same original source IDs, byte excerpts, Reader identity and question.

## Measured observational result, local exact-source replay

Three evidence states (`single_fact`, `target_decoy_two_first`, `decoy_one`) × the original 20 question IDs = **60 paired subjects** and **180 underlying model calls** in those conditions. The E/non-E archive also includes 20 no-evidence controls, so 200 completed historical model calls are pinned in total. These are **not** 200 independent examples.

| Output event (all 60 paired subjects) | E-coded JSON | R-coded JSON | Unlabeled JSON |
| --- | ---: | ---: | ---: |
| Exact target-only answer | 0 | 0 | 0 |
| Exact prescribed refusal | 0 | 0 | 0 |
| Only an E/R label list | **34** | **0** | **0** |
| Continues original input JSON | **26** | **60** | **60** |
| Hits the 64-token ceiling | **26** | **60** | **60** |

E and R prompts have precisely **equal input token counts for all 60 question/policy pairs** (but DIFFERENT input token IDs). The total input token count in these pairs is 15,370 under each code. Removing label properties lowers the aggregate input-token count to 14,970. The E-to-R lexeme change alters the failure *format*, not answer or refusal ability. E and R generated token totals are **1,766 and 3,840** respectively: those runs are **NOT output-compute matched**, although E/R input lengths agree exactly. The label experiment never established trustworthy citations; the answer-only prompts do not request them.

The observed E-only label echo is a fixed-synthetic, same-prompt-architecture behavioral association. It is NOT a statistically independent natural-language sample, an online causal guarantee across settings, a retrieval result, new learned value, semantic correctness, NDU/FBSDE reasoning emergence, or a production-safe prompt redesign.

## Fail-closed audit contract

The audit retains each of the original 20 question denominators per source arm and reports an eight-cell E/R/unlabeled response-pattern histogram for each of eight metrics, plus actual input/output token differences. If a registered call has failed, its paired result is **unknown**, with conservative bounds, not negative evidence or zero work. Existing response files and scoring are never modified; all calculations happen **after** original model-output seals. A missing/modified source, changed score, extra/missing row or model/source mismatch aborts before reporting a qualified result.

The main inherited Reader adequacy result is negative, so the disposition remains `reader_adequacy_unqualified`. The Qwen2.5-0.5B-Instruct model-capacity reference is a **separate pending experiment**, not a model-accuracy gain and not a FLOP-matched NDU test.

Reproduce on an exact repository checkout using Python with the original pinned zip files and the three arguments to `system2_onehop_label_triad_audit.py`; the fourth argument is the new report path. No model checkpoint is loaded.
