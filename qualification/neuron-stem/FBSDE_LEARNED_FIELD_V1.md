# Small learned continuation proposal plus original-problem correction

This is the numerical learning stage following `FBSDE_COUPLED_V1.md`. It does not
modify either real-Encoder profile or turn mathematical training points into
human observations. The selected object is a proposed decoupling field for ONE
fixed scalar coefficient profile, not a language model or an action policy.

A 2->32->32->1 tanh network (1,185 actual parameters, float64 CPU) takes time and
state coordinates. Its bounded output is (1+beta*T)*tanh(net(t,x)). Training uses
400 recorded Adam steps on approximately 64 tabulation points per time layer of
the correct continuation field. The field preparation, optimizer construction
and training are recorded. The target is a numerical table, never an imagined
independent outcome or a future truth label.

After fitting, parameters are frozen. On six fixed initial states, actual forward
propagation uses the proposed field to produce one Y per public prefix. The
ORIGINAL global map is evaluated; its residual and the exact-arithmetic bound
r/(1-q) are recorded. A fixed-point corrector then meets the same tolerance as a
cold solve. A small training loss is never substituted for this condition.

Controls are (1) cold global solve, (2) tabulated-field initialization plus the
same corrector, (3) learned initialization plus the same corrector, and an
independently implemented monolithic Newton reference. References are measured
as research validation work, not secretly made available to the proposals.
The recorded coefficient profile cannot silently change between fitting and use.
Here 'profile' is an immutable value binding, not a cryptographic signature or a
native source-use grant; no signing is performed.

## Observed outcome and cost interpretation

Local execution recovered all six original discrete solutions after correction,
with supremum Y error below 1e-9 against the independent monolithic reference.
The neural proposal reduced some map iterations but was NOT a measured total-cost
winner in the executed batch. The tabulated control is intentionally retained.
It too must pay its preparation on actual observed uses, not hypothetical future
volume. Source-specific raw costs, uncorrected errors, final errors, iteration
counts, frozen tensor hashes and the trained small field are saved together.

The recorded per-method CPU component totals are NOT a complete native deployment
lifecycle: importing runtimes, loading a deployed artifact, native journalling,
migration, decoder effects, energy and production endpoint latency have not been
qualified. A whole experiment CPU envelope and separate reference CPU are also
reported. No net resource advantage, model-independent reasoning, independent
future learning or production activation is inferred.

This experiment establishes a concrete interface needed for the proposed System 2:
learned continuation information can propose an initial solve, while an original
boundary-value residual can still correct it. It does not establish that this
particular small scalar task warrants a neural approximation over a cheap table.

## Reproduction

```sh
PYTHONPATH=qualification/neuron-stem python3 qualification/neuron-stem/fbsde_study.py \
  --profile learned_coupled_v1 --output /new/learned-coupled
PYTHONPATH=qualification/neuron-stem python3 -m unittest fbsde_coupled_tensor_checks -v
```

The unchanged study entrypoint has separate explicit profiles; the default still
runs the original exact experiments. A dedicated CPU job runs this learning
profile and preserves its exact source. It neither waits for nor substitutes for
the two actual pretrained Encoder jobs. Local Torch tests fail when unavailable;
they do not skip. Float residual bounds remain conditional on exact arithmetic,
not interval-certified enclosures of rounding or continuous-time error.
