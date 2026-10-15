# Hepta P0 V11 — lossless, isolated original four-model artifact intake

**DRAFT / SHADOW / DENY_ALL.** Additive research-only continuation on exact V10 parent
`cb4c42caec5a5848893d3658a89be78f6f52b038` (#2212). No main/Neuron/Worker,
model selection, NDU, Q24 wire, CNS, Artifact CAS, Evidence WAL, FinalUse,
production action or tool-effect control is modified. The changes are isolated
to the original P0 research workflow, one new standard-library intake program,
tests, this runbook, and the corrected inherited workflow assertion.

## Source-identified issue

V10 correctly runs Granite, mmBERT, EmbeddingGemma text and Laya native in
independent matrix jobs. But its `physical-four-models` collection step used
`actions/download-artifact@v4` with `merge-multiple: true`. According to the
[GitHub-maintained v4 migration guide](https://github.com/actions/upload-artifact/blob/main/docs/MIGRATION.md),
**identical paths overwrite each other and the last writer wins**. V10 named
ordinary model outputs uniquely, so an actual collision was **not observed**
on GitHub; however, an anomalous/forged extra file or future addition could
silently overwrite another arm, hide a failure record or defeat per-arm lineage.
A queued workflow is **not** a model failure or an artifact collision.

## V11 implementation

- Download all matching model attempt artifacts **without merging**; each is
  retained under `hepta-human-original-arm-<exact_model>-<run_id>/`.
- `p0_isolated_artifact_intake_v11.py` verifies the exact four possible model
  directory names, decimal GitHub Run ID, per-model declared upload inventory,
  bounded regular files, prohibited links, path traversal/cross-model files,
  duplicate JSON fields, attempt outcome, original-model-versus-failed-slot
  exclusivity, and a non-Laya three-file `*.replay/` tensor subtree.
- Only `fit.json` (TRAIN/CAL labels) and `blind.json` (held inputs WITHOUT labels)
  may preexist in the aggregation workspace. Owner-only human held labels,
  checkpoint foundation weights, extra executable code, duplicate/ambiguous
  paths and foreign artifacts are rejected, **not** scored.
- File bytes are copied to create-only collector paths with SHA-256 recorded
  for each leaf. `artifact-intake-v11.json` is written *last*. This hash record
  is **not a publisher signature** and cannot authenticate GitHub runners.
- A missing per-model upload remains `artifact_not_uploaded`; an explicit
  original-model failure remains `failed_or_incomplete`. A malformed or extra
  artifact is a hard intake error, never an unavailable/low-scoring model.
- The original V10 `p0_parallel_model_collector_v10.py` continues to validate
  the complete input/source/Head replay, and it still exits nonzero unless
  **all four** genuinely valid original model attempts are present. Original
  V8 partial diagnosis remains read-only, with V5/V6/V7 and independent human
  scorer completely unaffected by a partial result.

The GitHub Actions download step uses `continue-on-error: true` **only for
archival observability** when no model job uploaded anything; the original
collector still rejects missing arms. It is **not** an acceptance waiver.

## Exact local verification

```sh
PYTHONPATH=experiments/shared_stem_cell python -m unittest discover \
  -s experiments/shared_stem_cell -p test_p0_isolated_artifact_intake_v11.py -v
PYTHONPATH=experiments/shared_stem_cell python -m unittest discover \
  -s experiments/shared_stem_cell -p 'test_p0_*.py' -v
PYTHONPATH=experiments/shared_stem_cell python -O -m unittest discover \
  -s experiments/shared_stem_cell -p 'test_p0_*.py' -v
```

Observed on exact authored Python source: **22/22 focused tests**, **312/312
ordinary**, **312/312 under `python -O`**, no failures/errors/skips. The
end-to-end fixture passes all FOUR original **synthetic** model/Head outputs
through the new archive isolation before the unchanged V8 independent numeric
and V10 strict four-model census. This validates the collection contract, not
natural-language accuracy or actual pretrained Encoder execution. `compileall`,
duplicate-key-rejecting YAML parsing, nine workflow job definitions, and
**27 Shell `run` blocks** passed `bash -n` locally. Git Blob SHA equality and
exact HEAD hosted results are separate requirements.

## Scientific interpretation and hard limitations

No new Granite/mmBERT/EmbeddingGemma/Laya real pretrained task score, true
quality-over-complete-cost winner, source licensing, independent issuer
signature, prospective future1/future2/future3 source windows, source-family
power, full model/host telemetry, or physical Head/Cold-Encoder replay success
has been inferred from the local tests. The limited Laya no-change policy is
not a same-parameter trained Head comparator. P1–P5 (continual Stem/Cell,
split/merge, multimodal generation, NDU/FBSDE, native CPU/GPU computer-use)
remain unqualified on the same independently reviewed criteria. This work
never grants promotion, FinalUse, or production capability. Keep **DRAFT /
DENY_ALL**, and require exact-source hosted P0 as well as original
`blocking-ci`/Architecture/Security/Worker/WAL/FinalUse gates.
