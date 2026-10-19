# MemoryCell: incomplete real Qwen calibration and BF16 host forensics

**Date:** 2026-10-12. **Status:** research diagnosis only; not a successful calibrated baseline.

## Immutable evidence

- Aborted calibration: [Actions 38111452963](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38111452963), artifact `11696974258`, generating source `02c12b4aff0d589d10e5ed25d22b05d794ca96a0`.
- Partial ZIP SHA-256: `129351221d56c9668c57e33f8dec79a6443c0252675752085538375b12ca25a8`; partial journal SHA-256: `c644cd7ef62c06a2489ab9d9a67c0933ad489a2a8626de73000d27e45df9db71`.
- Original successful reader: [Actions 38063870516](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38063870516), artifact `11674741321`, generating source `59f9eadd5cc919359079e04442f7343838a60057`, ZIP SHA-256 `831ce9658bafcbaf04f4a15879982e58317322f7cd5137724498d7d20df7bb98`.
- The two archives pass the *external ZIP digest* and full inner `SHA256SUMS` checks: 25 and 21 files respectively. Both use Qwen2.5-3B-Instruct revision `82f42baa094a9600e39ccd80d34058aeeb3abbc1` and reader inventory SHA `f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225`.
- The original frozen test-plan SHA is `9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897`; only calibration scope `controlled_4b61ce33` had attempted model calls.

## Original saved model outputs, not a newly completed evaluation

| Attempt | Input tokens | Generated tokens | Model seconds | Task correct? | Annotated supporting source present? |
| --- | ---: | ---: | ---: | --- | --- |
| k1 | 504 | 7 | 923.308 | No | Yes |
| k2 | 787 | 6 | 1457.513 | No | Yes |
| k3 | 1,076 | 14 | 2045.598 | No | Yes |
| k4 | 1,370 | 13 | 2641.516 | No | Yes |

Four generations returned and were fsynced, but the expected answer `site_463f2998` is absent from each original raw answer. **Only 4/40 planned calibration calls were observed, 36 were never run**, and all four completed outputs are wrong. The correct annotated source was selected for all four; this does *not* mean a human adjudicated the context sufficient. No top-k winner or Qwen/MemoryCell task improvement is established.

The four calls consumed **7,067.934 actual reader seconds**. Historical Qwen hybrid controls with similar input lengths (eight 1,316–1,388-token prompts) had median 15.418 seconds. The cancelled run's 1,370-token k4 call took **171.32×** as long. These are a descriptive *cross-run* comparison on different questions and CPU hosts, not a controlled estimate of causal hardware speedup.

## Separate, verified hardware rejection

[Actions 38200169497](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38200169497) passed its source-format prerequisite but failed the actual host gate before model download. The observed host was **AMD EPYC 7763**, four logical CPUs, with no shared `avx512_bf16`/`amx_bf16` flags. The gate correctly recorded `host_eligible=false`, `full_inference_latency_qualified=false`, zero new model calls and exit code 3. Merely choosing the Ubuntu 22.04 runner label does not guarantee accelerated BF16.

## Reproduction

Download the exact existing Actions artifact ZIPs, without the model weights:

```sh
gh api repos/TrillionniumFoundation/hepta-private-ci/actions/artifacts/11696974258/zip > partial.zip
gh api repos/TrillionniumFoundation/hepta-private-ci/actions/artifacts/11674741321/zip > historical.zip
python3 codex-rs/hepta-intelligence-eval/repro/historical_qwen_partial_receipt.py partial.zip historical.zip --output receipt.json
HEPTA_PARTIAL_QWEN_ZIP=partial.zip HEPTA_HISTORICAL_QWEN_ZIP=historical.zip \
  python3 -m unittest discover -s codex-rs/hepta-intelligence-eval/repro -p 'test_historical_qwen_partial_receipt.py' -v
```

The replay tool checks complete outer/inner archive pins, source commits, calibration-only scope, model/profile consistency, selected original source excerpts, citation-answer consistency and all four original token/time counts. It rejects changed archive bytes and wrong reference model evidence. Its receipt is committed at `scripts/memory_cell/data/historical-qwen-partial-calibration-20261012.json`.

## Decision gate

Do **not** score this four-answer subset as a completed 8×5 calibration, tune k on it, or borrow later results from a different generating SHA. The latest source has a 180-second per-call fail-fast and a BF16 ISA prerequisite; retain both, without silent FP32/quantization/model substitutions. A usable run requires an actually verified BF16-accelerated host or other separately authorized, protocol-matched compute; sharding by itself does not fix a host without BF16 acceleration.

After an eligible host finishes **40 real calibration + 72 matched nine-arm answers**, independently replay raw answers, program probes, source/citation chains and costs. There are no independent future-family observations, semantic 99% evidence, parameter-memory benefits, production cutover or rollback proof from this retrospective diagnosis.
