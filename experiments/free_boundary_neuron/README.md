# Free-boundary neuron study

This research package separates mathematical operator verification, a small
causal spiking-learning experiment, and an original-owner integration experiment.
The pinned native baseline is PR #4064 at
`fb9281e4a7ccfc4034281ed6310adea7e50f4474`. Existing terminal-probability,
dual-threshold neutral-decision, continuous-versus-spike, and transfer studies
retain their own semantics and results.

| Package | Question | Scope of evidence |
| --- | --- | --- |
| [`math`](math/THEORY.md) | Are the hitting operators, optimal-stopping examples, sensitivities, and numerical references correct? | Analytic derivations and independent numerical checks under declared assumptions |
| [`learning`](learning/PROTOCOL.json) | How do stopping boundaries and surrogate gradients affect a trainable hard-spiking evidence accumulator? | Synthetic Bernoulli evidence, fixed dynamics, paired training seeds |
| [`owner`](owner/README.md) | Can a versioned stopping readout drive actual original-owner execution, durable stopping, and recovery? | A separate finite Gaussian decision-time MDP and local research host |

The [umbrella protocol](PROTOCOL.json), [math protocol](math/PROTOCOL.json),
[learning protocol](learning/PROTOCOL.json), and [owner protocol](owner/PROTOCOL.json)
are the registered specifications. Passing a numerical or execution gate does
not establish learning superiority or production qualification.

## Six learning arms

All arms use the same eight bipolar integrate-and-fire cells, visible evidence,
costs, deadlines, action set, and training budget. The following names are the
literal arm identifiers in result files.

| Boundary method | Standard logistic surrogate | First-passage surrogate |
| --- | --- | --- |
| Validation-tuned constant thresholds | `fixed:standard` | `fixed:first_passage` |
| Directly learned context thresholds | `direct:standard` | `direct:first_passage` |
| Model-informed Bellman stopping boundary | `free:standard` | `free:first_passage` |

The neural core has 57 trainable scalars; the direct context head adds 12.
The free-boundary method receives a known task model. Same-information raw-belief
Bellman and myopic value-of-computation references expose that model advantage.
Abstentions remain in utility, duration, and coverage denominators. Truth is
available for training losses and scoring, never as a runtime input.

Five screening seeds and ten independent confirmation seeds give 90 fits.
Episode-keyed random streams pair the arms without exposing future observations.
The two primary confirmation contrasts are OOD net utility of `free` minus
`direct`, separately for each gradient. A joint superiority claim requires both
family-adjusted confidence-interval lower limits to exceed the registered
minimum practical effect of 0.005. Screening, secondary factorial comparisons,
and neutral or negative outcomes retain their declared roles.

## Reproduction and source seal

Post-publication review corrected one checkpoint filename assertion in a
development test. The [acceptance record](ACCEPTANCE.md) distinguishes the
original scientific source from this maintenance revision. Original results
retain `results/SOURCE_SEAL.json`; that seal correctly rejects the revised test
file. It must not be replaced or treated as a seal of current HEAD.

For the exact published scientific source and its archived evidence, use a
separate checkout of `c32392367b7587d09806ca5cbc74678a168b4e16`, then verify its
original seal. This commit contains the original experiment and the known stale
test assertion. The mathematical and scientific result auditors do not execute
that development test.

```bash
(
set -e
git worktree add --detach ../hepta-free-boundary-archived c32392367b7587d09806ca5cbc74678a168b4e16
cd ../hepta-free-boundary-archived
python3 -m experiments.free_boundary_neuron.provenance verify \
  experiments/free_boundary_neuron/results/SOURCE_SEAL.json
)
```

For the corrected maintenance revision, verify
`results/maintenance001/SOURCE_SEAL.json`. That later seal is not retrospective
registration of the original experiment. A fresh scientific reproduction must
use its own committed source, new seal and unused destinations.

Run from the repository root using Python with the versions in
[`requirements.txt`](requirements.txt). Learning uses NumPy manual reverse mode;
Torch is not required. Behavioral and directional-gradient fixtures run without
scientific seeds:

