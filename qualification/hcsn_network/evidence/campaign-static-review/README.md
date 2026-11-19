# Independent static and sealed-fit metadata audit

## Scope and outcome

This review inspected the frozen protocol, campaign, training, evaluation,
data/model definitions and arithmetic reader. It then read all 30 collected
training terminals, RESULT records, training journals and process requests.
The complete selection seal was checked against the original COST, RESULT,
selected checkpoint and selected-validation file hashes. Checkpoint tensors were
not deserialized. No dataset, evaluation result, test logits or test labels were
opened by this reviewer. There were zero model, matrix-action and optimizer calls.

All 30 fits exited zero. All 26 frozen source-file hashes matched the protocol.
All 30 chosen snapshots were the best eligible validation records under the
frozen accuracy/negative-cross-entropy ordering; their in-memory snapshot
completion times were at most 60 seconds. Completed update journals had no gaps
or duplicate ordinals, and their validation records equaled RESULT.json.
All sealed original hashes matched. This is a metadata/control-flow audit,
not the later numerical recomputation of prediction scores.

Protocol SHA-256: `9601216e77b3dc5b3b41f77d7df8f124b7ab176692b0a0b66f24773b95eec9e0`.
Campaign source commit: `8fe7bc209803659cc3f4780be0940c5183ca6e9b`.
Raw per-fit source paths and SHA-256 identities are in INITIAL.json;
FINAL_FIT_METADATA.json binds the common seal and the later hash readback.
The initial persisted snapshot already contained all 30 terminated fits.

## What the 60-second budget means

The scientific clock starts immediately before model construction. It includes
model/optimizer construction, training, validation, validation NPZ writes and
an improved candidate's in-memory deepcopy. Imports, source/runtime checks,
data loading and split serialization happen before this clock and are included
in the separately reported full child-process cost.

The loop stops starting work after its wall-clock deadline. An update already
in progress may finish late. Every fit has one such late completed update in
this execution. All late updates are retained in the cost and trace, and none
is part of the selected checkpoint. The largest overrun is
`flow_no_return-s211`: update 428 starts after the prior update's 49.266124-second
record and completes at 66.936765 seconds. Its selected snapshot is update 358,
completed at 40.330395 seconds, so the late update does not enter selection.
The training interval for that fit is 66.937155 seconds, not 60 seconds.

The chosen snapshot is an in-memory deepcopy within the deadline. `selected.pt`
is serialized after the training loop. The implementation does not establish
that a durable checkpoint file existed within the 60-second window. It also
does not measure a filesystem fsync durability guarantee. Reports should say
"60-second selection window" and separately retain actual training/child cost.

## Shared-environment throughput

Affinity pins each child to logical CPU 0 or 1, with one declared numerical
thread and two concurrent children. This is not an exclusive CPU reservation.
The frozen observations explicitly do not enforce ancestor-cgroup quotas and
do not contain a per-update CPU, frequency, throttling or competing-job trace.
A single deterministic shuffle of the 30 fits reduces a fixed arm-order bias,
but it does not remove chronological resource variation.

SNN seed 307, 211 and 101 complete 601, 6,298 and 16,955 updates respectively.
Their training CPU times are 43.408239, 58.796536 and 59.554163 seconds. The
CPU-time ratio of the fastest-count and slowest-count fits is only about 1.37,
while their update-count ratio is about 28.21. Even training CPU per update,
including setup and validation, is 72.227, 9.336 and 3.512 milliseconds.
Therefore scheduler waiting alone cannot quantitatively explain the observed
update-count spread. The saved records cannot identify the remaining cause.

Initial validation finishes at 9.635604, 5.738050 and 1.281079 seconds for those
SNN fits. GRU seed 307, run in the same early time window as SNN seed 307, has its
first validation at 33.812950 seconds and only three validation opportunities.
SNN's code always executes the same ten dense recurrent steps; there is no
conditional event-sparse skip that would justify attributing these throughput
differences to measured event-driven computational savings.

