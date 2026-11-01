# R18: learned ordinary reference for previously unseen generator parameters

This study addresses R17's point-mass-only abstention limitation. It fits an
ordinary Markov-particle mixture and a pooled iid empirical-Bayes baseline from
complete public training streams. Models receive neither generator parameters
nor owner targets. Unknown generator parameters are fresh draws from the same
continuous parameter population; this is not a universal unknown-family result.

Four supplied symbolic addresses and four values are used. Six WRITEs are
interleaved with 8 or 24 distractors; two, three or four arbitrary positions are
missing independently of their contents. A raw alias-only query is actually
mapped through four observed raw bridges. The full-prefix ordinary reference
keeps joint missing-event/content uncertainty and conditions on an actual indexed
READ. The recorded 20/100 time gaps do not evolve these static contents: they are
public timing metadata, not continuous-time or learned long-context evidence.

The protocol fixes generator-disjoint fitting, OOD calibration, risk calibration
and confirmation seeds. Calibration uses one world per generator and exact
simultaneous Clopper-Pearson bounds for accepted and fractional-accepted error.
A failing uncertainty gate falls back to concentrated predictions and is reported
as failed. There is no post-confirmation threshold repair. Confirmation intervals
resample whole generator clusters and retain all four dependent worlds.

`SOURCE_FREEZE.json` and remote source readback must exist before `prepare`.
`POSTCALIBRATION_FREEZE.json` then pins fitted models and all selected controls;
remote calibration readback must exist before `confirm`.

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m experiments.hcsn_unknown_generator_r18_20261101.campaign prepare
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m experiments.hcsn_unknown_generator_r18_20261101.campaign confirm
```

All outputs are create-only. Whole child-process CPU covers interpreter/imports,
fitting, every calibration candidate, failures and outputs. Raw records are in
deterministic gzip chunks with exact input hashes. Development audit cost and
any later audit cost remain separate. Read `protocol.json` for gates and limits.

No analytical neuron, HCSN core D-B, GPU/energy or production ownership claim is
made by these ordinary finite-reference comparisons.
