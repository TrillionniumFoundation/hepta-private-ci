# Shared Stem / Cell Artifact P0

This directory is a research-only contract package for the next Hepta Neuron
Cell experiment. It defines an auditable comparison between a frozen shared
Stem and lightweight per-Cell adapters, gates, memory namespaces, and heads.

The package deliberately does not load a checkpoint, change weights, select a
production model, activate a Cell, or perform a physical split. `propose_split`
creates a zero-delta child proposal for a future snapshot only. A failed gate
becomes `hold`; it cannot become `accept_next_snapshot`.

The transfer matrix requires:

* one immutable Stem digest for every candidate;
* matched resource budgets and explicit FLOPs, memory, latency, and risk;
* an independent new source rather than a re-scored training source;
* a Pareto view so quality gains are not reported without their resource cost.

`ParameterLedgerV1` reports logical resident parameters separately from active
parameters. This is the accounting needed to test whether many Cells improve
coverage at lower resident or active cost; it is not evidence that a small
model has the general capability of a 10T or 100T model.

The Reader helper emits the four arms `none`, `distractor`, `withheld`, and
`full`, and keeps the evaluator gold outside every model request. The split
gate requires independent Reader evidence, a future lower confidence bound
above the baseline upper bound, bounded old-task degradation, calibration and
OOD limits, complete fallback and rollback coverage, and zero deleted replay.

`ModalityEnvelopeV1` is the boundary for text, image, audio, and video feature
front ends. It binds raw input, feature, projector, and Stem digests, plus
slot/time/region metadata, before any Cell sees a shared latent. It is an
encoder-side contract; generation still requires separately qualified text,
image, video, and audio decoders.

`System2IntervalGateV1` is a budget-aware NDU/System2 admission shadow. It
accepts an advisory candidate only when its utility lower bound minus the fully
charged encoder/Cell/controller/verification/latency/memory/energy cost is
strictly above every other feasible candidate's upper bound by the margin.
Overlap, missing alternatives, incomplete evidence, and any attempted
authority or efficacy claim return `NO_GO`/`DENY_ALL`.

Run the deterministic contract tests with:

```bash
python3 -m unittest discover -v \
  -s qualification/stem-transfer-cell-artifact-p0 -p 'test_*.py'
```

Passing these tests is only protocol validation. The next scientific gate is a
real frozen-Stem transfer matrix with independent new data, full Reader
citations, and the repository's required `blocking-ci` checks.