The results are valid observations of the fixed selection policy on the actual
shared environment. They do not establish equal CPU-compute allocation, steady
state kernel speed, isolated seed effects, or training to a common optimum.
Both wall and CPU results, including startup and late work, must accompany the
quality comparison. Do not correct observed quality by simply scaling update
counts by CPU time; this would not recover an unobserved training trajectory.

## Sealing, replay and the successor review guard

The original training loader opens only pendigits.tra. The campaign collects
all training terminals, creates the 30-selection seal, and only then starts
separate evaluation children. Each evaluator checks the full successful roster,
all terminal identities, its selected checkpoint/result, and the selected
validation NPZ hash. It replays validation to the original 1e-12 bound before
opening the test file. These are source/control-flow and hash-ledger guarantees;
this review did not perform an operating-system file-access trace.

The original arithmetic reader, used alone, checked only the seal's protocol
hash before reading test labels, and its score comparisons lacked a saved-logit
finite check. NaN comparisons could otherwise fail open. The normal frozen
campaign/evaluator path already enforced the selection seal and finite model
outputs; no premature test access was found in that path.

Root added a separate successor invocation guard at
`evidence/benchmark-review/run_review.py`, SHA-256
`1d5ab1ce8ec9a351d7ad23c1d86644464826de0d2033e34b98b1f4a3e2fdd78e`.
Its repository `parents[4]` path is correct. Static review found no blocking
error for this campaign: it requires all 30 fit/evaluation terminals, complete
rosters, protocol/source identities, all selected/cost/result/validation hashes,
finite scalar records and best-eligible selection, before admitting the child
reader. The child rechecks the gate, requires saved logits' shape/type/finiteness
and valid label ranges, calls the unchanged frozen arithmetic reader, then
requires a finite complete 30-fit result. Full child wait4 costs are separate.
This is a successor invocation constraint, not a rewrite of the frozen study.
This reviewer has not executed it or inspected its future test-score output.

## Remaining operational and interpretation limits

- The campaign's evaluation stage writes failure counts but does not make its
  parent exit nonzero solely because an evaluation child failed. Consumers must
  inspect those counts. The successor guard requires zero failures.
- Routine spawn failures and deadline/exit races are recorded, but the campaign
  has no complete crash-recovery protocol for an abrupt controller failure.
  No such failure was observed in these 30 collected training terminals.
- Test inference timing excludes data loading, checkpoint loading, and validation
  replay, while full evaluation-child costs include those operations. The model
  is already exercised by validation before the timed test pass; this is not a
  cold-start end-to-end inference latency claim.
- Autograd saved-tensor payload counts include repeated saves and are not unique
  allocation or peak allocator memory. Logical recurrent state, physical-law
  tensors, serialized continuation state and process RSS remain distinct fields.
- The three seeds reuse one fixed training/validation/test split. Their standard
  deviation mixes optimization randomness and runtime variability; it is not
  uncertainty from three independent datasets. This short FP64 CPU task does not
  prove an all-modal, GPU, energy, or sufficiently-trained architecture ranking.

## Per-fit timing and selection

All rows below passed the metadata selection checks. Times are seconds.
Full child cost includes imports and final serialization. Training CPU per update
is not an isolated kernel measurement. Raw evidence for fit NAME is
`fits/NAME/{RESULT.json,training.jsonl}` and
`fit-processes/NAME/{COST.json,process/REQUEST.json}` in the campaign directory.

