# HCSN P0: fail-closed physical identity for real debt-error panels (2026-10-31)

**RESEARCH ONLY / DENY_ALL / NO_GO.** This is a narrowly scoped provenance-correctness repair stacked on [Draft #4524](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4524) exact HEAD `0784c042b6144ec0709cf590775164a099508716`; observed protected main `732e934ba496d90fbe042b8d41d479ef901643e5`. No financial PDE mathematical algorithm, old evidence, training, Rust native owner, CI, admission, or deployment path is changed.

## Previously missed invalid cross-regime reuse

The parent bridge `check_idealized_equity_boundary(p, panel)` checks `p.sale_fraction == panel.sale_fraction`, a fixed barrier, and row count, **but not** the other HX financial inputs. For example, retain an error panel generated with `volatility=0.25`, change the downstream HX equity parameters to `volatility=0.251` while keeping `sale_fraction=0.2`, and the parent bridge can call the equity continuation gate with a debt error bound from the wrong physical stochastic process. This is a scientifically unsound use of measured external errors. The same issue arises with changes in rate, maturity, payout, shock intensity, recovery, coupon, principal, or tax shield.

An isolated **negative reproducer** reconstructed the parent bridge minus the new guard: a 33-node synthetic receipt tagged for `volatility=0.25` was accepted with `volatility=0.251` and passed to a stubbed equity gate. The patched bridge refused with `UnresolvedDebtAudit: stale/unbound physical HX debt-error panel` **before** calling the gate. Neither result is a real financial STOP certificate.

## Narrow implementation

1. New `hx_debt_panel_identity.py` computes a deterministic SHA256 identity over **all ten** HX physical parameters plus the financial barrier and finite numerical mesh (`nodes`, `time_steps`, `log_upper`). Each finite binary64 is represented using `float.hex()` to avoid decimal reinterpretation; booleans, nonfinites, unsupported work, and missing input fields REFUSE. This is a **checksum/identity**, *not* a cryptographic attestation or proof of interval accuracy.
2. The all-node auditor stamps `physical_parameters_sha256` into `FullDebtGridBound` when the actual numeric panel is generated. The existing `canonical_panel()` includes the new field, producing **new v2-style canonical payload digests**. Historical #4524 v1 node-panel digests remain untouched in that PR; do not equate old/new JSON SHA256 values.
3. The downstream conditional bridge now **requires** the exact stamp match against the HX model and mesh received by the equity solver. Unsealed/legacy objects refuse instead of silently assuming they describe the same PDE.
4. Additive tests explicitly cover the ten field changes, four discretization changes, forged/empty digests, invalid inputs, and a valid *mocked conditional* receipt that remains `production_activation=false`.

## Execution and provenance limits

- Local Python **3.13.5**, Linux CPU: **6/6** pure helper unittest methods passed using the exact newly uploaded helper bytes (Git blob `917dd99a25b94669886d335b076c953962887ca8`; local SHA256 `e9f17b67d8984523474a0e853fe42e457c79142c577ba40c2a0a61afa0f4622f`).
- The copied bridge guard and dataclass schema were exercised with **3/3 additional isolated tests** (valid conditional receipt, ten cross-regime refusals, mesh/checksum refusals). All nine local test methods passed, zero skipped. **This is an isolated schema/guard fixture, not a byte-identical complete upstream repository or a real PDE/financial obstacle execution.** The unmodified original modules on #4524 previously reported 11 focused local tests, but this increment has NOT independently rerun those tests in a full checkout.
- The GitHub connector read back exact source/blob hashes after upload. Pending CI is not presented as success.
- Reproduce this incremental unit test in a checkout of the proposed branch with:
  `python -m unittest -v experiments.hcsn_hx_unified_v3.test_hx_debt_panel_identity experiments.hcsn_hx_unified_v3.test_hx_measured_debt_conditional_bridge`.
  The first is quick synthetic input-identity regression; the second performs actual selected-grid PDE integration, including the original negative real-error behavior.

## Unclosed P0–P5

**P0 OPEN:** no complete finite-time/corner + continuum spatial error envelope, coupled endogenous HX free boundary, global obstacle classification, certified interval low precision, or financial implicit gradients. The narrow physical-input binding is a necessary evidence-contract correction, not a mathematical closure.

**P1 OPEN:** no independently preregistered same-total-resource causal Call/Risk/Margin advantage. **P2 OPEN:** real FIRE OOD/Overwrite/host crash-recovery deficiencies. **P3 OPEN:** true four-modal real encoder/OOD. **P4 OPEN:** native Rust/GPU 64–4096 Cell CPU/RSS/p95/p99/Joules and crash faults. **P5 BLOCKED:** genuine equal-budget scaling after the prerequisite scientific gates.

All negative findings from #4499, #4517, #4521, #4524, #4525 remain visible. Do not merge research to production or change admission to GO.
