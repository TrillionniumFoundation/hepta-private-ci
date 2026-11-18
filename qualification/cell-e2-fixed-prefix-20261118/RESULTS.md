# E2 same-prefix mechanism diagnostic: complete 33 calls

The verified-credit update preserves five of five previously successful A histories; the equally trained all-observed control and retained parent preserve two of five. Both updated models recover five of the same six failed histories, compared with two for the parent. This is a descriptive diagnostic on exposed A training histories. The original 108-call advancement gate remains false and research **NoUpdate remains selected**.

## Frozen execution and comparison

Execution source: `0d1e9d9e24f2f1d569585adb3a6203a9114f850d`. Protocol SHA-256: `b2894184e497663f52fc01cafe7b1d86e32c247248d339ded8b1ad75f62a5e1e`. The full 11 histories, per-prefix input token digests, model manifest digests, and one-call budget were published before execution. No new training occurred.

The prefixes are the earliest actual failed attempt for each of the six A tasks, followed by the earliest actual successful attempt where one existed. All three models see exactly the same tokens for each case. Colon has no invented success prefix. Historical actions are conditioning data; the 33 outputs in this run are actual new executions by the three frozen models.

| Frozen model | Recovery on common failed histories | Preservation on common successful histories | Calls | Input tokens | Output tokens |
|---|---:|---:|---:|---:|---:|
| NoUpdate parent 430f4051 | 2/6 | 2/5 | 11 | 5,828 | 1,065 |
| all_observed 0585075a | 5/6 | 2/5 | 11 | 5,828 | 980 |
| verified_credit 785bc1ce | 5/6 | 5/5 | 11 | 5,828 | 896 |

## Every paired case

P means the original behavior passed and all declared wrong-output controls were rejected; F retains the original strict failure.

| Common history | NoUpdate | all_observed | verified_credit |
|---|---:|---:|---:|
| A-counter/failure | P | P | P |
| A-mse/failure | P | P | P |
| A-readout-score/failure | F | P | P |
| A-clipped-metrics/failure | F | P | P |
| A-pair-map/failure | F | P | P |
| A-colon-repair/failure | F | F | F |
| A-counter/success | P | P | P |
| A-mse/success | P | P | P |
| A-readout-score/success | F | F | P |
| A-clipped-metrics/success | F | F | P |
| A-pair-map/success | F | F | P |

On the five repaired failure histories, the two updated models emit identical answer bytes. Their recovery difference on these fixed opportunities is zero. Credit's distinguishing result is successful preservation for readout-score, clipped-metrics, and pair-map after the exact same successful histories. The control still emits a malformed patch for readout-score and pair-map, and a semantically false additional assertion for clipped-metrics. All models fail colon; credit's colon output is format-rejected.

For all five tasks with both a failed and a successful history, credit emits identical answer bytes across those two histories. This is compatible with stable reuse of known successful A answers. It does not establish that credit learned general feedback interpretation or recovery on new tasks.

## Relation to the original 108 calls

The original natural trajectories had different numbers of recovery opportunities. The MSE trajectory changed from fail→pass to pass→pass, removing a first-step failure. That alone cannot be interpreted as weaker recovery. The original preregistration nevertheless required no decrease in the absolute A recovery count, and credit had one recovery versus the control's two. That gate is still false. This later fixed-denominator diagnostic does not rewrite it.

The separately frozen B2 evaluation remains six tasks: both updated models finished at 3/6. This diagnostic adds no independent tasks, new users, or evidence of unique credit generalization.

## Complete cost and validation record

All 33 original REQUEST/OUTPUT/VERIFICATION/RESULT bundles were rebound to the frozen cases and model identities. Strict pass flags were independently checked against the recorded original/control observations; no model or verifier was rerun by the collector.

There were 33 model calls, 33 verifier calls, 17,484 input tokens, 2,941 output tokens, no output-cap hits, seven format rejections, 26 business executions, and 117 observed subject calls. Three disjoint owned model stages used 317.708057 seconds of wall time and 318.477409 child CPU seconds. Their cold loads used 32.398611, 30.963588, and 31.600586 seconds inside those stage windows. Generation used 210.311265 seconds and verification 5.054335 seconds, also nested rather than additive. The earlier tokenizer-only preparation used another 10.141112 owned wall seconds and zero model/verifier calls. Energy, money, and full-system cost remain unknown.

The authoritative job `1a1ef5fa542-ffbe-4a4` and all three actual child waits exited zero without timeout. Original runtime exit/witness records are included. GPU ownership ended before the next Circuit experiment.

## Exact original artifacts

- [complete-originals.tar.gz](complete-originals.tar.gz): 127,208 bytes, SHA-256 `62ff592e727968b2e2df035d6b4a4bd2141037de6774d1e37a0407b08e507858`; 201 original files plus the index.
- [EVIDENCE_INDEX.json](EVIDENCE_INDEX.json): SHA-256 `f5a9cb70d0db4887eff1fd10ee0b3610e7bb2637fe5bc8f04f49095c4b7cfbac`.
- [READOUT.json](READOUT.json): SHA-256 `ec65db0622d391963edd3d3f5332a65ef6a6fd8697a4f2d582c49893505407be`; contains all 33 call bindings, paired outcomes, exact answer comparisons, costs, and runtime witnesses.
- The three manifest bytes are included. The two trained adapters are already retained in the prior complete 108-call archive, SHA-256 `95beda262721a747aeb3180b7d7f37a245735870b3ee0c8c58e80e45857b9bb6`; they are not duplicated or relabeled here.
- The postprocessor was separately published at `723d665e51869ba23f59ee747664210ffeb2a0f2`. The model execution remains attributed to source `0d1e9d9`.

Independent authenticated users = 0; new independent tasks = 0; native adoption = false; scientific confirmation = false. This result narrows the observed A mechanism while preserving every failure and the prior NoUpdate decision.
