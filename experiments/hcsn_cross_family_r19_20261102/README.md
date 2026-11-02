# R19: family-blind ordinary model-class inference and held-out process shifts

This extends R18's positive-Markov/iid population to public training streams from
independent, sticky and clockwise/counterclockwise rotor generators. The fitter
receives only complete raw token streams and group identity, with no generator
parameters or family labels. Candidate classes are empirical transition
particles, exchangeable Dirichlet sequences and unrestricted row-Dirichlet
sequences. A separate public validation stream fits mixture weights and selects
the strongest static candidate by predictive log likelihood.

At runtime, joint inference receives raw prefix/mask, observed alias bridges,
alias query and price. There is no family oracle. Class-resolved latent weights
survive actual indexed READ; broad-component posterior is recomputed after READ.
The expected READ payoff uses the same post-READ guard as execution. Cached
reprioring reproduces the static candidate under the fitted common key-prior
marginal; malformed priors are rejected.

The original 90% reliability target remains unchanged. Calibration must satisfy
both overall and genuinely-fractional accepted risk in **each** trained family,
with simultaneous 48 exact Clopper-Pearson bounds. Confirmation tests five
families separately, including switching-rotor and pair-renewal processes never
opened for fitting, calibration or guard/threshold selection. The primary
mixture must pass all per-family safety, fractional-coverage, shared-prefix proper
score and actual fee-paid payoff gates; a failure in any family makes the whole
gate false. Bootstrap multiplicity and limitations are fixed in `protocol.json`.

The raw-prefix guard is empirical: it does not identify arbitrary unknown
processes. Refusal safety is not useful uncertain answering, so each family must
have at least 32 accepted predictions below probability `1-1e-9`. Source and
fitted-control freezes precede separate confirmation, with no post-test repairs.

These are ordinary full-prefix finite models, not an analytical neuron, learned
semantic addressing or real AV binding. Alias queries actually use the observed
mapping. Recorded 20/100 timing gaps do not evolve the static content. CPU batch
cost includes all model candidates and failures; task READ fees are not physical
compute/energy savings.

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m experiments.hcsn_cross_family_r19_20261102.campaign prepare
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m experiments.hcsn_cross_family_r19_20261102.campaign confirm
```

`SOURCE_PUBLICATION.json` must bind verified immutable source readback before
prepare. `CALIBRATION_PUBLICATION.json` must bind verified fitted-control readback
before confirmation. All outputs use create-only writes.
