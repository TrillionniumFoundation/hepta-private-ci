# Research policy interface and frozen candidate identities

This policy learns a signed exponential-moment **difference from stopping**.
It does not output correctness probabilities and must not inherit a probability
calibration certificate from the existing teacher or native admission head.
Its prospective qualification is determined by `PROTOCOL.json` and the eventual
actual-output result, not by this interface document.

## Public input and causal owner contract

Python entry points are `model.load(checkpoint)` and
`Policy.predict(public, remaining)` / `Policy.choose(public, remaining)`.
The caller verifies the selected checkpoint SHA against the frozen protocol
before loading it. The input is a finite float32 matrix of shape `[B, 763]` from
the existing `ExactFeatureCache`: current latent state, current decoded draft
and public observation-derived features, followed by remaining budget divided
by two. It contains no target, private score or future decoder draw.

`remaining` is exactly 1 or 2. The selected head is specific to that horizon.
The returned matrix has shape `[B, 5]`, in this exact order:

| Index | Action | Value |
|---|---|---|
| 0 | stop | exact zero |
| 1 | refine_semantic | predicted signed difference; positive infinity at H1 |
| 2 | refine_image | predicted signed difference |
| 3 | refine_text | predicted signed difference |
| 4 | couple | predicted signed difference |

The owner chooses `argmin` in this order, so exact ties use the first index.
H1 semantic refinement is masked because it preserves the actual draft and
incurs the action fee. It remains feasible at H2, where its changed latent
state may influence the later output. Once the owner commits and fsyncs the
choice, it draws the future innovation and executes the transition. The
selected terminal output remains the actual generated media. Private
counterfactuals are diagnostic owner work after actual choices complete.

## Parameters and possible native split

Each horizon is one fixed normalization, one hidden layer, and one linear
output:

```
z = tanh(W1 @ ((public - mean) / scale) + b1)
delta_nonstop = W2 @ z + b2
delta_stop = 0
```

`mean` and `scale` have length 763, `W1` has shape `[width, 763]`, `b1` has
length `width`, `W2` has shape `[4, width]`, and `b2` has length four. All scales
are positive. The full float32 execution is the measured research baseline.
A native implementation could place the frozen feature encoder and first
layer before a bounded final-head port, passing only `z` and the horizon.
That split still requires its own input identity, float/Q24 action-parity and
actual execution qualification. It is not supplied or certified by the Python
training result. Correctness admission must remain a distinct mechanism.

## Selected artifacts

The selection rule was fixed before reading any new-source outcome. The two
registered capacities were 32 and 128; there was no additional search after
selection. The development outcome selected the following research panel:

| Generator seed | Width | Development admitted | Checkpoint SHA-256 |
|---|---:|---|---|
| 17 | 128 | no | `936920a009c548bb9d036bf182bab1cb96e07e38d583d08de228c2d37d50c024` |
| 29 | 32 | no | `6d969e0622b401ea25cdd8885691db594e608badf322c109dd22552c6893fbc3` |
| 43 | 32 | yes | `cbe1e4517afb95354cefcc870deab082607f4937ca82abc20da426abd35bdd61` |

Paths are recorded in the frozen protocol under `candidates`; in this run
they are `ndu-runs/action-value-development-001/seed-{seed}-width-{width}.pt`
under the shared workspace root. Each artifact contains both horizon heads,
their fixed normalization, configuration and state dictionaries. The protocol
SHA is `1f741901ab3cd737e9a03463a590cb3662b6544c17a22df7b0357b409c950e5f`.

The two unadmitted members are explicitly research candidates. A useful
selected action, a better aggregate outcome, a calibrated conditional value
estimate and a cheaper qualified replacement are separate claims. The actual
confirmation must report each without conflating them.
