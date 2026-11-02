# Digital-cell multiround feedback study

This is the next development and prospective confirmation after PR #4560,
`72917c2a32d79a63071a074b6a57d98d331f7fb8`. Its earlier frozen results retain
their original identity. This directory adds a new experiment; it changes no
parent study or production neuron.

## Scientific question

Can repeated actual-policy supervision improve belief, continuation Q and
executed utility when terminal values retain their declared stopping semantics?
The primary comparisons are multiround minus single-snapshot feedback for the
first-passage and ordinary-bank families, separately in IID and time/input OOD.

All physical cell parameters are held at each fit's paired initialization. This
stage trains the hidden readout, belief and continuation Q. Fixed physical
parameters permit caching exact finite conditional features without detaching a
trained dynamics parameter. This is a readout/feedback experiment, not a claim
of joint physical training or a new continuous stochastic process.

## Fifteen candidate arms

- First-passage: drift × bank driver four cells; explicit event-sign readout ×
  reset destination four cells, sharing the common baseline, giving seven arms.
- The common first-passage mechanism also has single-snapshot and no-visit arms.
- Ordinary bank has multiround and single-snapshot arms.
- The completed-observation accumulator has free/structured head × no-visit/
  multiround supervision, all four cells.

All cell arms use the same completed-READ impulse. Sign pooling changes the two
refractory readout rows; signed reset and public observations may retain sign.
The reset factor changes release destination, retaining event probabilities and
recovery timing. See [mechanisms.md](mechanisms.md).

## Acceptance and evidence

Candidate CPU covers setup, feature encoding, feedback collection, optimization
and finalization. Every fit/arm must satisfy the registered numerical tolerance,
and every within-fit range is checked. Shared data preparation, content setup,
persistence and diagnostics remain in whole-worker process receipts; nested
timings are not added twice. No measured energy or deployment throughput claim
is made.

Final-policy quality requires separate belief calibration, selected-action Q,
pairwise ranking, margin, teacher regret and empirical support checks, alongside
actual utility. Full numerical-state identity and the finite diagnostic strata
are reported separately. Collected rows enter supervised coverage only after a
complete optimizer update actually used them.

The independently fitted affine ridge readouts use the same selected event/
recovery pairs for before-cell, after-cell, before-full and after-full inputs.
Training uses only the final baseline policy's TRAIN fixed-controller traces;
all coefficients are sealed before new test worlds. This measures linear
recoverability within that baseline population, not irreversible information
loss or a counterfactual reset effect across different policies.

## Entry points

- `study.py`: bounded training, actual execution, process accounting.
- `training.py`, `TRAINING.md`: transactional CPU interruption and feedback.
- `diagnostics.py`, `quality.py`: final-policy support, control quality, readouts.
- `statistics.py`: independent-fit planning and simultaneous primary intervals.
- `freeze.py`: complete model/provenance inventory and publication binding.
- `archive.py`: byte-preserving bounded artifacts and safe cold restoration.
- `REPRODUCE.md`: exact phase commands and artifact interpretation.

The source/protocol, formal fitted models and confirmation evidence are published
in separate stages. Formal conclusions are given in `REPORT_ZH.md` and
`evidence/ANALYSIS.json` only after the corresponding frozen run completes.