| Fit | CPU | Updates | Training wall / CPU | Full child wall / CPU | First validation | Selected update @ seconds | Validations |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| flow_no_return-s101 | 0 | 625 | 60.058572 / 59.995600 | 65.016947 / 64.874210 | 1.427122 | 518 @ 50.324246 | 6 |
| transformer-s307 | 1 | 12,075 | 60.002108 / 59.696118 | 64.798462 / 64.307054 | 2.498693 | 10,000 @ 50.108447 | 6 |
| snn-s307 | 1 | 601 | 60.026965 / 43.408239 | 72.787487 / 53.573038 | 9.635604 | 483 @ 50.324543 | 6 |
| gru-s307 | 0 | 1,411 | 60.123649 / 46.399975 | 73.750451 / 57.219219 | 33.812950 | 553 @ 50.022533 | 3 |
| gate-s101 | 1 | 7,838 | 60.000881 / 56.034592 | 68.410103 / 63.044835 | 8.142446 | 5,552 @ 50.029144 | 6 |
| cfc-s211 | 0 | 9,388 | 60.001984 / 58.460642 | 75.286842 / 70.864405 | 0.950025 | 7,143 @ 50.010238 | 6 |
| flow_no_return-s307 | 1 | 415 | 60.040070 / 59.880859 | 62.525400 / 62.319136 | 0.924422 | 337 @ 50.592865 | 6 |
| cfc-s101 | 0 | 10,701 | 60.001295 / 59.526228 | 63.429154 / 62.904155 | 0.891639 | 8,662 @ 50.017942 | 6 |
| flow_no_return-s211 | 1 | 428 | 66.937155 / 59.655700 | 70.463965 / 62.934658 | 1.398920 | 358 @ 40.330395 | 5 |
| flow_erlang4-s101 | 0 | 1,063 | 60.014294 / 51.315119 | 64.059223 / 55.270462 | 1.020649 | 1,013 @ 57.606000 | 6 |
| flow_mass-s101 | 1 | 672 | 60.071791 / 59.836502 | 63.383808 / 63.023661 | 1.375312 | 576 @ 50.263336 | 6 |
| flow_mass-s211 | 0 | 556 | 60.017047 / 59.715577 | 62.697217 / 62.291748 | 1.328035 | 188 @ 20.396174 | 6 |
| flow-s211 | 1 | 162 | 60.130622 / 50.126017 | 72.446102 / 61.274693 | 2.326153 | 142 @ 51.169640 | 6 |
| flow_fixed-s307 | 0 | 368 | 60.053657 / 50.997250 | 69.841063 / 60.648235 | 18.587006 | 240 @ 50.356795 | 5 |
| transformer-s101 | 0 | 12,204 | 60.000980 / 59.067666 | 62.715290 / 61.737670 | 1.089387 | 6,954 @ 40.042870 | 6 |
| flow-s307 | 1 | 269 | 60.001081 / 59.886968 | 68.885991 / 68.590490 | 3.847781 | 188 @ 50.291396 | 6 |
| flow_fixed-s101 | 0 | 624 | 60.090767 / 57.449923 | 62.181866 / 59.508552 | 1.179537 | 491 @ 50.319394 | 6 |
| flow_fixed-s211 | 1 | 444 | 60.128844 / 58.667376 | 67.906105 / 66.329638 | 1.903490 | 403 @ 51.047124 | 6 |
| flow_erlang4-s211 | 0 | 1,612 | 60.003423 / 58.585443 | 64.039899 / 62.540780 | 0.922440 | 1,360 @ 50.125635 | 6 |
| snn-s211 | 1 | 6,298 | 60.004651 / 58.796536 | 75.615824 / 73.990147 | 5.738050 | 4,371 @ 40.043134 | 6 |
| snn-s101 | 0 | 16,955 | 60.000512 / 59.554163 | 62.839787 / 62.299193 | 1.281079 | 8,518 @ 30.008579 | 6 |
| flow-s101 | 1 | 319 | 60.103459 / 60.059992 | 62.893218 / 62.789501 | 1.114095 | 287 @ 51.115718 | 6 |
| gru-s101 | 0 | 13,987 | 60.000794 / 59.586824 | 62.207920 / 61.759272 | 0.986031 | 11,371 @ 50.025791 | 6 |
| transformer-s211 | 1 | 12,985 | 60.016642 / 60.000938 | 64.645032 / 64.582887 | 0.758062 | 10,579 @ 50.012529 | 6 |
| flow_erlang4-s307 | 0 | 2,147 | 60.010334 / 59.554483 | 62.782434 / 62.301416 | 1.008541 | 1,717 @ 50.057984 | 6 |
| cfc-s307 | 1 | 5,091 | 60.002922 / 59.722373 | 67.455096 / 67.118224 | 5.907217 | 2,875 @ 50.039482 | 6 |
| gru-s211 | 0 | 13,106 | 60.002257 / 59.325980 | 63.205825 / 62.468534 | 1.180242 | 11,627 @ 50.051249 | 6 |
| flow_mass-s307 | 1 | 356 | 60.049942 / 57.936216 | 61.883419 / 59.743164 | 1.058705 | 300 @ 50.848129 | 6 |
| gate-s211 | 0 | 17,119 | 60.001231 / 59.607236 | 62.333446 / 61.882680 | 1.023218 | 13,659 @ 50.007505 | 6 |
| gate-s307 | 1 | 7,645 | 60.218001 / 45.095010 | 74.724959 / 52.420023 | 0.730644 | 7,382 @ 40.030300 | 6 |

