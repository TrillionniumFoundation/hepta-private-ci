# HCSN P0: convergence of independent HX equity and renewal endpoint guards

**DRAFT / research only / DENY_ALL / all_blockers_closed=false / production_activation_allowed=false**

## Immutable scope

- Current main inspected: `732e934ba496d90fbe042b8d41d479ef901643e5` (not modified).
- Exact parent: PR #4465 HEAD `6dab0fd81a49a8f89428d49566ba1aba0a2a7cd1`.
- Preserve parent HX bond small-q no-hit annuity correction and fail-closed nonzero hit-mass gate.
- Transplant **only** the `equity_closed` function from sibling #4460 HEAD `dac62e04795b4f77e0f7c9089d5fa1462ecf86a3`: finite-operand overflow-resistant `_log_asset_ratio` and explicit finite result admission.
- Transplant **only** the `regenerative_boundary` function from sibling #4463 HEAD `d0000bb1f354a6c01b11ac3a5b6dfb9b92a19623`: reject `t==1` saturation of the binary64 Lambert-W interior root.
- Add one composition-specific regression file; all other source paths and earlier research results unchanged.

**Verified remote Git blob identities:**

| Path | Blob |
| --- | --- |
| `experiments/hcsn_hx_unified_v3/hx.py` | `ed59840d5d78459e4c2a8f67a3997611ab4e0d9b` |
| `experiments/hcsn_hx_unified_v3/stopping.py` | `7fedb50b864160b158bb9daf242c22ed2509a2a6` |
| `experiments/hcsn_hx_unified_v3/test_p0_equity_renewal_composition.py` | `484dc7ca65855ad2b2fbf8825d283c72b318642d` |

## Actual bounded numeric execution

Python 3.13.5 / SciPy on an **independently reconstructed relevant-function subset**, not a complete source-exact checkout of this GitHub branch:

1. Unmodified parent expressions under new composition test: **6 methods executed, 11 failed subtests/assertions**. Extreme positive finite operand ratios produced invalid equity, and primary Lambert-W roots at `h=37,40,50,100,710` incorrectly admitted saturated endpoints.
2. Composed narrow equity and renewal guards: **6/6 methods PASS, 0 SKIP**. Covered three overflowing operand ratios, three ordinary equity pairs, one inherited small-q bond case, five endpoint roots, downstream value/obstacle/QVI refusals, and nine regular interior roots.
3. A test in the sibling #4463 assumed `kappa==1.0` and `one_shot_boundary==1.0` bit-for-bit for `Stop(0,1,.5,0,-h,0)`. Current `kappa` arithmetic returns `1.0000000000000002`; the combined test correctly uses a declared `5e-16` absolute resolution check. This fixes the test assumption, **not** the math semantics.
4. Exact newly authored test file ran locally and remote Git blob matches it byte-for-byte. **The entire newly composed remote `hx.py`/`stopping.py` files have not been checked out or executed as complete byte-exact modules.** GitHub Actions/CI are not claimed as passing.

## Mandatory source-checkout commands before research-merge consideration

```sh
python -m unittest -v experiments.hcsn_hx_unified_v3.test_p0_equity_renewal_composition
python -m unittest -v experiments.hcsn_hx_unified_v3.test_hx_bond_small_q_nonunity
python -m unittest -v experiments.hcsn_hx_unified_v3.test_hx_log_ratio_overflow
python -m unittest -v experiments.hcsn_hx_unified_v3.test_oracles
python -m unittest -v experiments.hcsn_hx_unified_v3.test_renewal_upper_endpoint_gate
```

## Remaining scientific/engineering closure gates

- **P0:** Full self-consistent financial obstacle/associated bond fixed point, all-domain curvature/QVI, certified interval/tail and native low-precision boundary-gradient evidence are **NOT CLOSED**. Rejecting bad floats is necessary, not a mathematical certification.
- **P1:** Prior 0/4 mechanism gains remain negative. No new preregistered, training-seed independent same-information/local-slope/active-param/full-cost Call/Risk/Margin causal win.
- **P2:** Selective Copy/MQAR long memory, genuinely physical repeated-event learning and recovery equivalence not qualified.
- **P3:** Real, independently sourced four-modal encoders with pairing/OOD/control experiments not qualified.
- **P4:** No new Rust/GPU native neural kernel, 64/256/1024/4096 Cell actual hardware p99/joules/crash-recovery qualification.
- **P5:** No quality-conditioned equal-resource Encoder+HCSN Head superiority over tuned Transformer/SSM.

No merge to main, production authority change, model promotion, CI policy change, or claim of full P0-P5 success.
