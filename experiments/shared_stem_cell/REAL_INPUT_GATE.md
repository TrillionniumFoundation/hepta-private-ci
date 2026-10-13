# Real-input gate

The runners and receipts are ready, but the cloud workspace does not contain
the inputs required for a real capability claim. Synthetic reports remain
diagnostic fixtures and cannot be promoted to model results.

Required before running the real matrix:

- reviewed 421M Stem artifact and its SHA-256 digest;
- fixed Reader artifact, prompt/preprocessor digest and evaluator identity;
- versioned task/holdout JSONL with labels sealed outside the executor;
- modality codecs for image, audio and video, each with a digest;
- independent outcome evaluator and NDU evaluator identities;
- target-host p50/p95/p99, active FLOP, RSS/GPU memory and energy counters;
- split trace containing parent state, migration, retained-task result,
  independent evaluation, canary and rollback evidence.

The first admissible real run must populate external JSONL observations for
every registered arm, bind all context and artifact digests, and produce a
receipt with no missing or unpaired holdout rows. Missing inputs produce
`insufficient_evidence`; they do not produce a winner.
