# Retrieval calibration and paired ablation contract

Status: source tooling for offline candidate-policy generation. This contract does **not**
create a production retrieval policy, enable Vector, prove causal utility, qualify a target
host, activate a rollout, or replace the native nine-stage Agentd measurement producer.
Read it with `POLICY_REFERENCE.md`, `E2E_MEASUREMENT.md`, `ROLLOUT_POLICY.md`,
`OWNER_PROPOSITIONS.md` and `THREAT_MODEL.md`.

## 1. Purpose and claim boundary

`scripts/hepta_memory_retrieval_calibration.py` turns an exact-source, future-held-out,
paired comparison dataset into a content-addressed **candidate** calibration receipt. It:

- selects score/OOD/channel thresholds using only the `calibration` partition;
- evaluates the selected thresholds once on a strictly later `holdout` partition;
- reports aggregate and per-risk-stratum false accepts, harmful accepts and false
  abstentions with ceiling-parts-per-million arithmetic;
- compares the fixed lexical, owner-RRF, no-recurrence, no-inhibition and full-HNMF
  systems on identical query groups;
- binds every system configuration, annotation protocol, policy, dataset, Git commit and
  Git tree;
- rejects Vector in both policy and data until a separately qualified current text
  encoder and durable generation-bound vector-index publisher exist.

The receipt fixes all of these claims to `false`:

- `causalUtilityProved`;
- `productionPolicyApproved`;
- `productionImplementation`;
- `productExecutionProved`;
- `independentAcceptance`;
- `activation`;
- `release`.

A generated candidate may still be unsuitable. It must not be copied into a signed
retrieval publication merely because the tool exits successfully.

## 2. Required paired systems

Every query group contains exactly one row for every declared system. The policy must
include at least these standard identities:

1. `lexical`;
2. `owner_rrf`;
3. `hnmf_no_recurrence`;
4. `hnmf_no_inhibition`;
5. `hnmf_full`.

The exact implementation/configuration of each system is bound by a SHA-256 value in
`system_configuration_digests`. The names do not prove that the implementation actually
matches the intended ablation; retain build receipts, executable identity and raw
experiment traces for independent review.

A query group cannot disappear from one system, because dropping difficult groups would
make the comparison incomparable. Query metadata and the query-level target label must be
identical across all five rows. Output correctness and harmfulness remain system-specific.

## 3. Dataset contract

The input schema is `hepta.memory-retrieval.calibration-input.v1`. Its exact top-level
fields are:

| Field | Requirement |
| --- | --- |
| `source_head`, `source_tree` | Exact lowercase Git commit/tree observed from a clean checkout |
| `dataset_id` | Stable bounded identifier |
| `policy_sha256` | SHA-256 of canonical policy JSON; the dataset cannot be reused with another threshold search |
| `annotation_protocol_digest` | Digest of the frozen labeling instructions and adjudication procedure |
| `vector_channel_enabled` | Must be `false` |
| `system_configuration_digests` | Exact map for every required paired system |
| `rows` | Bounded nonempty array, at most 5,000,000 rows |

Each row contains exactly:

```text
sample_id
query_group
query_digest
partition
risk_stratum
system
event_time_micros
target_should_recall
selected
output_correct
output_harmful
source_current
score_q32
ood_q32
distinct_channels
contradiction
```

`score_q32` and `ood_q32` are raw unsigned Q32 values in `0..=4294967296`.
`distinct_channels` is `0..=8`. Booleans cannot be replaced by integers. An unselected
result cannot claim correctness or harmfulness. A harmful output cannot also be labeled
correct. A correct recall requires `target_should_recall=true`.

`source_current=false` and `contradiction=true` remain independent final-use gates. The
threshold search cannot learn to accept stale or contradictory material.

### Future-event separation

Partitions are only `calibration` and `holdout`. Every holdout event timestamp must be
strictly later than every calibration timestamp. A query digest cannot appear in both
partitions. This is stronger than a random row split and prevents the same normalized
query from leaking across the boundary.

