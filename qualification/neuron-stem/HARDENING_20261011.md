# Four-gate input and statistical hardening

This continuation rebases the previously delivered seven-file residual patch from
`94c49f409e63e17103da0a463d174dea27950dfb` onto inspected parent
`e2920fec4387b837bd557909df70dd34cecae5fb`. The latter's public-corpus schedule,
all 36 scale settings and 72 actual two-arm processes remain intact. Historical
import branches, V1 records, original reports and production owners are unchanged.
There is still one canonical review entrypoint, `four_gate_review.py`.

## Changes

- Reject training inputs or source groups used as best-fixed-depth validation,
  repeated validation inputs disguised as new cases, and empty observer identities.
  A newly computed outer digest cannot excuse leakage.
- Keep the existing source-cluster bootstrap, but enclose observed V2 selective
  ratios in a conservative finite-sample guard. An all-zero empirical error no
  longer implies a zero upper risk bound. The bound is conditional on fixed
  pre-outcome cluster sizes and independent clusters; these assumptions are not
  authenticated, and no arbitrary distribution-shift coverage is asserted.
  Reject-all risk remains undefined. Source floors and multiplicity are unchanged.
- Use an explicit question/options-preserving token adapter. Both joint and reuse
  arms receive the same retained state-token budget, reserved against the largest
  admitted condition. Insufficient space rejects rather than dropping conditions.
  Preparation cost is included in load, and pipeline identity plus per-request
  token audit records bind the actual condition and retained source tokens.
- Retain every original scale job and add the input adapter/test to real-model CI
  path triggers. This change requires new physical executions; earlier captures
  cannot be re-labelled as outputs of the new input profile.

## Validation and limits

The locally reconstructed exact qualification subtree, after conflict-aware
application, executed 159 model-free regressions and 10 real CPU tensor tests
without skips. This is not a full repository/Rust run or a final-head hosted pass.
The old patch's appended convergence note is consolidated here; the existing
convergence document is retained unchanged rather than rewritten.

Run the existing workflow and these commands on the final source and prospective
merge separately:

```sh
PYTHONPATH=qualification/neuron-stem python3 -m unittest discover \
  -s qualification/neuron-stem -p 'test_*.py' -v
PYTHONPATH=qualification/neuron-stem python3 -m unittest capture_cpu_checks -v
```

Physical model smoke uses untrained Heads and has no authentic current no-change
arm. Public labelled replay is historical, not independent future observation.
Neither a test pass nor lower measured Encoder work proves a three-arm quality,
learning, reasoning or NDU lifecycle benefit. Native final-use, CAS, checkpoint
recovery and target-host production qualification remain with their existing
owners. Keep the PR Draft and `production_promotion_permitted=false`.
