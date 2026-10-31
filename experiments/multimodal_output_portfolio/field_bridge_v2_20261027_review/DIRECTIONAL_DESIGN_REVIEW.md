# Scientific review of the conditional directional field

This is a prospective review of the isolated H12 repair. It does not alter the
frozen H7 bank, examine new holdout outcomes, or upgrade an unsuccessful gate.

## Field and derivative conventions

The seven existing coordinates are augmented with the next minibatch's
clipped-gradient RMS, its cosine with carried momentum, and three probe-loss
directional derivatives. These features include information about the current
minibatch as well as parameters and optimizer state. The appropriate name is
a **conditional optimizer/batch field**. A successful experiment would not
prove that the original H7 representation is sufficient.

Let `g` be the exact clipped gradient produced by the existing update objective
on the next scheduled minibatch. Its supervised weights are image BCE plus
0.5 times text CE plus 0.15 times digit CE. The unchanged teacher anchor and
the existing clipping implementation also contribute to `g`; substituting a
different loss or clipping a different parameter subset would change the
meaning of the experiment.

For plain SGD with momentum 0.9, zero dampening and weight decay, no Nesterov
term, and minimization, define `v = 0.9*m + g`. Missing momentum is zero. A
parameter with absent gradient is skipped by SGD, so its `v` coordinate must
be zero rather than decaying old momentum into an update. The actual parameter
step at learning-rate multiplier `a` is `-base_lr*a*v`. The cosine is zero
when either compared vector has zero norm.

The three new loss coordinates are `dot(grad(L_probe), v)`, without learning
rate or an extra minus sign. A positive dot therefore predicts a loss decrease
under the negative SGD step. `v` must be detached: these are first-order
directional derivatives, not derivatives through the gradient calculation or
momentum construction. Raw dots are retained and normalized by the fitting
pipeline later; unit-vector normalization would remove magnitude information
and constitute a different registered field.

Probe losses must be exactly those in the existing observation map: mean
response image BCE, mean response teacher-forced text CE, and mean clean joint
loss. Use the same fixed deployment action, teacher forcing, response noise
`71027 + condition_index`, and clean noise `81027`. An unequal panel-size
change would require declaring whether condition or example weighting is
intended; current panels use equal sizes.

## State and information boundaries

Feature extraction must preserve local parameters, frozen base parameters,
the complete optimizer state, incoming parameter-gradient buffers, and global
Torch RNG. Temporary gradients are allowed, but must be restored in a
`finally` block. Explicitly reject inference mode, which cannot supply the
required derivative graph. The helper should validate its supported SGD
configuration rather than silently treating Adam, Nesterov, or weight decay
as the same dynamics.

Only original fitting trajectories 0–7 are enriched by replay. Their recorded
parameter/optimizer hashes must match before attaching new features and the
old labels. H7 audit trajectories 8–15 cannot enter the new fit or candidate
selection. A conditional H12 audit uses fresh IDs 16–23 after its own source
and controller freeze. Those trajectories still evaluate the same training
response panel; they test optimizer-path transfer, not new task labels.

The seven old field coordinates followed by the five directional coordinates
form H12. The remaining old richer coordinates follow them to make a common
30-dimensional measurement vector. Both the 12-dimensional generic projection
and the richer control receive these same measured quantities and the same
fitting/search budget. Reordering or silently omitting directional coordinates
from a comparator would invalidate this comparison.

## Compute and ordinary-training comparison

Every measurement requires one extra candidate and teacher forward plus one
backward for the next-minibatch gradient, four response-probe forwards, one
clean-probe forward, and three probe-gradient traversals. Count actual
examples and record these separately from branch-training work, value scoring,
model fitting, and replay. All representation candidates share this measured
feature bank; it is shared search overhead, not zero-cost information.

Keeping ordinary and field training at 288 optimizer steps matches their
update horizon. It does not by itself match total computation. A later primary
comparison must expose the same legal diagnostics and comparable search
opportunities, or include a strong ordinary/adaptive baseline allowed to use
the extra computation. Padding a fixed optimizer with unused derivative work
is not evidence that the field is a more efficient use of compute.

The current audit can establish predictive and decision skill within its
registered action envelope. It cannot establish total training efficiency,
new-source retention, a Markov sufficient statistic, or the paper's HJB/FBSDE
hypotheses.

## Required execution contracts

Test the exact next-minibatch identity and clipped gradient, carried-momentum
direction, zero-momentum convention, and sign against an actual first SGD
step. Check probe dots against central differences of the same smooth
teacher-forced losses. Check state/gradient/RNG preservation under normal
execution and rejected optimizer/inference-mode inputs. These are interface
and numerical contracts; their synthetic or old-validation fixtures are not
scientific efficacy evidence.
