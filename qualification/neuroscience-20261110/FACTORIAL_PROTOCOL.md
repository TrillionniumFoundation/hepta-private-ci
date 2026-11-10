# HPCA Core × NDU factorial evaluation preflight — HOLD_NO_GO

This independent research-only protocol **does not run a model or external task**. It adds a machine-checkable *input contract* for the next real experiment, separate from the routed/shuffled/scalar/no-eligibility mechanisms in `study.py` and the HPCA microbenchmark in #5739. Fixtures in `test_factorial.py` are synthetic and **not experimental results**.

`python3 -m unittest -v test_factorial.py` runs ten contract tests. A prospective evaluator can provide `FactorialRow` JSONL (`python3 factorial.py --trials frozen.jsonl`); no dataset, human labels, GPU, or owner attestation is bundled. The output is always `HOLD_NO_GO` / `DENY_ALL`.

## Fixed identities and contrasts

- **A:** Ordinary core + ordinary controller; **B:** same ordinary core + NDU.
- **C:** Hepta core + ordinary controller; **D:** same Hepta core + NDU.
- Report **B−A**, **D−C**, **D−B**, and **(D−C)−(B−A)** on **net value** after full observed costs. This is four predeclared contrasts, not a post-hoc D−A comparison. Keep `core_model_digest` fixed A/B and C/D, `controller_digest` fixed A/C and B/D, with distinct core and controller identities. Compare equivalent *capacity opportunity*; a declared capacity contract is not an empirical proof of equal capability.
- Each `(episode_id, training seed, family)` must provide all A/B/C/D arms. All arms use identical frozen task, training dataset, evaluator, capacity and feedback contracts and opportunity ceilings (query/training/compute/feedback bits). An actual finalized source manifest must specify base, trainable adapter, tokenizer, weights, training split A, independent prospective test B, and distinct next use C. They cannot be inferred from these hashes.
- All outcome receipts must be distinct. Digest syntax does not authenticate owner signatures, data rights, independence of the evaluator, non-leakage or successful effects.
- Declare sparse/dense ACT/CTRL and the five task families plus retention separately. Exact-key RAG, latency- and failure-matched controls, full seven-lineage clocks and frozen old-task/OOD panel are further required real experiment arms; this input preflight does not silently supply them.

## Statistics, missingness and costs

- Record actual `wall_time_us`, `cpu_time_us`, `gpu_time_us`, `failed_actions`, as well as `gross_value` and `full_cost` (same declared utility units). Include time, inference, optimizer, verifier, storage, retrieval, data rights, missed/failed actions and retry cost in `full_cost`; account real monetary costs and whether the budgets were actually obeyed in the external owner audit. Budget equality here checks *declared ceilings*, not measured fairness.
- Preserve nulls: any missing primary gross outcome or full cost suppresses **all** effect estimates and p-values; any missing old-task result suppresses retention contrasts; any missing actual resource reading suppresses the resource summary. Never silently discard nonresponders.
- Per-seed averages across all episodes/families form **one** paired randomization cluster. Exact one-sided sign flips are computed only for 1–16 seeds; more seeds yield `null` pending a predeclared scalable method. Holm adjusts four prespecified contrasts. These p-values remain exploratory unless seed sign-exchangeability, family-wise hypotheses, power, independent training repeats, selection bias, and practical benefit thresholds are certified separately.
- NoUpdate/Adopt cannot be established by selecting positive numbers in a JSONL. Real StageOwner evaluation B, negative NoUpdate when regressions occur, distinct C consumer, actual cold recovery and cost/side-effect reconciliation remain separate owner-controlled tests.

## Gate interpretation

A passing test certifies **only input-contract mechanics**. Even if every input flag reads true and every p-value appears small, `credential_verification=NOT_PERFORMED`, `owner_attestation=NOT_PERFORMED`, `realized_cost_audit=NOT_PERFORMED`, `qualification=HOLD_NO_GO` and `authority=DENY_ALL` are unchanged. Never auto-deploy or equate this shadow preflight with independent scientific effect.
