# Masked external-span execution

This is a new opt-in execution profile over the inherited source-pinned SQuAD,
paired encoder, small residual head, and matched generator. It does not replace
production serving or rewrite the already completed listwise experiment.

## Why another profile

The inherited `external spans and matched generator` run at `2fb0488f` executes
real pretrained models but optimizes a softmax over all windows and the null head.
A missing external answer span is not certified negative window supervision.
The new `external-span-masked-evidence-only-v1` profile instead uses positive,
negative and unknown states. Only complete reference-span coverage supplies a
positive; only the human-unanswerable paragraph supplies negative windows. All
other windows are unknown and receive no loss. A missed answer span stays a
coverage omission, not an unanswerability label.

The 16-unit evidence residual optimizes 6,177 parameters. The entire paired
encoder and the 385 null-head parameters stay unchanged. Binary logistic loss
uses only observed window labels and is balanced by source family. Unknown
windows cannot affect gradients through the null mean or through normalization.
This is reference-span training, not an independent semantic entailment review.

The six existing same-generator arms remain identical in their candidate pools,
features, generator identity, prompt template and decoding budgets. Forced-choice
frozen/trained pairs are the primary sorting contrast. Fixed-zero-offset pairs
and selection-calibrated pairs expose decision and calibration effects. A fixed
null head still permits acceptance changes when evidence scores move; this is not
claimed as improved ranking. SQuAD evaluation and the two native transfers perform
no parameter updates or native recalibration after immutable head reload.

## Locked execution, not fixture inference

`hepta-memory-masked-span.yml` uses the complete package-version freeze from the
observed run `37919555733`, compares pip-freeze output exactly, and checks original
SQuAD bytes plus full ranker and generator inventories against that run. The
execution step launches a separate Python process with actual pretrained tensors,
not unit-test loader substitutes. Inference/optimization is offline after staging.
Package versions and model/data bytes are pinned; different hosts, Python builds
or CPU scheduling are not asserted bit-identical hardware environments.

The planned questions are unchanged: 128 external training, 32 selection, 16
external evaluation, eight LoCoMo and eight LongMemEval transfer questions. All
six arms are retained. These are bounded, previously exposed developmental data,
not a complete benchmark or new prospective performance claim. No hyperparameter,
threshold grid or question selection is tuned to the new test output.

Raw answer groups are synced to an append-only journal before score annotations
are read, including selector-abstention cases, which still invoke the same
model with empty evidence. No quote or citation is appended after generation.

`masked_span_audit.py` rechecks the complete plan/arm census, unchanged raw and
scored records, exact original window bytes, identical generator inputs, recorded
decisions, frozen null tensors and the paired report calculations. Its output is
an execution-consistency check by this implementation, not independent acceptance,
proof of dataset-pretraining separation, or >=99% semantic citation precision.

```sh
python3 -m unittest discover -s scripts/memory_cell -p 'test_*.py' -v
HEPTA_MEMORY_TESTED_COMMIT="$(git rev-parse HEAD)" \
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  python3 scripts/memory_cell/selector_end_to_end.py STAGED RANKER EXTERNAL NEW_OUTPUT \
    --training-profile external-span-masked-evidence-only-v1
python3 scripts/memory_cell/masked_span_audit.py NEW_OUTPUT "$(git rev-parse HEAD)"
```

The legacy default profile remains available for old-source reproduction. Required
repository checks remain unwaived. Never label a failed partial run as a complete
experiment or consider a test key, empty citation denominator, old snapshot, or
zero-update replay an independent production qualification.
