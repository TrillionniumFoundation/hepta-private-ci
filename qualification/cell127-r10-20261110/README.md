# Cell 1+2+7 — exact-head engineering replay (2026-11-10)

**Scope: independent rerun of existing synthetic GRU/diagonal-SSM producer probe, not independent real-task qualification.** The measured source is Draft #5853 head `fc893889e5e83c262592a134b52d054014b1793e`, source tree `60a16cec87046d82d03cac604753d506248b7883`. Original Draft #5724 source `176140c8c4f17204e704a8e9e4ae758f3567fa59` and its failing Actions remain historical originals. This evidence branch changes no executable source, original state owner, authorization, review threshold or old PR branch.

## Execution and identity

On authorized heptaruntime host `ai395`, a new isolated copy of the exact GitHub source was checked clean and frozen. Durable job `1a1c7928ce0-be2a-14d` completed with **exit 0**. The fixed protocol performed 6 actual CPU training fits: 3 seeds (41/67/89) × 2 model families (GRU, simple diagonal SSM), 40 optimizer updates each, 64 synthetic training episodes and 64 separately generated synthetic confirmation episodes per fit. Dataset seeds were disjoint by `seed+10000` versus `seed+20000`; these are *not* privately held independent customer tasks. Parameter counts: GRU 770, diagonal SSM 794. Training used NumPy 2.5.4 and one BLAS thread; the source manifest, exact source snapshot, raw model checkpoints and optimizer state, per-seed logits/labels/records, and real SQLite local owner database are attached without reconstruction.

Reproduce on the pinned commit with dependencies from `scripts/hepta_cells/requirements.txt`:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 \
  /usr/bin/time -v -o resources.log python3 scripts/qualify_hepta_cells.py --output /new/empty/absolute/probe
(cd /new/empty/absolute/probe && sha256sum -c /path/to/this/MANIFEST.sha256) # only same-byte replay; timings are variable
```

The attached `MANIFEST.sha256` authenticates the original artifacts *relative to this evidence directory*, not remote-execution identity or an independent evaluator signature. The source archive is a contemporaneous copy of `source.json` entries and is not a production model-weight custody certificate.

## Observations (not a science win)

| Seed | GRU NLL after | Diagonal SSM NLL after | Both accuracy | Rule accuracy |
| --- | ---: | ---: | ---: | ---: |
| 41 | 0.00007266 | 0.08840550 | 1.0 | 1.0 |
| 67 | 0.00001248 | 0.09849908 | 1.0 | 1.0 |
| 89 | 0.00002368 | 0.17731840 | 1.0 | 1.0 |

The **zero-training exact first-cue rule reaches 100%** on this task. Accordingly the models have not demonstrated incremental independent utility, old-task retention or any meaningful victory over an inexpensive fixed strategy. No VERIFY check-choice model was trained in this replay. HCSN/CfC/attention training and fair hyperparameter opportunities were not attempted.

The probe's own Python work loop reports **0.4916 s wall and 0.48755 s process CPU**. GNU `time -v` across Python startup and the probe measured **0.56 s wall, 0.54 s user CPU, 0.01 s system CPU, 44,876 KiB max RSS**. Per-fit train CPU is retained in the raw JSON (GRU ~0.031–0.032 s; SSM ~0.0132 s). Peak accelerator memory, accelerator use, energy, full transport and distributed recovery cost are **not measured**; the process used a CPU-only probe and had zero recorded socket messages. No GPU cost savings may be inferred. Byte-preserving SQLite owner reopen and receipt replay is only an injected-callback engineering experiment, not the native Bundle/CellStatePartition owner or independently signed evaluation.

## CI and progression boundary

At source head #5853, GitHub Actions Cell routes, v8-canary and Architecture finished SUCCESS, but [blocking-ci run 42904514541](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42904514541) finished FAILURE (15 success / 7 failure / 4 cancelled / 4 skipped on the 30-job first-page readback): Prettier fails on **two parallel-owner files**, `docs/hepta-generation-learning-readback.md` and `.github/workflows/hcsn-differentiable.yml`; cargo-deny retains RUSTSEC-2026-0459/0457/0461/0462; Windows Bazel shards and macOS Intel test fail. Do not silently reformat parallel owner files or weaken checks to create a green run.

Still **HOLD_NO_GO**: actual native owner admission and byte custody, original independent signed evaluator, a frozen PRED+VERIFY two-update protocol with real independent holdout and old-task retention, full CPU/GPU/RAM/network/recovery cost, ORG-1 owner net benefit, and fair GRU/SSM/CfC/attention/HCSN studies. This archive does not grant Adopt, Selection, FinalUse or production use.
