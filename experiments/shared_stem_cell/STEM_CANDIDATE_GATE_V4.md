# V4: independent matched-candidate readout (research only)

This increment is intentionally **not** a classifier trainer, pretrained checkpoint
loader, evaluator of agent quality, NDU owner, or production model selector. It
adds a fail-closed readout contract at the boundary between separately trained
frozen stem candidates and an independently retained future-label cohort.

## Required order and ownership

1. **Operator:** freeze a canonical JSON plan before train/predict execution.
   Pin training data, a source-only future cohort, future-label file SHA-256,
   sorted training group hashes, train/future time boundaries, device,
   environment, seed, fixed Cell Head parameter count and training steps.
   Register exactly one `no_change` baseline and at least one alternative.
   Profile and checkpoint digests are byte identities, **not provenance**.
2. **Training and inference executors:** train only using the frozen train set;
   execute each candidate over the same future source-only records and preserve
   one pinned candidate-result document. The baseline has zero training steps
   and zero new Head parameters. All alternatives must have the same Head budget
   and training steps, same seed, input cohort, hardware and environment.
3. **Independent readout:** read the frozen plan, labels and *all* candidate
   result documents by their literal SHA-256 pins. Reject missing/extra/duplicate
   candidate arms, time/group/scope/identity drift, train label contamination,
   malformed probabilities, missing forward counters, and missing model-material
   and resource declarations. Compare accuracy, Brier, log loss, ten-bin ECE,
   newly introduced errors and rescued errors against `no_change`.
4. **External authorities:** authenticate actual pretrained publisher/weights,
   real execution and physical resource witnesses, calibrate OOD, independently
   observe future NDU and negative transfer. Until these gates pass,
   **`winner: null` and `production_accepted: false` are invariant**.

Candidate execution receipts in this research contract are still *caller
supplied*. `checkpoint_locally_verified=true` is necessary but not a signed
independent witness; `publisher_authenticated=true` asserted by the caller
cannot grant authority. Reported energy is null unless actually measured.
Future-label files must remain inaccessible to the train/inference executor.

## Important limitations

- Unit fixtures have invented classification predictions and deterministic
  scores; they are **not** evidence of mmBERT, Granite or Laya quality.
- This readout operates on output probabilities. The existing V2 multimodal
  linear Bridge evaluates geometry separately. Neither is a calibrated neural
  utility or proof that a Cell should physically split.
- The schema holds a declared no-change baseline; its independently frozen
  model-state witness, exact selected-artifact truth, NDU observations and
  production final-use authorization remain external integration work.
- Counts and runtime metrics must be collected from target hardware; raw
  serialized claims are not actual RSS/p95/p99 evidence.

Run the dependency-light protocol checks without any HF weight downloads:

```sh
PYTHONPATH=experiments/shared_stem_cell python3 -m unittest discover \
  -s experiments/shared_stem_cell -p test_multimodal_candidate_gate.py -v
```

Call `multimodal_candidate_gate.py --help` for its isolated readout CLI. Do not
feed it candidate result files from unreviewed or untrusted producers and do not
re-interpret any scoring advantage as permission to activate a new Cell.
