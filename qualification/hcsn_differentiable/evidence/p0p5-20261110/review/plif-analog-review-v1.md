# Independent analog-PLIF diagnostic review

**All four historical attempt checks and the selected768-update independent
replay pass.** This supports the training-only diagnostic and candidate choice;
it does not establish full-data training adequacy or task benefit. The
[receipt](plif-analog-review-v1.json) and [script](review_plif_attempts.py) retain
source/input/model identities, NumPy metric recomputation, causality checks,
update counts and costs.

## Reproducible candidate comparison

Both256-update trials and both fresh1024-update trials have identical initial
tensor states. Their saved configuration identifies the analog readout,
threshold, initial tau and input-weight gain; it matches their plan, initial
checkpoint, trained checkpoint and result. The recorded40 source files for each
trial match the retained before/after hashes and the actual frozen files.
The frozen frontend and head remain unchanged. Every optimizer state counter
agrees with the reported update count and every journal is consecutive.

Fresh reconstruction from the saved configuration and final weights reproduces
all accuracy/F1/confusion results independently in NumPy. Repeating each forward
is exact, and changing inputs from position128 onward leaves all earlier logits
exactly unchanged. No D or E features or labels are loaded; only A01-0 content and
class weights fitted to ABC training data are used. The shared manifest still
contains D episode metadata, so this is not a claim of zero metadata exposure.

| Diagnostic | Updates | Accuracy | F1 over classes present in A01-0 | First observed passing checkpoint |
| --- | ---: | ---: | ---: | ---: |
| Membrane, initial attempt | 256 | 0.81640625 | 0.75592664 | None |
| Spike trace, initial attempt | 256 | 0.67968750 | 0.54461324 | None |
| Membrane, fresh extended attempt | 1024 | 0.96484375 | 0.96244065 | 1024 |
| Spike trace, fresh extended attempt | 1024 | 0.99218750 | 0.99055273 | 768 |

The declared rule requires accuracy at least0.95 and present-class F1 at least0.9.
The trace configuration first passes at the scheduled768-update observation;
membrane first passes at the1024 observation. Intermediate updates were not all
evaluated, so these are not exact threshold-crossing times. Both extended trials
run to1024 and all their work remains charged.

## Independent replay of the selection evidence

The original768-update weights were not retained. The independent review fills
that gap with a separate deterministic execution from the identical initial
state through768 updates. Every loss and gradient norm agrees with the original
768 journal entries with absolute difference0. Its state at update256 equals
the separate original256-update checkpoint tensor for tensor. At update768,
accuracy0.96484375 and present-class F1 0.9655121591746499 exactly reproduce the
recorded selection curve. The newly retained intermediate checkpoint, logits,
labels and independent update journal belong to this review execution, not to
the historical run.

This verifies the stated training-only reason for choosing spike_trace among
these two candidates. It does not establish that this readout generalizes better,
that all PLIF configurations were adequately tuned, or that it beats another
core. A full-data fit must start from its own declared fresh initialization.

## Configuration correction and cost scope

The implemented smoother is `trace_t = .75*trace_(t-1) + .25*spike_t`, reset at
window start and indexed by event number. Its exact exponential e-fold duration
is `-1/log(.75) = 3.4760594968` event steps. The historical field
`trace_time_constant_event_steps=4.0` is the reciprocal injection scale,
`1/(1-.75)`, not that e-fold constant. The historical files stay unchanged;
the training owner has adopted explicit decay, injection and e-fold fields in
the fresh source. This is not a physical-time decay constant in seconds.

The four historical attempts perform2560 optimizer updates and655360 labelled
event presentations, but only256 distinct A01-0 events are involved. Their two
outer campaign walls total172.737596889s; measured child CPU totals172.426831s;
summed inner-trial wall is164.035417369s. These accounting scopes overlap and must
not be added. Energy remains unmeasured. The independent review costs46.81099s
wall, including its45.64503s768-step replay, and is a separate validation cost.
The additional PLIF attempts and the extended diagnostic budget remain tuning
costs in any later resource comparison.
