# Selective video acquisition and the cost of waiting

[实验结果与适用范围](RESULTS.md) · [模型和逐来源结果](evidence/results.json) · [同价原生时序对照](wait/README.md)

The complete pre-inference parameter archive is [locked_heads.zip](evidence/locked_heads.zip). [The selection commit](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/02d92eed5904d70d27876ad38c015d5a9f392970) precedes final camera inference. [The recording plan](recording_plan.json) binds candidate order and eligibility, [the physical roster](evidence/data_freeze.json) binds the source, and [the release manifest](evidence/archive_manifest.json) binds all derived arrays, split labels, acquisition receipts, parameter fits and evaluation traces.

## Portable evidence check

The GitHub job uses Python’s standard library to check archive hashes, 1,936 selector decisions, 704 bounded-edit decisions and exact convex combinations of the saved binary64 inputs. It separately reconstructs and checks the HAPT archive. The full offline workflow below also refits the models and compares the recomputed features and decisions.

```sh
python3 -m qualification.hcsn_blocker_followup.ci_evidence qualification/hcsn_blocker_followup/evidence
```

## Offline scientific replay

From the repository root, install the numerical dependencies used by #6988 (NumPy, SciPy, CPU PyTorch) and pin numerical threads. The model-only replay uses the two repository evidence directories and a newly created temporary directory. It recomputes all training and selection decisions for the new selector and bounded edits, confirms them on the sealed test observations, and checks each of the preceding study's 66 trained heads on those observations. Approximate maximum resident memory measured when generating the results is recorded with each cold process in the archive. This replay does not access the network.

```sh
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
python -m unittest qualification.hcsn_blocker_followup.test_selector
python -m qualification.hcsn_blocker_followup.replay \
  qualification/hcsn_blocker_followup/evidence \
  qualification/hcsn_intervention_value/evidence
```

Field-wise equality excludes timing, which varies across machines. The separate scalar checker recomputes source means, confusion counts, calibrated bins, sign probabilities and head displacements from evidence traces. See [the offline replay](evidence/offline_replay.json), [primary selector checks](evidence/selector_verify.json) and [direct-edit checks](evidence/edit_verification.json).

## Rebuild media and movement results

[The portable recording kit](media/source_replay.zip) contains the per-work permanent source URLs, attribution, licenses, byte hashes, original versions, clock checks, two frozen frontend paths, physical windows, RGB staging implementation, and its checks. Unzip the kit in an empty directory. Run `python pinned/portable_replay.py --help` there for the checkout, legal local original cache, weights and output arguments. FFmpeg, FFprobe, Pillow, torchvision and the exact ImageNet weights are necessary when reconstructing visual inputs from the original recordings. Derived feature replay needs only the archived features. [Recording release identity](media/evidence_packet.json) · [Camera equivalence on two original recordings](media/decoder_equivalence.json)

All 88 queries were independently rebuilt from the original recordings in fresh directories. All six NPZ files, every raw feature and the 528 two-class camera prefix outputs match byte-for-byte. [Raw replay](evidence/raw_replay.json). On a memory-constrained Linux worker, recover a partially finished RGB stage using the verified files in the same new workspace. The recovery tool checks the saved item before resuming, divides preprocessing into bounded subprocesses and retains the original six-frame batch for model inference.

```sh
python qualification/hcsn_blocker_followup/media/portable_memory_recovery.py \
  --workspace /path/to/portable-replay-workspace --kit /path/to/source_replay.zip --split test
```

The separate native movement experiment has its own original dataset credit, frozen source splits, fit seal and raw-sample verification. Its two archive pieces reconstruct a single ZIP. Follow [the movement study instructions](wait/README.md).

The historical 412-sample gap is evaluated as an identifiability question. [The sample-clock witnesses](evidence/gap_witness.json) preserve the known suffix and camera data when they vary the missing segment. Source and replay assumptions are given in [gap_witness.py](gap_witness.py).
