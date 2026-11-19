# Source-grounded model development and owner observation

This continuation adds opt-in model training/decoding experiments and a read-only
Supervisor observation client. It does not activate a production model, change
old benchmark answers, issue independent signatures, or replace HNMF qualification.

## Model paths

`GroundedReader` reuses the pinned pretrained reader and its rank-4 LoRA. A new
source-derived objective masks every prompt token from the loss and supervises
only the exact source quotation plus its label (or an unsupported-cue abstention).
It never receives a benchmark target or the evaluation question as its training
prompt. Repeated updates preserve the union of all prior source roots. Nonfinite
updates quarantine the candidate. The development driver resets, trains, saves
and validates an immutable reload before evaluating an adapter.

The `span` decoder uses `prefix_allowed_tokens_fn` during token generation. Its
finite trie admits only complete, round-tripping source quotations with generated
labels or the exact abstention string. It rejects truncated/nonterminal output;
there is no post-generation citation insertion or response rewrite. Free decoding
uses the same prompt and output token ceiling. The receipt retains prompt/output
identities, exact delivered excerpts, UTF-8 source offsets, omitted input bytes,
and excluded overlong/unrepresentable choices.

**Copy validity is not answer relevance, source truth, completeness or semantic
entailment.** The decoder can select a greeting, question, stale statement or list
number correctly copied from memory while failing the user's task. Such an output
must not be advertised as 99% citation precision. Abstention is not perfect
precision, and the protocol does not certify its own relevance or acceptance.

The preregistered DEVELOPMENT comparison has five arms: frozen free/span,
raw-history LoRA span, and source-supervised LoRA free/span. All share the pinned
reader/encoder, rank, retrieval view and visible source bytes. Input ceiling is
1,024 tokens, generation ceiling 96; adaptation has at most 32 steps and 6,144
training tokens. The source objective uses longer examples and may complete fewer
steps. Actual token counts, wall time and optimizer storage are reported; equal
ceilings are not equal FLOPs or actual lifecycle cost. The original native run's
32-token generation protocol is unchanged and is not a matched comparison here.

The current driver uses four deterministically selected questions from each
previously exposed public dataset. This is neither full benchmark execution nor
fresh untouched holdout evidence. Answer annotations are consulted only after
all model runs, solely for diagnostic token F1. Missing/unscored outcomes remain
explicit. The full historical benchmark evidence and negative results remain
unchanged. New experiments need their own preregistration and independent tasks.

```sh
python3 -m unittest discover -s scripts/memory_cell -p 'test_*.py' -v
HEPTA_MEMORY_TESTED_COMMIT=$(git rev-parse HEAD) \
  python scripts/memory_cell/grounded_development.py \
  /path/to/pinned-inputs /new/development-output longmemeval --count 4
```

Run with the pinned worker requirements and offline reader/encoder files, as in
`.github/workflows/hepta-memory-grounded-development.yml`. The native model jobs
are separate from grammar/one-parameter fixture tests. Never substitute those
fixtures for measured pretrained behavior.

## Owner-local observation

`SupervisordClient::observe_current` uses only existing health, snapshot,
release-selection and production-mutation-status RPCs. Eight reads bracket the
same expected control fence and current daemon epoch. A changed bracket, wrong
expectation, cancellation, backward clock or ten-second overall timeout fails.
It performs no start/stop/upgrade/rollback or recovery decision.

The CLI can run locally on each explicitly authorized host:

```sh
cd codex-rs
cargo run -p codex-hepta-supervisor --example observe_memory_owner -- \
  /absolute/owner/supervisord.sock \
  /absolute/current-expected-fence.json \
  /absolute/new-observation.json
```

Use the owner's protected socket and an independently obtained current expected
fence. Output is create-only, bounded, synced and owner-private on Unix. Preserve
the complete output bytes and printed SHA-256, not a paraphrased status. A failed
write is not a completed receipt. Run/copy only through the operator's authorized
host path; no credentials, host names, signing keys or remote authority are
inferred by this client.

Equal read brackets are **not an atomic snapshot**, cannot exclude an intervening
ABA change, do not authenticate wall-clock time or remote-host independence, and
cannot prove model revocation or disaster recovery. All acceptance/independence
flags remain false. Existing independent evaluators must bind the exact bytes to
actual host identity, current trust, source/fleet frontiers and registered
observation windows. The signed production-mutation state, when present, is
transported unchanged; collecting it does not independently validate its grant.

The test suite uses explicit protocol peers plus the actual supervisord binary
in a temporary local fleet. It kills/restarts that daemon and rejects the previous
epoch. This is product integration coverage, not cross-host partition, deployed
selected-LoRA cutover/rollback, three independent snapshots or two future windows.
Those acceptance requirements and default production activation remain unchanged.