## Charged late updates

Each row is the single final atomic update that completed after the selection
window. All are excluded from the selected snapshot. A very small positive
excess still counts as late; none is rounded back into the selection window.

| Fit | Late update | Completion seconds | Seconds beyond 60 | Selected update |
| --- | ---: | ---: | ---: | ---: |
| flow_no_return-s101 | 625 | 60.058493349 | 0.058493349 | 518 |
| transformer-s307 | 12,075 | 60.002002401 | 0.002002401 | 10,000 |
| snn-s307 | 601 | 60.016040163 | 0.016040163 | 483 |
| gru-s307 | 1,411 | 60.123370802 | 0.123370802 | 553 |
| gate-s101 | 7,838 | 60.000834242 | 0.000834242 | 5,552 |
| cfc-s211 | 9,388 | 60.001322632 | 0.001322632 | 7,143 |
| flow_no_return-s307 | 415 | 60.039972033 | 0.039972033 | 337 |
| cfc-s101 | 10,701 | 60.001189282 | 0.001189282 | 8,662 |
| flow_no_return-s211 | 428 | 66.936764789 | 6.936764789 | 358 |
| flow_erlang4-s101 | 1,063 | 60.014201074 | 0.014201074 | 1,013 |
| flow_mass-s101 | 672 | 60.071177482 | 0.071177482 | 576 |
| flow_mass-s211 | 556 | 60.015840297 | 0.015840297 | 188 |
| flow-s211 | 162 | 60.130396520 | 0.130396520 | 142 |
| flow_fixed-s307 | 368 | 60.053556430 | 0.053556430 | 240 |
| transformer-s101 | 12,204 | 60.000937985 | 0.000937985 | 6,954 |
| flow-s307 | 269 | 60.001015747 | 0.001015747 | 188 |
| flow_fixed-s101 | 624 | 60.090633709 | 0.090633709 | 491 |
| flow_fixed-s211 | 444 | 60.123881504 | 0.123881504 | 403 |
| flow_erlang4-s211 | 1,612 | 60.003332803 | 0.003332803 | 1,360 |
| snn-s211 | 6,298 | 60.002583394 | 0.002583394 | 4,371 |
| snn-s101 | 16,955 | 60.000431070 | 0.000431070 | 8,518 |
| flow-s101 | 319 | 60.103377949 | 0.103377949 | 287 |
| gru-s101 | 13,987 | 60.000690722 | 0.000690722 | 11,371 |
| transformer-s211 | 12,985 | 60.016546697 | 0.016546697 | 10,579 |
| flow_erlang4-s307 | 2,147 | 60.010224289 | 0.010224289 | 1,717 |
| cfc-s307 | 5,091 | 60.002803034 | 0.002803034 | 2,875 |
| gru-s211 | 13,106 | 60.001198591 | 0.001198591 | 11,627 |
| flow_mass-s307 | 356 | 60.049888209 | 0.049888209 | 300 |
| gate-s211 | 17,119 | 60.001047743 | 0.001047743 | 13,659 |
| gate-s307 | 7,645 | 60.217777246 | 0.217777246 | 7,382 |

All training child CPU cost: **1874.611680 seconds**. Sum of training child wall durations: **1995.212336 seconds**. The latter is not campaign elapsed time because children overlap. Evaluation and independent reader costs are outside these training-only totals.
