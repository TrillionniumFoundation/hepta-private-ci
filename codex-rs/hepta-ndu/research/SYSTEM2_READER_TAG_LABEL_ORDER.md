# Frozen Qwen 0.5B: TAG-code label echo versus two-source binding

This is a **research-only** controlled test inside draft [PR #1546](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1546). It does not alter the production Reader, model weights, tokenizer, NDU/FBSDE/Riccati implementation, shared Encoder, or runtime evidence owner. No train or optimization steps are scheduled.

## Actual existing neural evidence

The completed [320-call 0.5B lexical factorial](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38333959891), source `4fe8ac3d75132a21abf2c3e9d172c637e1bb6f91`, returned an externally pinned artifact **11784676839**, SHA256 `0fd2a2aa60c0c28bdd61a2566262558410bb66c6997355aa610fe98b89aabc19`, with zero failed inference calls. Across 20 fixed synthetic devices:

| Registered wording / code prefix | Single correct fact: exact answer | Correct + competing fact: exact answer | One irrelevant code: exact refusal |
|---|---:|---:|---:|
| clearance token / TOK- | 0/20 | 0/20 | 20/20 |
| inventory code / TOK- | 0/20 | 0/20 | 18/20 |
| clearance token / TAG- | **20/20** | **1/20** | **0/20** |
| inventory code / TAG- | 17/20 | 0/20 | 0/20 |

For the `clearance token / TAG-` correct-plus-competing condition, 19/20 original outputs were **exactly `E1`**, not answer codes. In its irrelevant-code condition, 20/20 outputs were ungrounded TAG-code copies rather than the prescribed refusal. Zero evidence yielded 19/20 correct refusals. This is an extraction–refusal tradeoff; the factorial's preregistered primary condition **failed**, even though single-fact copying was perfect.

The current latest-head factorial archive audit checks both original and factorial output SHA pins, all 320 source/Reader identity/proof/cost receipts and paired 2×2 lexical effects. It is an independent, zero-neural-call audit; this proposal does not change its source or retroactively select the successful spelling as a production winner.

## Predeclared next question: does `E1` induce two-source label echo?

Freeze Qwen2.5-0.5B-Instruct **exact same** pinned revision `a338b55dd21219a5f4da42bc11a9313d1a27d4cc`, tokenizer/snapshot inventory, greedy 64-token generation, unchanged `clearance token / TAG-` system instruction, same source text bytes and question within each labeled/unlabeled pair. Use **20 new synthetic device identities from catalogue positions 80:100**, which are disjoint at question-ID level from the factorial 60:80. This is still the same artificial task family, not independent natural-language or realistic safety evidence.

Five evidence arms and source presentations:

| Evidence arm | Presentations | Planned calls |
|---|---|---:|
| One correct fact | labeled and unlabeled | 40 |
| Correct fact + competing TAG, target first | labeled and unlabeled | 40 |
| SAME two facts reversed, target last | labeled and unlabeled | 40 |
| One irrelevant TAG fact only | labeled and unlabeled | 40 |
| No evidence | unlabeled once | 20 |
| **Total** | nine registered conditions | **180** |

The `labeled` prompt is byte-exact to the existing factorial JSON serialization and system template, except the predeclared new data. The `unlabeled` prompt deletes only the `label` key of each evidence object. Input token counts can change; **not token- or CPU-matched**. The target-last arm reverses the same source IDs and snippets and does not silently pick a more favorable decoy. Source choice receives only question and source bytes, never `case.answer` or any saved Reader prediction.

## Trust, failure, and promotion controls

1. **Before inference:** verify the previous Qwen 160-answer artifact external SHA256 `853afed48368b2c4e562191c7ed6d6bf28492bd80ec95634119b8afc7d43ab37`, internal inventory, original model identity and exact Hugging Face checkpoint files. Hosted CI performs all MemoryCell regressions and Ruff F/E9 static checks. No model download or arbitrary remote code execution after verification.
2. **During inference:** flush and fsync a start and a complete/failed row per position; preserve actual input-token count, generated-token count, decoded original answer, model/source/bundle digests and CPU nanoseconds. Exceptions and missing work are not imputed as negative predictions or free computation.
3. **After raw-answer SHA seal:** score exact answer-only output, correct refusal on insufficient evidence, label-only echo (`E1`,`E2`, etc.), over-refusal, wrong/unsupported TAG copies, and paired outcome transitions (both, labeled-only, unlabeled-only, neither). No external generated citations are credited to the Reader.
4. **Fixed primary candidate:** the `unlabeled` presentation. It requires at least **15/20 exact answers** in *each* of the one-source, target-first and target-last supported arms, plus **18/20 exact refusals** in each no-evidence and irrelevant-TAG arm. Passing would qualify *only another independent confirmation*, not general capability or production promotion.
5. Per-question paired discordance is descriptive; with only 20 correlated fictional devices and different input-token lengths it does not establish a general vocabulary-causality or compute efficiency result. The deterministic grammar/symbolic reader is a separate strong control and can solve this closed symbolic task without neural inference.

### Reproduction (exact head)

Run the standalone workflow `hepta-system2-reader-tag-label-order.yml`; it downloads/pins the original model and source archive. With the exact checkpoint staged locally:

```sh
HEPTA_MEMORY_TESTED_COMMIT="$(git rev-parse HEAD)" \
python scripts/memory_cell/system2_reader_tag_label_order.py \
  /tmp/original-qwen-160.zip /tmp/qwen-original /tmp/qwen-tag-label-trial --development
```

Only original immutable response artifacts establish the frozen Reader behavior. Local fake-Reader tests check experiment mechanics and journaling; they are **not** neural answer results. `production_accepted=false`, `independent_natural_task_evidence=false`, `reader_adequacy_established=false`, `general_ndu_fbsde_gain=false`.
