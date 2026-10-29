# Restoring and inspecting the Round5 research delivery

Read [ACCEPTANCE.md](ACCEPTANCE.md) for the scientific outcome and limits. The
registered range-expansion comparisons and all eight joint profile gates failed.
Restoring evidence or passing adapter tests does not change that result.

## 1. Source and numerical environment

The scientific dependency snapshot contains 102 unchanged inherited files and
five Round5 selection files. The independent head and typed interoperability
adapters are separately versioned. The experiment froze Python **3.12.14**,
NumPy **2.3.5**, SciPy **1.17.0**, their actual numerical build configuration,
Linux/platform identity and the declared thread environment. Full details are in
`evidence/selection_registered_001/PREPARED_INDEX.json` and `FREEZE.json`.

The exact experiment interpreter was:

```bash
HEPTA_REVIEW_PY=/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python
```

Qualified replay checks the complete recorded environment, including that
executable path. A different environment is a new portability evaluation; do
not edit the original freeze to make it appear identical. The first independent
review really did reject the `python3` alias, and that failed attempt is retained.
Archive restoration itself uses only the Python standard library and does not
require the numerical environment to match.

## 2. Restore the raw arrays from a Git checkout

The Git-readable JSON mirrors sit outside the raw-data destinations so the
destinations can be created atomically. Run from the repository root:

```bash
python -m experiments.analytic_event_neuron.round5.evidence_io restore \
  experiments/analytic_event_neuron/round5/evidence/envelopes/selection_prepared_001 \
  experiments/analytic_event_neuron/round5/evidence/selection_registered_001/prepared

python -m experiments.analytic_event_neuron.round5.evidence_io restore \
  experiments/analytic_event_neuron/round5/evidence/envelopes/selection_confirmation_001 \
  experiments/analytic_event_neuron/round5/evidence/selection_registered_001/confirmation
```

Both destinations must be absent. The downloadable research delivery already
contains the restored raw directories, so these two commands are unnecessary
there. Never delete an existing research attempt to rerun a command.

The preparation envelope contains 251 original files (including `PREPARED.json`),
10,372,700 bytes. Confirmation contains 187 files, 56,646,467 bytes. The reader
checks the encoded chunks, decoded archive, member inventory and every member's
original bytes before writing. Version1 gzip and version2 xz envelopes are both
supported. The original development smoke and scientific figure also have their
own independent envelopes. See [EVIDENCE_TRANSPORT.md](EVIDENCE_TRANSPORT.md).

## 3. Recompute the completed confirmation without retraining

Under the exact recorded numerical environment, write a new review receipt
outside the immutable scientific run:

```bash
"$HEPTA_REVIEW_PY" -m experiments.analytic_event_neuron.round5.evidence.reviews.review_confirmation \
  --run-dir experiments/analytic_event_neuron/round5/evidence/selection_registered_001 \
  --freeze experiments/analytic_event_neuron/round5/evidence/selection_registered_001/FREEZE.json \
  --expected-freeze-sha256 1e5676bd481ef5a3d13e63a5de8eb90223e9abf55bb918721b28ab32e1f5ba16 \
  --expected-index-sha256 7de85b15d658d34cef74a3b7ebeb7e9ac19d9fcef446c056f4566c15b0fe7636 \
  --expected-results-sha256 3a7d02813f2c0d7338c9e1d9d344f4406c13a0e4b01900c659911bbe371005bd \
  --output experiments/analytic_event_neuron/round5/evidence/new_replay_001/REVIEW.json
```

This independently recalculates the saved scores, intervals and gates. It does
not fit models or generate new queries. The preparation-only reviewer is a
**pre-freeze** gate and deliberately rejects runs that already contain a freeze
or confirmation; it should not be invoked on the completed run. The standalone
study summary also refuses to overwrite an existing `RESULTS.json`.

## 4. Exercise the typed interfaces

The existing targeted suites cover the original typed bridge, study provenance
and trained-head adapter:

```bash
"$HEPTA_REVIEW_PY" -m unittest \
  experiments.analytic_event_neuron.round5.test_interop \
  experiments.analytic_event_neuron.round5.test_selection \
  experiments.analytic_event_neuron.round5.test_prediction_head -v
```

The head suite requires restored prepared evidence and the exact frozen
environment. These suites use separate unit/development inputs. They do not
create registered confirmation data. Preserved historical test snapshots under
`evidence/` are audit artifacts, not test-discovery targets.

Use [PREDICTION_HEAD_CONTRACT.md](PREDICTION_HEAD_CONTRACT.md) for the actual
`PredictionHead` / `PublicHistory` / `TerminalForecast` / `release_q24` API and
its effective domain. First-passage cell state, terminal-head identity and signed
communication decoder state remain separate checkpoint types.

## 5. What this delivery cannot restore

This package is the new Round5 research delivery. It is not the missing original
Round4 final archive, a complete checkout of every repository file, or an original
native executable. The old scientific sources are included by their frozen
identities for reproducibility. Native build, actual delivery/readback/action
execution, latency, energy and production promotion require their own evidence.
The successful interface tests and failed scientific gates retain that boundary.