Every declared risk stratum must contain at least 100 complete paired query groups in
each partition. Policies may require a larger minimum. The tool applies acceptance limits
to both the aggregate and every stratum separately; a low aggregate rate cannot hide a
high-risk-stratum regression.

## 4. Policy contract

The policy schema is `hepta.memory-retrieval.calibration-policy.v1`. It declares:

- `policy_id`;
- `baseline_system`;
- `required_systems`;
- `risk_strata`;
- `minimum_groups_per_partition_stratum`;
- `vector_channel_enabled=false`;
- a bounded grid of `minimum_total_score_q32`, `maximum_ood_q32` and
  `minimum_distinct_channels`;
- limits for:
  - `false_accept_ppm_of_groups`;
  - `harmful_accept_ppm_of_groups`;
  - `false_abstain_ppm_of_positive_groups`.

The Cartesian grid is capped at 4096 policies. Contradiction abstention is always enabled
and is not a calibration knob. Policies are feasible only when all three limits hold for
the aggregate and for every risk stratum.

Among feasible calibration-partition policies, deterministic selection maximizes correct
accepts, then minimizes harmful accepts, false accepts and false abstentions. Remaining
ties prefer a higher score floor, lower OOD ceiling and larger channel minimum. Holdout
outcomes are not consulted during selection.

If no feasible candidate exists, the receipt status is `no_feasible_candidate`; the
corresponding system has no selected policy and no holdout evaluation. Relaxing a limit
requires another independently approved policy document, not an automatic fallback.

## 5. Metrics and interpretation

For one system/policy:

- **accepted** requires the system to have selected an output, current source support,
  positive score, score at or above the floor, OOD at or below the ceiling, sufficient
  distinct channels and no contradiction;
- **correct accept** is an accepted output labeled correct;
- **false accept** is an accepted output not labeled correct;
- **harmful accept** is an accepted output labeled harmful;
- **false abstain** is a positive query group without a correct accepted output.

Rates use ceiling ppm. For example, one event in 101 groups is 9901 ppm, not 9900.
False-abstain ppm uses positive query groups as its denominator; other reported rates use
all query groups.

`descriptive_delta_from_baseline` subtracts the baseline holdout rate from each system's
holdout rate. It is descriptive, not a randomized causal estimate. Shared sources,
deterministic treatment assignment and downstream selection can invalidate naive causal
interpretations.

## 6. Reproducible invocation

Run from a clean checkout detached at the exact candidate:

```sh
python3 scripts/hepta_memory_retrieval_calibration.py \
  --root "$CHECKOUT" \
  --head "$SOURCE_HEAD" \
  --dataset "$RAW_PAIRED_DATASET" \
  --policy "$PREAPPROVED_CALIBRATION_POLICY" \
  --output-dir "$CONTENT_ADDRESSED_RECEIPTS"
```

The tool observes the Git commit, tree and ordered parents before calibration and again
before publication. It refuses dirty tracked or untracked state, duplicate JSON keys,
non-finite values, wrong source identity, policy drift, incomplete paired groups,
cross-partition query reuse, insufficient evidence, vector enablement and malformed
labels.

The output path is the SHA-256 of canonical receipt JSON and is created exclusively,
flushed and directory-synced. This local retention is not external immutable/WORM
governance.

## 7. Qualification sequence

Before a candidate threshold can enter a signed context publication:

1. execute this tool on independently retained raw paired data and a preapproved policy;
2. review all holdout and per-stratum results, including failed and abstained queries;
3. execute the real native nine-stage Agentd producer on the exact binary and target host;
4. verify current proposition-owner semantics, source revalidation and delivery receipts;
5. run bounded shadow with CPU/RSS/allocation/wall-time isolation and cancellation;
6. obtain independent semantic, security, operator and release approval;
7. publish a new signed policy generation and rehearse rollback.

The calibration receipt alone satisfies none of steps 3–7.
