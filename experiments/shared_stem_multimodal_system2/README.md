# Shared Stem, multimodal differentiation and NDU System 2 ablation

This directory provides a model-free measurement boundary for experiments 3
and 4 in the shared-Encoder/Cell-Head program. The external executor owns
training and inference. It writes one JSON object per observation to JSONL;
`runner.py` validates the frozen plan, keeps failed/abstained attempts in the
denominator, and emits a digest-bound receipt.

The multimodal plan has six preregistered paths: text→text, image→text,
audio→text, video→text, text→image and text→audio. The NDU plan has five
arms: no System 2, replay only, routing, split proposal and full resource
allocation. Both plans require the holdout split, paired `example_id`, the same
Stem/seed/objective/dataset metadata, task utility, active FLOPs, latency,
memory, retention and old-task regression. Each row also binds model,
preprocessor and Head digests. Multimodal rows additionally carry an
independently measured single-modality baseline with its own status, artifact
digests and paired metrics, so baseline deltas are not imputed when missing.
Objective, Stem, dataset, host-profile,
measurement-interval and seed digests must be identical across all rows; this
prevents accidentally pooling different Stems, objectives, datasets, hosts or
seeds. Cell count and training budget are also fixed across the complete run.
All arms must contain the same holdout `example_id` set; mismatches are
retained as `unpaired_evaluation_set`. The runner reports p50/p95/p99 latency
and utility per active FLOP; it does not choose a winner.
Artifact and baseline digest drift is a diagnostic blocker. Failed, abstained
and unavailable rows remain in the survivorship denominator; utility per active
FLOP is explicitly labelled completed-row-only. NDU receipts use `no_system2`
as the fixed control and separately report paired external-task, resource and
old-task regression deltas for every other arm.
Rows over the preregistered FLOP, latency or memory ceilings are retained and
reported as `resource_budget_exceeded`; they cannot produce a complete
diagnostic disposition.
When supplied by an executor, negative transfer, new-Cell incremental cost,
calibration error and OOD false-acceptance are summarized with explicit
coverage counts; missing optional metrics are never imputed as zero.

```bash
python3 experiments/shared_stem_multimodal_system2/runner.py \
  validate-config experiments/shared_stem_multimodal_system2/config/multimodal_differentiation.v1.json

python3 experiments/shared_stem_multimodal_system2/runner.py run CONFIG.json OBSERVATIONS.jsonl RECEIPT.json
python3 experiments/shared_stem_multimodal_system2/runner.py verify CONFIG.json OBSERVATIONS.jsonl RECEIPT.json
```

Completed receipts are diagnostic evidence only. `authority_delta` is always
`none`; production acceptance, artifact selection, training authority and
semantic human judgement remain false.
