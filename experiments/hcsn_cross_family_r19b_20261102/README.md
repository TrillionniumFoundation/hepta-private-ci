# R19b: conditional public-stream learning with a generative forecast calibrator

The preceding R19 calibration failed and remains unchanged. This is a separate
candidate with fresh namespaces and fixed 8,192 independent calibration
generators per trained family. Its original 10% error cap, simultaneous 48 risk
bounds and 20 confirmation bounds are unchanged; no old calibration worlds are
pooled into the new test.

Complete PUBLIC streams alone provide masked-learning labels. Each source world
produces one masked pre-READ view and one view for each actual masked PUBLIC
token acquired at its original position. Final-query supervision is computed
from the last publicly visible source WRITE via the observed raw alias mapping.
Each world has equal total objective weight. No owner target, latent parameter
or family label is passed to fitting.

For each of four fixed beta values, two-logit class priors minimize conditional
proper log loss, including every actual-token READ view. Three fixed optimizer
starts are retained. A separate PUBLIC conditional dataset chooses the primary
beta. The strong static reference can choose any of all 12 (class,beta) pairs on
the identical objective and data, so it is not tied to a weaker primary choice.

Calibration is generative, not a confidence-only output adjustment. For each
class and repeated/distinct overwrite-key condition, sum the 4,096 complete
six-value sequence masses to K, normalize to S=L/K, then set
`L_beta = K*S**beta/sum(S**beta)`. This preserves the key marginal and legitimate
zero key mass. Full completion-by-class posterior conditioning, actual READ and
guarded READ expected payoff remain exact for the fitted finite model. The
finite six-event model is not promoted to a general continuous process.

Source publication precedes all formal fitting. Fitted weights and normalized
sequence tables are published before fresh risk calibration. Selected guards and
thresholds are published before any five-family confirmation. The coherent
switching-rotor and pair-renewal worlds remain outside training/calibration and
can fail the unchanged per-family gates. Safe refusal does not satisfy the
minimum 32 genuinely fractional answers per family.

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m experiments.hcsn_cross_family_r19b_20261102.campaign fit
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m experiments.hcsn_cross_family_r19b_20261102.campaign calibrate
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m experiments.hcsn_cross_family_r19b_20261102.campaign confirm
```

Each stage requires verified upstream publication receipts; all writes are
create-only and all candidate/failed-attempt costs remain recorded. Both models
are ordinary full-prefix symbolic references. This establishes no analytical
HCSN D-B, learned semantic/real AV binding, dynamic timing, GPU/energy or production
ownership result.
