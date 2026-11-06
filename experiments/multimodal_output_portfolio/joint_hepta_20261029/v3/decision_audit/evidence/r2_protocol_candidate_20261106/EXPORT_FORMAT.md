# Evaluator export and execution handoff

The normal analysis entry point is:

```bash
python analyze_capture.py \
  --bundle /absolute/independent-owner/export.json \
  --design-sha256 ACTUAL_PRE_OUTCOME_DESIGN_DIGEST \
  --capture-sha256 ACTUAL_POST_RUN_CAPTURE_DIGEST \
  --output /absolute/new/arithmetic-report.json
```

The two digests must come from the separately retained owner receipts. Computing
them from an altered input in the same command is not independent custody.
This command does no training, evaluation, model loading, or promotion. It
rejects explicitly synthetic bundles and never reports `confirmation=true`.

## Required export objects

`design` has schema `hepta.r2.panel-design.v1`, the canonical protocol digest,
the fixed 32 `fit_seeds`, `draws=[0,1]`, the exact ordered seven methods, unique
source-cluster IDs, the validation-selected strong reference, and exact hashes
for test seal, custody receipt, candidate manifest, validation selection and
tariff manifest. Failure utilities are -1 and abstention 0 in this candidate.
`budget_estimand` is `same_total_budget`. These are placeholders until the six
real gates close; the current package does not contain an actual design export.

`tariff_manifest` contains `cpu_second=0.02`, `wall_second=0.001` and an explicit
finite nonnegative `services` mapping. Every physical event names a key and
number of service units. Unknown or unmapped real actions are rejected.

`capture` has schema `hepta.r2.capture.v1`, the design digest, a complete episode
roster and `outer_event_ids`. Each episode records an ID, fit seed, source
cluster, draw, method and its unique event IDs. It must contain the entire
Cartesian panel, including failed/cancelled fits. `payload_sha256` hashes the
canonical object containing unique events sorted by ID and outcomes sorted by
ID. Exact duplicate physical receipts are deduplicated before this hash;
conflicting duplicates reject. The capture itself is independently pinned by
the caller's capture digest.

Each `events` record has `id`, `episode_id` or null, scope, terminal status,
boolean `selected`, `metering="exclusive"`, cost unit, CPU/wall seconds,
service key/units/fee and total declared cost. Episode cost categories are
encoder/generation/planner/critic/verification/seal, with explicit justified
`not_run` records where appropriate. No-run records have exactly zero physical
cost. Outer scopes setup/training/analysis/publication must all be present;
training has a record for each fit/arm, including explicit 00 no-training.

`raw_measurements` always contains peak_rss_bytes, retained_disk_bytes,
network_payload_bytes and energy_joules. A missing measurement is null and its
name must be in `unknown_raw_costs`; it is never silently zero. Such unknowns
are reported and prohibit a full-cost qualification claim. Parent inclusive
wall envelopes belong in separately retained observations, not additive leaves.

Every `outcomes` row binds an episode ID, exact terminal status, independent
utility and sealed cost. Completed outcomes require the independent label
receipt digest. The checker verifies the costs against captured leaves and
keeps failures at the preregistered utility. It does not interpret a label hash
as proof that a human or independent evaluator actually supplied that label.

## Training and candidate manifest still required

Before any confirmatory dispatch, an actual implementation must supply:

- full source SHA/tree, environment and hardware identity;
- fit seed, arm, training callable and all optimizer/hyperparameter values;
- identical starting pretrained manifests and paired 10/11 initialization;
- explicit trainable/frozen parameter names and actual before/after hashes;
- executed gradients/updates or an explicit failure/no-training terminal;
- every selected, unselected, failed and intermediate checkpoint;
- complete search/training/validation costs and budget consumption;
- exact new-process loading of the selected checkpoint and frozen index;
- reference-policy implementations, predicted-vs-observed trace types, and
  actual validation selection with all rejected configurations retained.

None of those entries may be filled with the historical small synthetic
`JointGenerator`, a base-model self-critique, an arbitrary mock checkpoint,
or the already exposed acquisition canaries. The old inference adapter rejects
changed base weight hashes; a reviewed research candidate loader is a real
dependency, not an invitation to weaken that check.
