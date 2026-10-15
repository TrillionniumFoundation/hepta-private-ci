# P0 V12 — physical Runner stage receipts without weakening scientific gates

**Research / Shadow / DENY_ALL, Draft.** This is an additive continuation
of P0 V11, on the exact parent commit `2c1661ae0cf71e871c81482ca73ff67806621278`.
No original Stem, Neuron, Worker, NDU, CAS, Evidence WAL, FinalUse, production
model selector, tool-effect authority or `main` is changed.

## What previous P0 reports cannot tell us

The original matrix correctly preserved `MODEL.failed.txt` and a source-blind
per-model artifact even on physical model failure. But the failed slot's content
was intentionally generic: we could not tell from the downloaded original
artifact whether the pinned source checkout, CPU dependency setup, pretrained
checkpoint preflight or real inference step had stopped. Readable GitHub logs
are still the ultimate debugging evidence; a queued job has *no failure log*.
The V11 exact-HEAD job was queued at initial inspection, so this repair
addresses a **code-level observability gap**, not an observed V11 hosted crash.

## One original model, one bounded stage record

1. Give the six existing model-preparation/execution steps stable Actions IDs:
   `compact_checkout`, `gemma_checkout`, `source_lock`, `runtime`,
   `source_preflight`, `original_attempt`.
2. On every attempted Runner's original `if: always()` preservation step, write
   exactly one create-only `<model>.stage-v12.json` *after* the unchanged
   `attempt-<model>.json` and original physical output or `.failed.txt`.
   Values come from the GitHub Actions `steps.ID.outcome` enumeration; only
   `success`, `failure`, `cancelled`, `skipped`, `not_run` are permitted. No raw
   exception messages, environment, tokens, original foundation checkpoint
   weights or held test labels are included.
3. A separate collector Runner validates exact GitHub run ID, immutable
   `pull_request.head.sha` (or dispatch SHA), original model identity,
   no-effect flags, and consistency with the original success/failure/replay
   slots. An absent uploader is `artifact_not_uploaded`, never a low score.
   Successful model reports with a failed required stage are rejected outright.
4. Preserve the source HEAD / run / status summary separately as
   `hepta-p0-original-attempt-stage-observations-<run>` so negative model
   outcomes can be triaged even when complete 4-model admission fails. The
   original V11 isolated path intake accepts only the fixed new stage leaf;
   all other foreign files are still prohibited.

An original model's shell step can catch a failure and return success while
writing `MODEL.failed.txt`. Such an observation is **not** promoted to success
and uses the narrow stage label `caught_inside_successful_step`, with the
original failed-model artifact retained. This is not a parser for arbitrary
stdout or stderr and therefore does not leak model/system secrets.

## Scientific meaning and withheld permissions

These stage records are **self-reported observations from an original Runner**,
not cryptographically signed GitHub execution attestations or externally
verified safetensors origins. A successful named stage still does not prove
actual foundation weight use. V5 Head numeric replay, V6 real pretrained
cold-reload on another Runner, V7 independently re-executed genuine-label SGD,
all four original physical model results, independent original human-label
scoring and original blocking-ci / Architecture / security / Worker / WAL /
CAS / FinalUse gates remain mandatory and unchanged.

No new Granite/mmBERT/EmbeddingGemma/Laya actual language-task result, complete
hardware/energy budget, three prospective future windows or P1–P5 scientific
qualification follows from these local source tests. Do not merge/promote or
select a model from this diagnostic.

## Local reproduce

```sh
PYTHONPATH=experiments/shared_stem_cell python -m unittest discover \
  -s experiments/shared_stem_cell -p 'test_p0_runner_stage_diag_v12.py' -v
PYTHONPATH=experiments/shared_stem_cell python -m unittest discover \
  -s experiments/shared_stem_cell -p 'test_p0_*.py' -v
PYTHONPATH=experiments/shared_stem_cell python -O -m unittest discover \
  -s experiments/shared_stem_cell -p 'test_p0_*.py' -v
```

This program is stdlib-only and does not use actual pretrained weights in
its test fixtures. Real physical success must be established only from
exact-head hosted logs, numerical archives and independent reviews.
