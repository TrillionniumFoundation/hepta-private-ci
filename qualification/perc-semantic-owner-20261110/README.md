# PERC: real semantic evaluation and owned encoding

**Engineering result: PASS for the bounded components below. Scientific adoption: HOLD / NoUpdate.** This candidate implements and tests actual MobileNet encoding, a local durable owner, ordinary pinned-file capture/readback, exact original-wire retention, and consumption by the unchanged native PerceptionCellEncoderV1. The neural policies do not meet the task-benefit or resource-efficiency threshold.

The complete implementation is in the repository's `scripts/` tree. The archive contains original runs, inputs, trained heads, receipts, source snapshots, faults, and native/build evidence. Earlier publication checkpoints are historical and are superseded by `SUMMARY.json` and the resolved `CHECKPOINT.json`.

Baseline: `72569fba94a38f7bb0628409cbb05b62fa6c9627`, the existing PERC canonical-test-roots stage (#5683). Production Rust implementation, native authority, and the default policy are unchanged.

## Final controlled experiment

The generator seed is `2026111001`. Five controlled families cover semantic localization, occlusion, layout variation, temporal change, and text/image complementarity: 60 TRAIN, 20 reserved but unused DEV, and **30 distinct synthetic confirmation tasks**.

Global and dense each use training seeds `1101 / 2202 / 3303`, 200 updates per fit. Six fits and 1,200 optimizer updates complete before scoring. Ninety executions per arm repeat those same 30 tasks; they are not ninety independent tasks.

| Policy | Correct / executions | Completed online encoder batches | Continuation reads | Cumulative online wall |
| --- | ---: | ---: | ---: | ---: |
| Rules | 90 / 90 | 0 | 90 | 0.196993453 s |
| Global | 49 / 90 | 108 | 149 | 6.704176951 s |
| Dense | 63 / 90 | 108 | 138 | 6.735790162 s |
| Direct-ROI oracle | 90 / 90 | 0 | 90 | 0.044437444 s |

The oracle receives private answer locations and is excluded from fair policy comparisons. Direct ROI remains a strong baseline when the real task itself supplies valid coordinates.

| Training seed | Rules | Global | Dense |
| --- | ---: | ---: | ---: |
| 1101 | 30/30 | 16/30 | 22/30 |
| 2202 | 30/30 | 15/30 | 20/30 |
| 3303 | 30/30 | 18/30 | 21/30 |

Both neural policies use about 34 times the rule policy's online wall time and return fewer correct terminal answers. This run therefore supplies no adoption case.

The final run completes **432 successful encoder batches**: 72 for TRAIN-only PCA collection, 144 for head-training collection, and 216 online. These counters count completed valid finite feature batches, not every attempted forward or failed device operation. Each crop's backbone feature dimension is 576.

The full process envelope is 31.53 s wall, 31.01 s user CPU, 0.52 s system CPU, and 339,752 KiB peak RSS, exit 0. Do not add this inclusive envelope to its internal phases. Energy and paid provider costs are unmeasured.

### Fairness, splits and resource accounting

Rules, global and dense receive the same public target semantics, images, neutral complete-grid candidates and acquisition limits. Public tasks do not contain evaluator answer coordinates. Private scoring targets are opened after the fair actors execute; changing a private answer cannot alter an actor's decision. The six heads are frozen before confirmation scoring.

Document/template/source group IDs are disjoint and augmentation inheritance is checked. All tasks nevertheless share a controlled renderer and grammar. They do not establish independence across unseen real organizations or real-world source collections. DEV was not used for hyperparameter selection.

Exact source text and image latents remain complementary channels. Numeric answers carry original UTF-8 byte spans, source hashes and associated raster references. The generated numeric codes are not painted into the images. This is exact source-text fidelity, not OCR accuracy evidence. OCR contracts retain their engine and unverified-transcription status.

| Policy | Logical input observations | Additional immutable PNG reads by producer | Input file reads |
| --- | ---: | ---: | ---: |
| Rules | 198 | 0 | 198 |
| Global | 257 | 108 | 365 |
| Dense | 246 | 108 | 354 |

Extra image reads are included in wall/CPU time. These file counts exclude weights, code verification and bookkeeping. The temporal family uses controlled frames; V-JEPA and a real video-source qualification were not run.

## Implementation stages

`SOURCE_COMMITS.json` identifies seven coherent source commits, each verified against the final test-run SHA pins. The smallest first stage is the shared semantic contract and its tests.

| Stage | Main files | Result |
| --- | --- | --- |
| Public/source contract | `semantic_contract.py`, contract tests | Neutral geometry, private/public boundary, original evidence spans, grouped splits and acquisition budgets |
| Durable local owner | `owner.py`, owner tests | Reservation before effects, lifetime single-writer lock, retained receipts, bounded recovery |
| Capture adapter | `capture_entry.py` | Actual producer dispatch and preservation of original native bytes |
| Ordinary entry | `entry.py`, `__main__.py`, entry tests | `capture` and `capture-read`, strict pinned file acquisition and current-invocation counters |
| Semantic task and policies | `semantic_data.py`, `semantic_policy.py` | Five task families, strong rules, global/dense learned heads |
| Actual online benchmark | `semantic_benchmark.py`, benchmark tests | TRAIN-only projection, fixed heads, real online calls and exact original-wire archives |
| Reproducible integration drivers | `owned_qualification.py`, `perc1_native_cell_probe.py` | Real subprocess CLI lifecycle and actual native Cell consumption |

The benchmark plus its integration regression slightly exceeds the repository's 800-line staging guideline; it stays together as one coherent executable experiment and behavioral guard. The rest of the change is staged around explicit interfaces. Generated evidence and verbatim historical snapshots are retained separately.

## Ordinary owner and cold recovery

The entry is an **operator-pinned local file acquisition path**. The local POSIX owner durably reserves acquisition units before capture or encoding and binds owner/generation, grant, source frontier, capture backend and encoder/model identity. SQLite FULL synchronization and a lifetime nonblocking file lock serialize cooperating writers on one store.

Reserved-but-undispatched work can resume. A durable dispatch without a retained receipt is UNKNOWN, holds its reserved units and is not automatically replayed. Exact operation ID/payload reuse returns the immutable retained receipt; conflicting payloads or identities fail. This is not native authorization, cloned-store fencing or a complete wall/energy budget.

The real owned CLI qualification passes:

| Step | Current source callbacks | Encoder loaded | Completed encoder batches | Observed result |
| --- | ---: | --- | ---: | --- |
| Fresh capture | 1 | Yes | 1 | Four crops, 4 × 576 backbone features; actual CLI PID equals producer PID |
| Same-operation replay | 0 | No | 0 | Exact same receipt and original wire |
| New-process cold read | 0 | No | 0 | Exact same receipt/wire after deleting run-owned image, text and weight copies |
| New operation, missing source | 1 | No | 0 | Failure retained; second acquisition unit remains charged |
| Over budget | No admitted work | No new work | 0 | Journal rows and retained captures unchanged |

The next task extracts amount `0042.50` and entity `Hepta Labs` from registered retained UTF-8 spans without original source files or a new encoder call. Shared original weights remain unchanged.

The complete driver/child process envelope is 4.858137091 s wall, 4.711349 s waited CPU and 329,220,096 bytes largest waited-process RSS. This does not establish energy, provider billing or detached-process accounting.

## Original native wire and actual Cell consumption

Canonical JSON orders nested keys, but the existing wire digest depends on serde-compatible field order. The first complete run, `full-v1`, exposed this persistence defect.

The fix preserves the producer's original receipt and stores the original native wire as bounded Base64 before canonical serialization. Decode verifies the producer hash, byte length, original digest, strict JSON and typed semantic equality. The legacy producer/exporter is unchanged.

`full-v2` repeats the same cohort and hyperparameters to verify this repair. It is not new independent confirmation. V1/V2 have identical 360 terminal outcomes/read counts, 270 fair-policy rankings, 360 feature hashes/Q24 vectors, TRAIN backbone bytes and six fitted heads/optimizer traces.

The final artifact audit verifies 360 original retained native wires, 288 PCA feature rows, 467 exact quoted source spans and 90 task × seed groups with equal public packets and initial image hashes. V1's original results remain intact; its post-hoc wire reconstruction is explicitly labeled.

The native probe builds unchanged real `hepta-types`, `hepta-infer-core` and `hepta-neuron` sources. It uses the actual `PerceptionCellEncoderV1`, scope, request, trait and types:

- Consumed the exact 28,968-byte owner-retained original wire.
- Produced 64 Q24 scalars, 4 × 16, with zero truncated bytes.
- Python original wire and Rust canonical roundtrip agree exactly.
- Scope, frontier, encoder, model and raster negative controls all pass.
- Exit 0, empty stderr, one actual native consume invocation.

This is `PASS_NATIVE_CELL_ENCODER_ONLY`. Native Cell ownership, inference, daemon admission and authority-grant fields remain false. The benchmark, local owned CLI and native Cell probe are distinct evidence paths; benchmark actions do not all traverse the owner and native consumer.

## Verification and retained attempts

Final PERC regression: **127 discovered, 126 passed, one skipped, zero failures/errors**, 21.996 s. The existing real-document integration test requires an unavailable `PERC_TEST_DOCUMENT_DATASET`; no replacement dataset was invented. The real producer tests used the official fixed checkpoint. POSIX owner tests explicitly skip unsupported platforms.

Canonical `just fmt` passed with unchanged Python ASTs. All candidate source hashes remained unchanged during the final regression and real owned qualification. Source publication uses those exact bytes.

All three benchmark attempts are retained: smoke-v1, full-v1 and full-v2. Their actual benchmark work totals 18 fits, 2,460 optimizer updates and 918 completed encoder batches. These include setup and the same-cohort persistence rerun, not additional independent scientific repeats. The owned CLI's one call is separate; unit-test computation and infrastructure work are not included in those benchmark counters.

Earlier missing-fixture/formatter/environment failures are preserved. A temporary execution-connector outage was reconciled before accepting or repeating any ambiguous operation. The first native command had not been accepted; it was executed once after recovery. A later failed partial-clone fast-forward was repaired by restoring 116 exact baseline files, with candidate Python bytes unchanged. Final publication uses an isolated Git index and preserves the remote parent tree.

## Evidence map

| File | Content |
| --- | --- |
| `SUMMARY.json` | Final bounded engineering gates and scientific HOLD |
| `REPORT_BENCHMARK_V2.json` | Exact final report |
| `REPORT_BENCHMARK_V1.json` | Exact prior report, retained unchanged |
| `PROCESS_BENCHMARK_V2.txt` | Complete final process envelope |
| `REPORT_OWNED_CLI.json` | Actual capture/replay/cold/failure/budget results |
| `REPORT_NATIVE_CELL.json`, `NATIVE_GATES.json` | Actual consumer output, negative controls and scope |
| `INTEGRITY_V2.json`, `V1_V2_COMPARISON.json` | Receipt/span/input integrity and unchanged outcomes |
| `ACCOUNTING_ADDENDUM.json`, `ATTEMPT_LEDGER.json` | Logical/physical I/O and all benchmark attempts |
| `TESTS.json`, `TESTS.log`, `FORMAT.json` | Final regression and canonical formatter records |
| `SOURCE_COMMITS.json`, `SOURCE_FINAL.json` | Reviewable stages and complete executed-source pins |
| `EVIDENCE_MANIFEST.json`, `ARCHIVE.json` | Every archived input/output hash and exact archive identity |
| `raw-evidence-v1.tar.xz` | All raw runs, logs, generated data, heads, features, wire receipts, source/build snapshots and recovery records |

The archive contains `evidence/` paths and a manifest that excludes itself. The archive identity is outside it in `ARCHIVE.json`. The large-blob allowance binds only the exact SHA-256 bytes of this intentional research asset; the size policy is not relaxed for other bytes.

`SOURCE_SNAPSHOT.json` and `retained-source/` are the unchanged historical partial transfer checkpoint. The complete active source is now in the root `scripts/` tree; use `SOURCE_FINAL.json` for final identities.

## Reproduce

Use Python 3.12 with torch 2.8.0+cpu, torchvision 0.23.0+cpu, NumPy 1.26.4 and Pillow 10.2.0. The official weight file is `mobilenet_v3_small-047dcff4.pth`, SHA-256 `047dcff4addef86ea5bc2eff13c9614dc11f47ab1160d0a71a25e7db994f4e1f`. It is referenced by identity, not bundled. Installation/download records are in the archive.

Set a CPU interpreter that resolves these dependencies, then run from the repository root:

```bash
export PERC_PYTHON=/absolute/path/to/python3.12
export PYTHONPATH="$PWD/scripts"
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export PERC_WEIGHTS=/absolute/path/to/mobilenet_v3_small-047dcff4.pth
export PERC_WEIGHT_SHA=047dcff4addef86ea5bc2eff13c9614dc11f47ab1160d0a71a25e7db994f4e1f
"$PERC_PYTHON" -m perc1.semantic_benchmark --weights "$PERC_WEIGHTS" --weights-sha256 "$PERC_WEIGHT_SHA" --output /absolute/path/to/fresh-semantic-run --seed 2026111001 --steps 200 --train-per-family 12 --dev-per-family 4 --confirmation-per-family 6
PERC_TEST_MOBILENET_WEIGHTS="$PERC_WEIGHTS" "$PERC_PYTHON" -m unittest discover -s scripts -p 'test_perc1*.py' -v
```

Outputs are create-only; use a new directory for every attempt. Repeating the fixed cohort does not create new independent confirmation. Paths, PIDs, runtime costs and identity metadata may differ on a new machine.

Build the native probe from the real unchanged crate sources with a populated Cargo dependency cache:

```bash
"$PERC_PYTHON" scripts/perc1_native_cell_probe.py --repo "$PWD" --build-dir /absolute/path/to/fresh-native-build
```

The builder returns the binary path. Its `consume WIRE RGB EXPECTED RESULT` command can replay the original artifacts under `evidence/review-native-v1/native-readback/`. The archive includes the exact Cargo lock/manifests, compiler identity and Rust driver.

The real CLI driver is `python -m perc1.owned_qualification`. Supply `--output`, `--weights`, `--weights-sha256`, `--projection`, `--projection-sha256`, `--scope-input` and `--scope-digest`. Use the exact archived TRAIN projection and scope input, or generate and bind fresh identities. It exercises the ordinary `capture`/`capture-read` commands in separate subprocesses, removes only its own input copies, checks exact recovery, and verifies failed-attempt and over-budget behavior.

## Remaining adoption gates

Use an independently sourced real confirmation set with document/template/source separation, verified original evidence, and fair information/budget controls. Demonstrate improved terminal net utility or equal quality with fewer resources before adoption.

Live desktop/camera capture, production daemon integration, native Cell ownership/inference, distributed fencing, physical energy and complete provider billing remain open. Embedding shape, decreasing training loss and byte equality are necessary engineering evidence; they are not substitutes for task benefit.