```bash
python3 -m unittest discover -s experiments/free_boundary_neuron/math/tests -v
python3 -m unittest experiments.free_boundary_neuron.learning.test_learning -v
```

Commit the reviewed source and protocols before freezing. `freeze` requires its
input inventory to be tracked and clean, records source identities and environment,
and refuses to replace an existing seal. Use new destinations for each attempt.

```bash
(
set -e
study=experiments/free_boundary_neuron
attempt="$study/results/reproduction001"
seal="$attempt/SOURCE_SEAL.json"
test ! -e "$attempt"
python3 -m experiments.free_boundary_neuron.provenance freeze "$seal"
python3 -m experiments.free_boundary_neuron.provenance verify "$seal"

python3 -m experiments.free_boundary_neuron.math.audit \
  --source-seal "$seal" --output-dir "$attempt/math"
python3 -m experiments.free_boundary_neuron.math.belief_reference_check \
  --source-seal "$seal" --output "$attempt/math/belief_reference.json"

python3 -m experiments.free_boundary_neuron.learning.runner \
  --phase screening --source-seal "$seal" \
  --output "$attempt/learning/screening.json"
python3 -m experiments.free_boundary_neuron.learning.runner \
  --phase confirmation --source-seal "$seal" \
  --output "$attempt/learning/confirmation.json"
python3 -m experiments.free_boundary_neuron.learning.runner \
  --phase audit --source-seal "$seal" \
  --results "$attempt/learning/confirmation.json" \
  --output "$attempt/learning/confirmation_audit.json"
python3 -m experiments.free_boundary_neuron.analysis \
  --source-seal "$seal" --results "$attempt/learning/confirmation.json" \
  --output "$attempt/learning/confirmation_analysis.json"
)
```

Audit screening with the same audit command and its own input/output names.
Do not alter methods after viewing screening or confirmation results and reuse
the original registration. Source changes require a new seal and clearly
identified attempt.

The [owner instructions](owner/README.md) explain building the source-composed
host and testing real native stopping and recovery. The archived registered run
used `results/math/run001/readout_affine_v1.json`, destination
`results/owner/run001`, the original source seal, and its actual build receipt.
A fresh reproduction must instead use its newly generated model, matching seal,
build receipt, and unused owner destination. The receipt and run bind the binary
hash. Archived replay uses that exact binary; rebuilding on another system is a
fresh reproduction unless the binary is byte-identical.

## Evidence and interpretation

Learning outputs include trained arrays, validation choices, per-seed results,
work counters, and sibling checkpoint directories. Checkpoints precede test
scoring; failed attempts preserve completed work and invalid-attempt receipts.
The independent auditor regenerates validation and test streams, repeats fixed
threshold selection, and scores saved parameters without retraining. Owner
evidence retains complete registered episodes, journals, witnesses, event ledgers,
identity bindings, and separate audit costs. Preflight or development artifacts
are not confirmation results. The commands above specify destinations, not
assertions that a run has succeeded.

Interpret results within these limits:

- The learning comparison fixes surrogate drift, volatility, cancellation rate,
  and horizon. It does not test joint learning of mu, sigma, and lambda or an
  inner/outer meta-learning algorithm.
- The first-passage derivative is a local neural surrogate. It is not the exact
  Bernoulli evidence transition, a terminal payoff probability, or a proof for a
  moving boundary.
- Learning and owner boundaries are numerical decision-time Bellman boundaries.
  They do not establish continuous smooth-pasting; the eligible continuous
  stopping examples and their assumptions are treated separately in the math.
- The owner readout uses its declared Gaussian grid state and remaining time.
  The trained learning SNN is not deployed in that host.
- Hard inference skips surrogate derivative calculations. Actual dense inference
  work is reported separately from hypothetical stopped-prefix work. Native
  cancellation, CPU time, bytes, and synthetic utility costs do not establish
  measured hardware energy savings.
