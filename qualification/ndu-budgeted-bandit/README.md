# Support-aware budgeted bandit: reproducible synthetic diagnostic

Initial execution 2026-10-23 at 15:47 UTC; exact publication-copy execution at 15:54 UTC. This is synthetic mechanism evidence only. It does not close any of the six scientific blockers, prove NDU efficacy, or reproduce the guarantees of the cited algorithms.

## Main findings

- All 384 policy trajectories obeyed the 7168-unit cap and every baseline-reserve prefix condition. These are synthetic cost units, not real inference cost.
- All 32 deficient-support twin pairs had identical training bytes, fits, and action sequences. The empirical router nevertheless changed from beneficial to harmful when only the unobserved reward law changed. This demonstrates nonidentifiability, not hidden evidence in the log.
- Support-LCB fallback made zero unsupported choices, sacrificing upside in the favorable twin. It still became sharply harmful under reward-law drift: support, frozen parameters, and cap compliance do not establish future-window safety.

## Aggregate baseline-paired reward gains

| Scenario | Empirical extrapolation | Support-LCB fallback |
| --- | ---: | ---: |
| full_support | +0.104492 [+0.101599, +0.107386] | +0.106209 [+0.104021, +0.108397] |
| deficient_high | +0.111725 [+0.109937, +0.113513] | +0.092667 [+0.090416, +0.094917] |
| deficient_low | -0.066032 [-0.067669, -0.064396] | +0.092667 [+0.090416, +0.094917] |
| reward_law_shift | -0.205124 [-0.208482, -0.201766] | -0.206520 [-0.208220, -0.204820] |

Intervals are descriptive 95% t intervals across the 32 fixed simulator seeds, unadjusted for multiple comparisons. They are not uncertainty intervals for real-world model quality. All seeds, including failures, are retained in evidence/expected-results.json.

## Costs and conservatism

Baseline always spends 4096 units. Most nonbaseline runs spend 7168; deficient-support support-LCB mean spend is 7136.25. Hence this is a shared-cap comparison, not equal-spend or cost-efficiency evidence. The cap is a greedy feasibility filter and can reject valuable later actions; no globally optimal allocation claim is made. Empirical deficient-support runs selected unobserved cells 24,566 times over 32 seeds in each twin. Support-LCB selected none.

## Custody and verification

- Protocol SHA256: 41408e63a112f293ddedbaef644e852556515168f04d44822d8eb48cbcca0b4c
- Publication runner SHA256: 3e19bc2b18c1704dac57c11756f6db0f60fdf9e587172a7b55cca8b3cb8307f0
- Published compact evidence SHA256: 8398a470d9a2534ea8df11c82201caab7c2c14b25765574be8e7dc7f458ed9a2
- Original protocol/source/test hashes passed verification after the first execution. The publication copy removes one unused future import to follow repository Python guidance. Its fresh run reproduced all per-seed results exactly; only runner hash and harness duration changed. The locally frozen protocol is unchanged.
- Initial 10/10 unit tests passed in 0.042 s. Initial harness wall time was 3.238 s with affinity CPU 1 and child peak RSS 17,504 KiB. The publication copy passed 15/15 tests in 0.044 s and executed in 3.344 s wall time, peak RSS 17,532 KiB, also CPU 1. Neither is measured CPU time or model cost.
- The first test launcher could not find /usr/bin/time; its error is preserved. A stdlib subprocess/resource wrapper then executed the actual tests and experiment.

## Next scientifically necessary inputs

To turn this into a real routing control: provide the frozen callable conditional-generator/action adapters, an independently sourced and preregistered natural cohort, action propensities and real rewards controlled by an independent observer, complete observed inference costs, and future/retention windows with immutable trust roots. The existing natural-image codec reconstruction does not supply those inputs.

Sources, fixed settings, hypotheses and limits are in PROTOCOL.md. No production or existing media-PR source is changed by this standalone diagnostic.

## Independent review
A separate read-only reviewer reran all 10 unit tests on CPU 1 and independently recomputed all 128 seed/scenario rows' summaries, t intervals, spend identities, twin equalities, and source hashes. No blocking leakage, confidence-bound, cap, or aggregation issue was found. The review confirmed the original result SHA256 5949ab9fc518b20472abe3984365c96e0fe8a98c3b92eabf6dae59469291f0d0 before publication packaging.

The frozen pre-run files and hashes establish local execution custody only, not independent external preregistration. The 3.24-second number is single-core harness wall time, not measured CPU time and not model inference cost. The reviewer did not rerun the full experiment.

## Reproduce with Python standard library only

Run from the repository root:

```sh
python3 -m unittest discover -s qualification/ndu-budgeted-bandit -p 'test_*.py' -v
ROOT=qualification/ndu-budgeted-bandit
RUN_DIR=$(mktemp -d)
cp "$ROOT/diagnostic.py" "$ROOT/PROTOCOL.md" "$RUN_DIR/"
python3 "$RUN_DIR/diagnostic.py" > "$RUN_DIR/run.log"
python3 "$ROOT/verify_reproduction.py" "$RUN_DIR/results.json"
```

The checker compares every deterministic field, all source/data/action hashes and all negative outcomes. It ignores only the root harness wall-time value; floating-point values use a 1e-12 numerical tolerance. This is regression reproduction, not statistical validation from an independent natural cohort. The dedicated CI checks the exact submitted head, runs all tests, and reexecutes all seeds using temporary output without rewriting committed evidence. No model downloads, secrets, GPU, or external Python packages are required.

PROTOCOL.md is the unchanged local pre-run specification. Its historical title uses “preregistered local”; that means locally frozen before this run, not a formal or independently timestamped preregistration. No theorem from CLUCB, SPIBB or contextual bandits with knapsacks is claimed for this simpler diagnostic. See its primary-source links for the actual algorithms and assumptions.
