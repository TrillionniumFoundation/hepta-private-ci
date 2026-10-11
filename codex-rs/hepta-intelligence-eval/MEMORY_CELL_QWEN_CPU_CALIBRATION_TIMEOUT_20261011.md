# MemoryCell: measured Qwen CPU calibration feasibility (2026-10-11)

This is a **real hosted-run failure analysis**, not a new model-quality result, a GPU benchmark, an excuse to waive a test, or permission to train/adopt a memory parameter.

## Actual GitHub Actions sources

- Experimental source SHA: `02c12b4aff0d589d10e5ed25d22b05d794ca96a0`.
- Run: https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38111452963
- Uploaded failure/partial artifact: `11696974258`, `memory-strong-rag-calibrated-reader`.
- GitHub-reported ZIP SHA-256: `129351221d56c9668c57e33f8dec79a6443c0252675752085538375b12ca25a8`.
- Original archived event plan SHA-256: `9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897`.
- Actual CPU runner reader configuration: pinned Qwen2.5-3B research revision, PyTorch CPU, BF16, eager attention, deterministic generation, `OMP_NUM_THREADS=2` and `MKL_NUM_THREADS=2`.

The scoped `experiment-format` and **42 strong-RAG regression tests** passed. Source restoration, pinned encoder staging, exact original retrieval replay (`prep/calibration-plan.json` SHA-256 `205c9a46b3776a7e8f3063b8eb63cf7a0f5cd4647a1947b6e90d2b2e0d570e45`), and pinned Qwen weight staging completed. The reader job was then **cancelled** during real calibration, not during source/format/retrieval.

## Original raw answer journal (not projected model scores)

Read `calibration/raw-answers.jsonl` from the uploaded artifact: **4 complete lines** from the first of eight calibration questions, out of the registered 40 calibration attempts.

| Completed call | Prompt input tokens | Generated tokens | Recorded inference seconds |
| --- | ---: | ---: | ---: |
| k=1 | 504 | 7 | 923.308 |
| k=2 | 787 | 6 | 1457.513 |
| k=3 | 1076 | 14 | 2045.598 |
| k=4 | 1370 | 13 | 2641.516 |
| **Total** | **3737** | **46** | **7067.934** |

All four rows recorded status `succeeded`, original answer and source/reader receipts. Their strict correctness **cannot be scored as a calibration result** because the complete census was never committed and the answer-label embargo was not lifted. The fifth call k=6 was interrupted. The 72 test-arm calls and independent replay **never happened**. Do not multiply the partial answers into a success rate or fill missing calls with fabricated zeros.

The reader job's declared `timeout-minutes: 180` is inconsistent with serially finishing all 40 calibration calls on the observed hardware/profile. The first four completed calls alone consumed 117.8 minutes of inference; one planned calibration case consumes five calls, and another seven cases plus 72 test calls remain. Runtime varies with prompt length, token count and CPU support, so no extrapolation here is a measured GPU or total-work estimate.

## Required remediation before rerunning expensive inference

1. **Compute capacity:** use an actually available, validated accelerator or hardware/precision profile that preserves the reader-control contract; if precision or prompt digest changes, mark a **new experiment profile**, rebaseline all compared arms, and keep the historical Qwen record unchanged. Do not assume that a GitHub-hosted GPU label is provisioned.
2. **Durable interruption-safe execution:** checkpoint each original answer and receipt with exact model, prompt, source-archive and generating-commit identity. Resume only after validating full on-disk bytes, unique question/arm census, prior source identity and fixed prompt/token budgets. Do not silently mix reader versions, reroll a response, read held-out labels early, or treat partial execution as a qualified calibration.
3. **Resource sanity gate:** measure one exact-profile bounded real answer before allocating full 112-call (40+72) budget. If incompatible with timeout, exit *unqualified*, preserve diagnostic artifacts and publish an explicit resource failure. No implicit demotion to a smaller reader or learned adapter.

The project-wide quality gates and independent replay remain mandatory. A formatter or 42/42 unit-test success is software validation, not model efficacy. The entire source population is authored/development only; independent prospective task advantage, semantic citation precision, parametric gains, future retention, recovery and production acceptance remain **unestablished**.
