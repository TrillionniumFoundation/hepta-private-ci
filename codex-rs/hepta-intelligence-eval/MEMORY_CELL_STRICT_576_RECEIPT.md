# Strict native 576/576 completion: independently auditable evidence, not Cell superiority

**Source:** `675970bb610c70bb0ec30a2dee05c025440510e6`  
**Complete CI:** https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38114716982 — **success**  
**Immutable artifact:** GitHub artifact `11693693993`, ZIP SHA-256 `1db7f8f7c13a1f718d5065956f14d554d3fe328c415fac4bb145d1eaf9d913c8`  
**Exact tested tree:** `d280ba53070fb6457c04ff0d97fbb14ebbdbc3fb`

This was an actual model run under the **strict as-of source admission before retrieval**. The archive has **130 internally SHA-256-verified files**. All 576 preregistered policy answers succeeded; full repository regression/static checks, native timestamp census, source features, actual Reader calls and model artifact-only reloads completed. No inferred or imputed answer was introduced to fill a failed request. The entire result remains a previously exposed **development** benchmark, not an untouched prospective test.

## What the genuine successful experiment shows

| Observable | Pinned result |
| --- | ---: |
| Preregistered six-arm policy attempts / successes | 576 / **576** |
| TRAIN questions / admitted weak-source questions | 48 / 40 |
| Actual **positive-negative** Adapter-suitable TRAIN questions, prefixes 16/32/48 | **10 / 17 / 28** |
| Distinct lineage LoRA warm-start contrastive TRAIN questions | **10** |
| Actual original Reader executions across policy + Oracle diagnostic | **44**, zero failed |
| Original Reader cached calls across policy experiment | **543** |
| Separate no-evidence Reader control executions | **32**, zero failed |
| Source-choice flips of each learner on **test+transfer** | **0** |
| Emitted policy citation markers | **0** |
| Independently reviewed semantic citation precision | **null / not established** |

Across **96 matched frozen-policy comparisons per learning arm**, prototype, linear, gated, lineage-LoRA-gated and independent-LoRA-gated each produced no correct unseen selection improvement. One marginal rank flip was observed **only** for `lineage_lora_gated`, checkpoint 48, **retention**, question `locomo:conv-43/q217`. Both the original frozen choice and changed learned choice have **native-document support score 0**, and the Reader's original answer bytes stayed identical. This is an incorrect→incorrect rank movement, **not** a retained-memory gain.

All registered evaluation questions had multiple candidate windows. The absence of a learned decision improvement cannot be explained by forced single-source top-1.

### Actual Head fitting must be separated from correct source retrieval

The independently recorded saved Head before/after TRAIN telemetry measured 30 Head updates across 16/32/48, five learning arms and two Cell routes. On the native weak-source multi-positive/null objective, sample-weighted deltas were:

| Checkpoint | Linear | Gated | Lineage LoRA+gated | Independent LoRA+gated |
| --- | ---: | ---: | ---: | ---: |
| 16 | −0.4327 | −0.4282 | −0.4225 | −0.4255 |
| 32 | −0.4423 | −0.4458 | −0.4460 | −0.4461 |
| 48 | **+0.0084** | **+0.0075** | **+0.0061** | **+0.0066** |

Each value is a within-checkpoint, pre/post-fit **TRAIN loss delta**, not prospective held-out F1 or a test-label optimization target. Across the 30 measured Head updates, training source top-1 did **not** change. These negative losses can be dominated by the null-logit contribution and therefore do **not** show learning to select the correct source. The final checkpoint's positive average loss shift is an observed small regression on that checkpoint's training cut.

The original Reader generated **zero citation markers** across the 576 policy outputs. The result therefore contains neither structural policy citations nor an independent semantic citation precision denominator; **0 markers is not 100% citation quality**.

### Source availability and Reader capacity are separate bottlenecks

The 32 held-out source-coverage decisions, computed **after policy output generation** from only native document-level labels, show:

| Phase | Answerable native-source questions | Labelled support absent from candidate pool | Support present but frozen top-1 missed | Frozen top-1 hit |
| --- | ---: | ---: | ---: | ---: |
| select | 6 | 3 | 1 | 2 |
| retention | 6 | 3 | 1 | 2 |
| test | 6 | **2** | **1** | **3** |
| transfer | 7 | **0** | **1** | **6** |

These are **native document-source annotations**, not independently proven window entailment. A better Head cannot choose a source missing from its allowed pool. The evidence-recall bottleneck is most evident on the existing LoCoMo cuts. The Reader's answer diagnostic token-F1 remains low (frozen baseline test ~0.095 and transfer ~0.033 at checkpoint 48), while comparisons with the independent no-evidence Reader have wide or narrowly negative all-planned bounds. Thus no Reader evidence-sufficiency win has been certified.

A separate source-only LongMemEval chronology preflight counted **1,475 truly future source/query timestamp pairs among 23,867**, zero unknown date formats; strict preindex as-of filtering was applied. Those pairs are not prospective future-calendar retention measurements.

## Exact immutable replay, no new model execution

`stem_strict_success_audit.py` pins the exact completed source/tree, external ZIP SHA-256 and all internal manifest members. The auditor then checks all original raw and scored rows, original Reader/Head/checkpoint identities, the 30 Head before/after TRAIN records and their recomputed means, the native-document support ceiling, frozen-matched learner outputs, actual Reader/cache accounting, 32 isolated no-evidence controls and closed production/citation gates.

`test_stem_strict_success_audit.py` injects deliberately missing and rewritten rows, changed Reader/profile, falsified Head snapshots, missing source-control records and false production qualification. An independent GitHub Actions workflow downloads the previous fixed artifact and retains exact auditing source, generated report and signed-by-hash failure logs. **The audit's own hosted CI status is distinct from the successful historical model execution**.

**Decision:** halt Cell-number scale-out and claims of ≥99% semantic citation precision. Invest in stronger calibrated **retrieval + frozen Reader** baseline, then test whether trainable Head residuals can move labelled positive sources into top-1 *without* test-label hyperparameter tuning. Any new model improvement must be evaluated on genuinely independent source families/future windows with independent citation entailment judgment and complete p95/cost receipts. No production cutover, independent owner authorization or signed semantic review has occurred. `production_accepted=false`.
