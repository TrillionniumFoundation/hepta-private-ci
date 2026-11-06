# Source-only decoder-versus-adapter factorial

The pinned source-writing run (source `6df724aeb`, Actions run `38161559498`)
completed all 128 optimizer updates and 56 actual seven-arm task reads, despite
the independent repository formatting job failing. Its same-evidence knowledge
contrast was 8/8 vs 8/8, and the parameter-only contrast 0/8 vs 0/8.
Source-derived in-sample recall was 0/16 for both reader arms. Teacher-forced
correct-answer mean NLL decreased for every one of eight scheduled source scopes,
but same-entity/attribute confusion was not reliably corrected.

`source_decode_factorial.py` is a **new research diagnostic**, not a replay
that claims new answers already exist. It generates actual answers with an
identical frozen Qwen2.5-3B base, the same persisted adapter, source-only
questions and exactly empty evidence. Greedy and beam-2 differ ONLY in decoder
search; within each decoder, base and memory differ ONLY in adapter mode. The
source-derived question set and answer digests are committed before inference.
Both per-decoder raw answer journals precede offline scoring. Failures stay in
planned denominators and interaction outcomes are not imputed.

Beam-2 uses the same 64-token output cap and chat prompt. It takes more CPU,
so no equal-cost conclusion is possible without measured runtime and aggregate
lifecycle accounting. This is not a secret candidate-answer list: no candidate
strings or targets are passed to either generator. Even a beam improvement
would establish only a decoder improvement on exposed training-source facts,
not independent transfer, semantic citations or production qualification.

The stand-alone bounded command uses the original already committed source
snapshot, pinned research reader and exact source/READY hashes:

```sh
HEPTA_MEMORY_TESTED_COMMIT=EXACT_SHA python3 scripts/memory_cell/source_decode_factorial.py \
  SOURCES.json STAGED_MODEL SNAPSHOT OUTDIR \
  --source-sha SOURCE_SHA --stage-sha STAGE_SHA \
  --ready-sha READY_SHA --source-commit EXACT_SHA --maximum 8
```

The CLI verifies snapshot/source/model identity and full immutable source
lineage, loads the frozen adapter, and retains separate raw journals. The
separate scoped workflow tests contracts only, not actual pretrained
generation. It does not enable the candidate, modify runtime owners, or
substitute for future independent test families or >=99% citation review.
