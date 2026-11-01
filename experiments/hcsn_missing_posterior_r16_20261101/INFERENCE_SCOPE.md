# Missing content: exact scope and causal posterior

## Frozen model and observation contract

The baseline is `a793d55c23a7742378b081b162252da428a9fdb2`, PR #4548.
`BASELINE.json` records checked Git blob and SHA-256 identities. The unchanged
generator is `experiments/hcsn_four_stage_flow_20261031/synthetic_data.py`;
the 18 unchanged neural checkpoints are identified by the original
`results/retention001/ALL_CHECKPOINTS.json` and the two existing checkpoint
archive parts. New calibration is applied identically to Flow and Diagonal.

The observer receives public task identity, the raw prelude, and its boolean
observation mask. It receives no label, `target_available`, removed-write index,
latent state, future query or future acquisition. Query addresses and Binding
aliases are decoded from the publicly specified typed fields. This is an
explicit structural prior and an ordinary exact reference; it is not evidence
that the neural models learned missingness or semantic routing.

The current implementation admits the fixed base preludes and one erased WRITE.
Other schedules, erased bridge relations, multiple erasures, resampling and
long-token inputs are not covered by this new observer. Existing acceptance of
those schedules is not borrowed as acceptance of this new code.

## Exact posterior under the published without-replacement law

Four initial values are drawn without replacement from eight classes. Selective
then writes two distinct new values to two distinct addresses. Conditional on
observed WRITE values and addresses, all compatible latent assignments have
equal prior weight. Distractors do not constrain these assignments.

For MQAR and Binding, three observed initial values exclude three classes. The
missing address is identified by the other three addresses. Its missing value
is uniform over the five remaining classes. The conditional optimal top-one
accuracy is therefore 20%, not the marginal eight-class guess rate of 12.5%.
Binding's observed permutation changes query routing but not that posterior.

Selective has three distinct cases:

| Visible missing event | Posterior for final content |
| --- | --- |
| Initial WRITE, later overwritten | Final target is exactly observed in the later WRITE |
| Initial WRITE, not overwritten | Three observed initial values plus two new values exclude five classes; missing final value is uniform over the remaining three |
| One of the two final overwrites | All four initial values and the other new value are known; hidden overwrite address is uniform among the other three addresses and its value is uniform among three unseen classes |

In the last case, for each candidate address the original value retains
probability `2/3`, while each of the three unseen values has probability `1/9`.
The Bayes classifier therefore predicts the original value. It is always wrong
on the *actual hidden overwritten address*, even though it minimizes average
error given the public prefix. An evaluator's `target_available == false`
subset identifies that hidden address. Conditioning only a score on this
unobserved subset can make a calibrated classifier look worse than a uniformly
random answer; it is not a calibration criterion available to the model.

The observer retains the corresponding joint candidate worlds, not four
independent guesses. An actual acquired raw WRITE selects all and only worlds
whose missing event has the observed address and value. All final contents
then become known. The READ value is the expected gain in mean four-query
correctness before seeing that event. In the registered delayed-READ task,
an unknown initial target has gain `1/6` in Selective and `1/5` in MQAR/Binding;
a missing Selective overwrite has gain `1/4`. Original missing-stress cases
whose erased old WRITE is superseded have gain zero.

## Independent checks and calibration

The independent checker enumerates all ordered value assignments, and all
ordered pairs of overwrite addresses in Selective, filters them by the raw
observations, and computes final-content frequencies. It does not call the
closed-form posterior constructor to generate its reference.

Calibration accepts normalized FP64 probabilities and replaces a distribution only when the public-prefix
posterior is uncertain. Already determined targets retain their original neural
probabilities byte for byte. Consequently existing neural errors on a fully
known target would remain visible; this is not an oracle that repairs every
answer from evaluation labels. The same prior and operation apply to both cores.

Proper scores are reported over all query targets. Abstention uses a fixed
0.9 maximum-probability threshold, with coverage shown alongside correctness.
Hidden-unavailable subsets remain useful diagnostics but do not supply actions,
probabilities or acceptance thresholds.

## Evidence separation

`results_dev_01` replays an already opened confirmation namespace; its original
new-source bytes are preserved under `source_snapshot`. Its 18 old
accuracy outcomes were reproduced exactly. Its corrected scores are development
results. The separate `CONFIRMATION_PROTOCOL.json` freezes new stream IDs,
unchanged checkpoints, inference source, 12 simultaneous proper-score tests,
18 episode-based reliability tests, independent-reference checks and real READ
successors. It must be published and read back before any new stream is opened.

Any later successful confirmation qualifies this shared finite-profile
calibration repair. It cannot establish positive D−B, training-seed population
generalization, an unknown-world Bayes observer, audiovisual capability, GPU
speed, energy savings or a production neuron replacement.
