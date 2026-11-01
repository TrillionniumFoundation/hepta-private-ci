# Multiple missing typed content events and explicit generator uncertainty

This is an ordinary exact finite reference, with no analytical neuron, learned
network, future label or owner target as an inference/control input. It extends
the R16 single-WRITE erasure problem to two or three arbitrary missing prelude
events. Masks are uniform independent positions; unlike erasing an informative
WRITE, their public mechanism does not reveal the absent event type.

`posterior.py` marginalizes missing distractors and enumerates missing WRITE
slots, legal keys and values. The two admitted value laws are independent uniform
sampling with replacement and uniform ordered sampling without replacement. Both
retain the original four-key/eight-value schedule: one initial WRITE per key,
four shuffled distractors, and (Selective only) two distinct overwrite keys.
The full correlation between missing events and final content is retained.
There is no epsilon floor, label-conditioned support repair or success-only fit.

All surviving assignments have the same prior weight. Conditional on a mask,
the raw-prefix likelihood per surviving row is

`1 / (choose(2K,K) K! P(K,U) A (KV)^D)`,

where `A=P(V,K+U)` without replacement or `V^(K+U)` with replacement, and `D`
is the number of observed distractors. Missing distractor attributes integrate to
one. READ conditions on the actual owner token at the original missing index;
observing a distractor adds its independent `1/(KV)` likelihood without turning
it into a WRITE. Identical READ retries are idempotent, and conflicting retries
are rejected using retained raw token receipts.

The unknown finite-set controller keeps both supported laws and may reject one
when a public prefix or actual READ has zero likelihood under that law. It
answers only when all remaining laws agree on a label with probability at least
0.8 under each. Its displayed distribution is the equal-model mean, **not** a
Bayesian posterior for an arbitrary unknown generator. The accepted confidence
bound only applies to these two finite laws. An independent audit includes a
same-prefix/different-target witness demonstrating that arbitrary unknown laws
cannot be identified from the observed prefix.

Binding uses a completely supplied symbolic alias permutation, not learned
language, real audiovisual content or unknown/missing bridge relations. There is
no claimed analytical-core contribution or architecture adoption result.

Before new-world verification, `SOURCE_FREEZE.json` binds the complete execution
source and protocol. `SOURCE_PUBLICATION.json`, when present, must bind its exact
SHA256, a 40-hex commit SHA and verified remote readback. Absence of this receipt
forces the result role to development verification. A receipt with inconsistent
identity is rejected before opening worlds.

From the repository root:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m experiments.hcsn_multi_missing_r17_20261101.run --audit /tmp/new-missing-audit.json
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m experiments.hcsn_multi_missing_r17_20261101.run --run /tmp/new-missing-verification
```

Outputs are create-only. Run the campaign in a fresh independent copy if its
process receipt already exists. Complete child CPU includes Python startup,
imports, every model attempt, actual acquisition and output; development and
independent audit costs are recorded separately and must not be treated as zero.
