# P0 HX near-barrier log-ratio numerical admission gate

**DRAFT / research only / DENY_ALL**  
`all_blockers_closed=false`; `production_activation_allowed=false`.

## Immutable context and narrow scope

- Parent draft [#4465](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4465), exact HEAD `6dab0fd81a49a8f89428d49566ba1aba0a2a7cd1`.
- Target: `experiments/hcsn_hx_unified_v3/hx.py`, starting blob `f27ece333a436048e7ce366fc43f5f893324d319`.
- Changed only the *financial* first-passage log-ratio helper, the importing regression, and this evidence note.
- No training, HCSN Cell execution, Rust/GPU, CI config, model authorization, or production deployment changes.

## Reproduced first-passage false result

For default `HX()`, `asset_boundary=0.1`, `asset=math.nextafter(0.1,math.inf)`, `tau=1e-30`:

- Existing `math.log(asset/asset_boundary)` uses the rounded quotient, treating the actual one-ULP separation as approximately `2.220446049250313e-16`.
- Independent 100+ decimal digit `mpmath` evaluation from the **exact finite binary64 asset and barrier** gives log-ratio approximately `1.3877787807814457e-16`.
- Existing default probability `F` approximately `0.374444785`; independent first-passage formula `0.578818389`. This is an approximately 0.20437 absolute probability error.
- A branch-local source change uses `math.log1p((asset-asset_boundary)/asset_boundary)` *only* for positive assets within `1e-8` quotient separation of their barrier. The subtraction is exact in that range by Sterbenz's lemma; `log1p` preserves the small logarithm.
- Outside the narrow separation window the old `math.log(asset/asset_boundary)` remains unchanged, including its overflow fallback. This is an **engineering precision improvement**, not a certified full-domain error bound.

## Independent executed checks vs unexecuted checks

The relevant functions `HX`, `_log_asset_ratio`, `_first_passage_factors`, `default_probability`, and `discounted_default_factor` were **locally reconstructed from the inspected GitHub source**. The complete `hx.py` and full repository were **not checked out locally**.

- Original corresponding function + final regression: **1,218 failing unittest subtest/assertions** and nonzero exit (negative witness, not skipped).
- Narrow patched reconstruction + regression: **7/7 unittest methods PASS**, zero skipped; `python -m compileall` PASS.
- One-ULP distance tested at 12 admitted first-passage configurations, plus extreme-scale helper cases, ordinary bit-exact quotient controls, endpoints, and overflow fallback.
- Seeded `Random(20261031)` 1,200 one-ULP binary64 log-ratio cases across exponents -980 through +979 against 100+ dps mpmath. Worst old relative log error **0.9993710215981496**; worst patched relative log error **2.219747742946587e-16**.
- Two specific near-boundary cases still correctly raise `ArithmeticError` under the inherited joint F/G ordering guard; these refusals are **not** counted as numerical solution admissions.
- Local 7-method suite wall time including interpreter startup: ~1.36 seconds, peak process RSS ~109,068 KiB; these are **not Cell/native throughput, energy or tail latency measurements**.
- Remote regression Git blob **`155b4622f76af85409f7f465c0bae371c2dae41b` matches byte-for-byte the locally executed test**. Remote patched source Git blob **`33fa0c170ce311d58383f6a7f0c70e7a51f48cfa`** was read back, but the *complete* new source was **not run** in this container.

## Reproduction on an exact checkout of this branch

```sh
python -m unittest -v experiments.hcsn_hx_unified_v3.test_hx_near_barrier_log1p
python -m unittest -v experiments.hcsn_hx_unified_v3.test_oracles
python -m unittest -v experiments.hcsn_hx_unified_v3.test_hx_joint_fpt_contract
python -m compileall -q experiments/hcsn_hx_unified_v3
```

The second and third commands **have not been run in this work session**, and the first was run on a reconstructed selected-function module, not a complete source-exact checkout. A future complete exact checkout should re-run all of them before stack integration.

## Remaining vetoes

- P0: rigorous coupled HX obstacle/free-boundary/QVI; independently certified first-passage quadrature and tails; low-precision/degenerate-limits and bounded gradient assessment; exact full-checkout regressions.
- P1: same-information, same-parameters and same-budget causal Call/Risk/Margin ablations with robust positive incremental value.
- P2: physically repeated event and long-horizon Selective Copy, MQAR, overwrite, irregular-time and multi-regeneration quality.
- P3: truly paired text/image/audio/video task and noise/OOD independent verification.
- P4: native Rust/GPU 64/256/1024/4096 Cell throughput, p95/p99, CPU/GPU, memory, joules and crash/recovery evidence.
- P5: quality- and compute-matched hybrid backbone superiority over tuned Transformer/SSM baselines.

**Do not merge to production or lift `DENY_ALL` based on this research-only numerical gate.**
