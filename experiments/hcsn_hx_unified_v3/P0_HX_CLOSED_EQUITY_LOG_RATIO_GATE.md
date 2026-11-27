# HCSN P0: close the remaining HX closed-equity overflow-ratio NaN

**DRAFT / RESEARCH ONLY / DENY_ALL / all_blockers_closed=false / production_activation_allowed=false.**

## Source boundary
Stacked on Draft PR #4459 HEAD `78519b7fe1d85000bb13a739fb70f45bba70e18c`, itself stacked on #4457. Inspected inherited `hx.py` blob `f7443b1e5c7e769f331999bd8666516d557237c9`. Changes only offline `experiments/hcsn_hx_unified_v3/hx.py`, adds an isolated four-method regression, and this gate note. No production finance, runtime, Rust/GPU, model learning, CI or authority changes.

## Confirmed old failure

Draft #4457 fixed the quotient-overflow log in bond and first-passage functions but `equity_closed` still used `math.log(asset/boundary)`. For positive finite pairs (1e308,1e-308), (1e308,1e-100), and (1e200,1e-200), division overflows even though the real log ratio is finite. Under the local inspected formula, the spurious infinite log then feeds `_A` normal tails and returns **NaN equity** (not a true financial result). This also taints `mechanism_channels`.

## Bounded repair

Reuse the inherited `_log_asset_ratio` for closed equity, preserving the old quotient log exactly on finite quotients, and explicitly refuse a nonfinite final equity with `ArithmeticError`. Do **not** clip negative financial equity: the existing `sale_fraction=.2` global-obstacle failure is kept. Do not change `equity_resolvent`; its own large-log Green integration, global obstacle and tail error remain separately unqualified.

## Executed and not executed

- **3/3** local Python 3.13.5 focused unittest methods PASS with independently transcribed inspected HX closed-equity formulae, 0 skips. Under the original ratio each extreme pair gives NaN; after stable v every pair yields a finite value equal to the leading asset asymptote within relative 1e-12. Six ordinary ratios retain bit-identical old/new results. This is a focused *formula extraction*, not a source-exact full checkout.
- Committed four-method integration regression includes the three extreme pairs through `mechanism_channels`, normal financial resolvent, intentionally negative equity and forced NaN output denial. **Not yet executed against exact repository code / full CI.** No production admission or general financial numerical stability claim.

From the exact research checkout:

```sh
python -m unittest -v experiments.hcsn_hx_unified_v3.test_hx_equity_log_ratio
python -m unittest -v experiments.hcsn_hx_unified_v3.test_hx_joint_fpt_contract
python -m unittest -v experiments.hcsn_hx_unified_v3.test_oracles
```

## Still open

Global coupled financial equity obstacle, interval-certified first-passage and resolvent tail, boundary/gradient and full legal domains, true native low-precision, mechanism causal benefits (P1), long event-memory workloads (P2), real paired multimodal (P3), Rust/GPU 64–4096 Cell energy/recovery (P4), equal-budget backbone benefit (P5): **all OPEN**.
