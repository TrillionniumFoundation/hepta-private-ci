# E12+ Cell-local handoff: finite nonlinear stochastic FBSDE (research only)

**Scope:** additive child of [E12 #2143](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2143) at original SHA `47fb9fac2e4275df53c2cfa2f50564bf48895ae7`. Research / `DENY_ALL` / no production caller / no selected weights / no main merge. This does not claim a new FBSDE theorem, neural reasoning, modality generation, or offline/online net utility.

## Question and mathematical acceptance

The original E12 paper-size test computes the nonlinear finite-tree coupled model with `phi(x)=x/(1+x*x)`, nonzero symmetric martingale increments, depth `1..3`, `a in {0,1/3}`, and a registered global contraction `q=a*T*(g+beta*T)<3/4`. The ordinary full-tree fixed point satisfies the rational global approximation guarantee `||Y-Y*||∞ <= ||Y-F(Y)||∞/(1-q)`.

The new boundary *producer* breaks a frozen original `Solve` into separate one-step `CellSegment` records (one per public-history interior node) and terminal `TerminalCell` records. Each Cell repeats only its own start, its two outgoing boundaries, its martingale `Z`, the external scope digest, and its public path. No Cell owns authority or model weights. The *reviewer* does not trust the producer's scalar residual or per-Cell success declaration: it checks every node, every edge and leaf, reconstructs a complete backward pass from externally specified terminal values, and calculates the global rational residual anew. A separate replay of the original E12 independent auditor checks the source numerical certificate.

For each interior node `v`, admitted formulas are:

```text
X_vL = X_v + a*h*phi(Y_v) - sigma*s
X_vR = X_v + a*h*phi(Y_v) + sigma*s
(1+lambda*h)*Y_v ≈ (Y_vL+Y_vR)/2 + beta*h*phi(X_v)
Z_v = (Y_vR-Y_vL)/(2*s)
```

Here `≈` is a measured local residual because the original globally certified E12 solver returns a bounded approximate fixed point, not an exact one. The children must agree **exactly** on both `X` and `Y` with each parent's declared outgoing boundary. Terminal leaves must satisfy `Y=g*phi(X)` exactly. The independent backward map recomputes `Y=F(Y)` on the entire tree, then applies the contraction-error enclosure. A small terminal residual or isolated local residual is not sufficient. In particular, a one-step Cell can have *zero* forward, backward and `Z` error with arbitrary child continuation guesses, yet fail the cross-Cell equality or true terminal condition.

## Source and execution isolation

- `e12_cell_boundary.py`: typed, bounded internal/terminal Cell records; exact checked public-prefix identities, explicit conditional martingale `Z`, full replayed backward map and finite global error enclosure.
- `e12_cell_boundary_study.py`: reads one pre-sealed original E12 six-law source, produces a **create-only** Cell bundle; a subsequent separate CLI process reopens the original source and sealed bundle after SHA verification and emits a distinct, create-only audit. JSON rejects duplicate keys and nonfinite inputs through the original E12 source loader.
- `test_e12_cell_boundary*.py`: 22 source-driven/adversarial tests, including six actual original finite nonlinear stochastic laws, invalid numeric strings, missing/duplicated Cell interfaces, incorrect `Z`, changed leaf, forged bound, forged scope and authority, sealed-file overwrite.
- `hepta-e12-cell-boundary.yml`: read-only Actions checkout at PR source SHA and synthetic merge; reruns inherited E12 tests normally and under `python -O`, then original E12 execution, separate Cell bundle generation, and independent Cell reviewer processes. Store exact source and failure logs with immutable output digests.

The source digest and Cell scope digest are **not** issuer signatures or trusted runtime authorization. Timers in inherited E12 source are not independently hardware-attested, and repeated local simulations are not independent human task results. The model has 1, 3, or 7 internal Cells, **not** measured scaling to 64/1024/4096 physical Neuron Cells. No general continuous-time FBSDE, learned coefficients, multimodal or reasoning-task gain is claimed.

## Execute and gate

```sh
ROOT=qualification/shared-stem-system2-architecture
export PYTHONPATH="$ROOT"
python -m unittest discover -s "$ROOT" -p 'test_e12_*.py' -v
python -O -m unittest discover -s "$ROOT" -p 'test_e12_*.py' -v
mkdir -p /tmp/hepta-e12-local-global
python "$ROOT/e12_study.py" execute --output /tmp/hepta-e12-local-global/source.json
SRC_SHA=$(sha256sum /tmp/hepta-e12-local-global/source.json | cut -d ' ' -f1)
python "$ROOT/e12_cell_boundary_study.py" produce \
  --source /tmp/hepta-e12-local-global/source.json --source-sha256 "$SRC_SHA" \
  --output /tmp/hepta-e12-local-global/segments.json
SEG_SHA=$(sha256sum /tmp/hepta-e12-local-global/segments.json | cut -d ' ' -f1)
python "$ROOT/e12_cell_boundary_study.py" review \
  --source /tmp/hepta-e12-local-global/source.json --source-sha256 "$SRC_SHA" \
  --candidate /tmp/hepta-e12-local-global/segments.json --candidate-sha256 "$SEG_SHA" \
  --output /tmp/hepta-e12-local-global/review.json
```

**Next qualification condition:** only if the exact-head hosted audit and the independent source/merge checks complete, advance to real Reader sufficiency and equal-total-cost prospective utility. A finite-tree mathematical handoff cannot waive the documented E13/E14 authentic-task `NO_GO`, globally blocking CI, independent original source evidence, or production selection requirements.
