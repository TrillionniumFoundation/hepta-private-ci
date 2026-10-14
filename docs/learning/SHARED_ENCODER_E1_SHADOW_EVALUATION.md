# Shared Encoder E1 shadow evaluation — research only

This is a **read-only, retrospective, non-authoritative** comparison of a
candidate Encoder/Head against the **independently frozen no-change**
predictions on the same held-out case IDs. No model weights are downloaded or
executed by this evaluator; it does not certify NDU or select/publish a model.

## CLI

```sh
python3 scripts/hepta-shared-encoder-e1-eval.py \
  --dataset cohort.jsonl \
  --no-change baseline-predictions.jsonl \
  --candidate candidate-predictions.jsonl \
  --scope real-scope-id --task real-task-id \
  --train-cutoff 2026-10-14T00:00:00Z \
  --bootstrap-rounds 500 \
  --out e1-shadow-evidence.json
python3 -m unittest discover -s scripts/tests -p 'test_hepta_shared_encoder_e1_eval.py' -v
```

The output uses exclusive creation (no overwrite) and always marks:
`RETROSPECTIVE_SHADOW_EVIDENCE_INCOMPLETE`, `DENY_ALL`,
`production_promotion_permitted=false`, `winner_selected=false`,
`independent_ndu_verified=false`. No stdout summary is an independent
performance, utility or resource receipt.

## Input contracts

**Dataset JSONL**: one object per case:
`case_id`, `scope_id`, `task_id`, `split` (`train`,
`calibration`, `test`, `future`, `old`, `ood`), `group_id`,
`event_time` and `label_available_at` (canonical UTC ISO timestamps),
`label` (binary 0/1).

**Both prediction JSONL streams**: exactly one row for each held-out
`future`, `old` and `ood` case belonging to the requested Scope/task.
Each prediction must contain `case_id`, `scope_id`, `task_id`, `split`,
`abstain=false`, `probability_positive` in [0,1],
`prediction_committed_at`, `encoder_digest`, `head_digest`,
`weights_digest` (64 lower-case hex), `model_revision` (40 lower-case
hex), `runtime_generation` positive, `execution_receipt_id` nonempty,
`latency_micros`, `resident_bytes`, `transient_bytes` nonnegative.
These fields are **unverified assertions** until their owners independently
authenticate the artifacts and signed execution receipts.

Any duplicate, extra, missing or mixed-revision case, malformed numeric
value, split/Scope mismatch, feature-budget override, contaminated train
group, or prediction at/after the declared label availability time rejects
the run. At least two independent `future` groups are required for the
deterministic group-bootstrap interval. This simple binary/no-abstention
evaluation is deliberately not a general NDU protocol.

## Interpretation

- Positive `paired_brier_improvement` = lower candidate Brier loss
  than no-change, on exactly the same declared future cases.
- `bootstrap_ci_lower/upper` are **descriptive** group-bootstrap
  intervals, not an authorized release criterion.
- `negative_transfer_old_tasks` = candidate minus no-change Brier
  loss on `old` cases; positive indicates regression.
- CPU/GPU/RSS and model-call latency have not been authenticated just because
  prediction rows include resource numbers.
- Validated timestamps in JSONL do not prove predictions were sealed
  before labels became available. The NDU Evaluator must get externally
  witnessed predictions, chronology and outcome events.

## Remaining hard gates

1. Actual target host E0: verified executing model/weight/tokenizer,
   signature/owner provenance, RAM/GPU/CPU and warm/cold measured receipts.
2. Pin and independently authenticate exact model weights; never load
   untrusted pickle, floating revisions or arbitrary remote code.
3. Execute mmBERT-small and Granite 97M R2 under the same dataset,
   Head parameters, total compute, sequence/truncation profile and seeds.
4. Compute the independent utility, calibration, OOD errors, tail latency,
   resource costs and negative transfer in a future frozen window.
5. Only independent Evaluator → Selector → Executor may permit a separately
   authorized artifact CAS / generation fence / migration / route cutover.

**No test fixture or unverified JSONL is evidence that E1 has passed.**
