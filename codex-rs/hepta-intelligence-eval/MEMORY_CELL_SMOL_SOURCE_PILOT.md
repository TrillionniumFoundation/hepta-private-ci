# Small-reader source-written memory pilot

The pinned `HuggingFaceTB/SmolLM2-135M-Instruct` model at
`12fd25f77366fa6b3b4b768ec3050bf629380bac` is an independent
reader-capacity diagnostic, NOT an interchangeable Qwen2.5-3B replacement.
It is the reader already pinned in the historical native benchmark.

`.github/workflows/hepta-memory-smol-source-pilot.yml` executes
the unchanged controlled event corpus and the same seven source-before-task
arms: hybrid, deterministic organizer, organized+knowledge adapter,
parameter-only, empty, initial policy and learned policy.

Use the original full completion loss, not the Qwen2-only sparse-position
backend. Keep the 128-update / 65,536-input-token limits, all source, model
and task byte pins, raw answer records, procedural worker checks, artifact
hashes and final full-regression/formatting gates. A distinct SHA-based
concurrency key prevents interference with the expensive 3B experiment.

The Qwen-only teacher-forced scoring procedure is inapplicable to this
tier; `source-likelihood-status.json` records that fact as unavailable,
not zero. All within-tier causal comparisons use the same 135M model.
Results must NOT be compared with 3B outcomes as a MemoryCell effect.
The authored development corpus is neither independent future evidence
nor a certified natural-language task set.

This diagnostic does not establish stronger-than-RAG performance, a
successful parameter-memory write, full lifecycle cost, any >=99% claim
entailment, or production qualification. Retain `production_accepted=false`
and the existing Rust owner, revocation, review and rollback gates.
