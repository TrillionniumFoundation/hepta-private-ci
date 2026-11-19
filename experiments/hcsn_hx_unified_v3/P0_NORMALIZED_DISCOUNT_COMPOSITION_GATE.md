# HCSN P0 — compose normalized killed-Gaussian first-hit with discount-loss admission

**RESEARCH ONLY / DRAFT / DENY_ALL.**
`all_blockers_closed=false`; `production_activation_allowed=false`.
No production owner, original finance HX, Rust/GPU, training, CI/workflow, or main edits.

## Immutable dependency and why this is needed

- Exact parent: HCSN draft PR #4485 HEAD `766cacb71e98ed88dc79a659fdde24e731c3315e`; branch `dot/hcsn-piecewise-killed-gap-normalization-20261031-r14`.
- #4485 fixed *remote and vanishing Gaussian mode* omissions by standardizing the killed endpoint integral, but was stacked directly on #4478, **not** on sibling PR #4481.
- #4481 had separately proved and checked the stopped discount-loss envelope in the earlier unnormalized code. The normalized two-segment code did not inherit the check.
- This patch composes only that physical admission condition with the normalized implementation: one linear-oracle guard, one piecewise-oracle guard, one regression test and this note. All normalized quadrature, slopes and error/refusal policies are unchanged.

## Mathematical necessary condition, not a new closed-form solution

For a Brownian first hit `tau`, starting strictly above a finite continuous barrier over a finite nonzero horizon `T`, with discount `q>0`, let

```
F = P(tau <= T)
G = E[exp(-q*tau) * 1(tau<=T)]
D = F - G = E[(1-exp(-q*tau)) * 1(tau<=T)].
```

For positive diffusion and a finite continuous two-segment barrier, `F>0`, and `tau>0` on the event, hence:

```
0 < G < F <= 1,       0 < D <= F * (-expm1(-q*T)).
```

Use `expm1` for the upper bound. This is a **necessary physical envelope**; a pair `F,G` may lie inside it and still be wrong. Reject violations; never clamp or label an explicit refusal as a correct probability. Cases with `q=0`, `T=0` or initial contact `x<=b` retain their actual equalities.

## Reproduced negative evidence on unmodified exact parent

The two reference source files were reconstructed byte-for-byte from PR #4485. Their Git blob SHAs were independently checked:

- `moving_boundary_enclosure.py`: `f2f2f864188f6563d0033af998d7cdec7ab95b6d`.
- `piecewise_boundary_oracle.py`: `37c3f53602bbc1b18735a3f1ff6ccd3ae879b33e`.

With `x=1,b=0,mu=0,sigma=.6,T=1.3`:

- Linear `c=0,q=1e-90,dps=65`: accepted `D≈2.96736492055e-67`, despite the necessary upper limit `≈1.86947886216e-91`.
- Linear `q=1e-200`: accepted `F=G`, although true `D>0`.
- Piecewise `c1=-.2,c2=.7,switch=.6,q=1e-90` or `1e-200,dps=60`: accepted `F=G`.
- Piecewise equal-slope, zero-length first or second segment delegates to unguarded linear code and also admitted unresolved `q=1e-200` outputs.

**Unmodified #4485 + new test: eight methods, six failing assertions/subtests, the other methods passing.** This is the requested negative control; the failed checks are not hidden.

## Actually executed local verification

- Linux x86-64; Python 3.13.5; mpmath 1.3.0.
- Reconstructed exact parent source and all three inherited focused test modules; their upstream test blob identities were verified.
- Patched-source + original 22 inherited methods + eight new methods: **30/30 PASS, 0 skipped**; targeted `compileall` PASS.
- Tested patched source Git blobs:
  - linear: `f0a2a11199a8e81a9d79362ec91ec5ccf142331c`
  - normalized piecewise: `8a039d357c3464bc137b822dd0f02abed7589345`
  - regression test: `3eb3fb5f632474bd79f88bb206e9c071c1955671`
- Existing tests include independent time-density first-hit integration, killed-mass reflection, two-slope vs average-slope, 50/80-digit stability and extreme narrow-mode witnesses. All passed after the composition.
- Reproduce in a complete checkout of **this exact branch**:

```sh
python -m unittest -v \
  experiments.hcsn_hx_unified_v3.test_moving_boundary_enclosure \
  experiments.hcsn_hx_unified_v3.test_piecewise_boundary_oracle \
  experiments.hcsn_hx_unified_v3.test_piecewise_narrow_mode \
  experiments.hcsn_hx_unified_v3.test_normalized_discount_loss_integration
python -m compileall -q experiments/hcsn_hx_unified_v3
```

Testing used a relevant-module reconstruction, **not** an entire Git checkout and **not** GitHub Actions. Full upstream integration, adversarial all-domain correctness and cross-platform equivalence remain unverified.

## Remaining P0–P5 admission blockers

- **P0 OPEN:** globally self-consistent coupled financial HX equity/obstacle/fixed point, rigorous directed-rounding and quadrature-tail certificate, full gradient/FP32/FP16/GPU boundary fidelity. These new refusals narrow accepted input domains; they are not numerical proofs.
- **P1 OPEN:** preregistered Call/Risk/Margin ablations beating matched-slope, matched-information ordinary gates; previous negative mechanism results remain binding.
- **P2 OPEN:** real long-memory, overwrite, MQAR and repeated physical event/restore superiority beyond small CTMC mathematical checks.
- **P3 OPEN:** strong paired text/image/audio/video encoder and OOD quality evidence.
- **P4 OPEN:** native Rust/GPU 64/256/1024/4096 Cell full-cost CPU/RSS/VRAM/p95/p99/joules/recovery evidence.
- **P5 OPEN:** matched-token, matched-active-parameter, equal-quality and full-cost Transformer/SSM superiority before backbone scaling.

**Keep this PR Draft and DENY_ALL. No admission, production activation or successful mechanism/superiority claim.**
