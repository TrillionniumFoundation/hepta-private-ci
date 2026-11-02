# HCSN R2 source and evidence bootstrap

The final Chinese research report is `repo/experiments/hcsn_next_blockers_r2_20261101/REPORT_ZH.md`.
This package preserves successful and failed runs. It does not assert all blockers closed.

After extracting this ZIP into an empty directory, run `python3 restore.py` there.
It verifies every payload and restores the exact nested R1 source/evidence archive into `repo/`;
conflicting existing files cause an error. R2 files, predecessor checkpoints/features,
and sibling `upstream_lipreading_tcn/` then have their original relative layout.
`BUNDLE_MANIFEST.json` inventories all payloads except itself; the external final receipt
provides the ZIP SHA256. ZIP compression records the runtime zlib version; identical
inputs on that runtime yield identical bytes. No cross-zlib byte-identity claim is made.

Use Python 3.12 (recorded runtime 3.12.14), FFmpeg/ffprobe 6.1.1-3ubuntu5, and an isolated
environment. The measured runtime used these exact Python packages:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --index-url https://download.pytorch.org/whl/cpu 'torch==2.6.0+cpu' 'torchaudio==2.6.0+cpu'
python -m pip install 'numpy==2.3.5' 'scipy==1.17.0' 'Pillow==12.3.0'
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
cd repo
```

The package contains derived pixels/features, fitted heads, frozen neural checkpoints,
raw scientific arrays, logs, protocol/source commitments, and per-component byte manifests.
Preserve these archived records; rerun commands in each lane's README or source CLI with
fresh output directories. Confirmation results are already exposed and cannot be reused
as an unseen confirmation dataset for selecting new methods.

Raw public CREMA FLV/GRID MPEG media and two third-party pretrained weights are excluded.
Their identities, URLs, licenses and acquisition receipts are retained in
`EXTERNAL_INPUTS.json` and the relevant lane. Raw media are only necessary to repeat
acquisition/feature extraction, not to audit saved logits or refit heads from saved features.
The raw-data modules verify exact source bytes (CREMA) or registered ranges/CRC and
acquisition SHA (GRID). Reacquire only the registered cohorts; source changes must fail
identity checks. Keep raw files beside `repo/` as `video_raw_r2_media/` and
`grid_raw_r2_media/`, including GRID speaker namespaces. Existing derived outputs must
not be overwritten by reacquisition commands.

From `repo/`, reacquire the official visual weights without changing the archived receipt:

```sh
python -m experiments.hcsn_video_pretrained_feasibility_r2_20261101.acquire --output ../pretrained_lipreading_weights/resnet18_mstcn_video.pth --receipt ../visual_reacquisition.json
mkdir -p ../upstream_audio
curl --fail --location --output ../upstream_audio/wav2vec2_fairseq_base_ls960_asr_ls960.pth https://download.pytorch.org/torchaudio/models/wav2vec2_fairseq_base_ls960_asr_ls960.pth
printf '%s  %s\n' 488fd4f16de84438ffc945334278c1b9fb9b7159a806c1080b16111a958c945d ../upstream_audio/wav2vec2_fairseq_base_ls960_asr_ls960.pth | sha256sum --check
printf '%s  %s\n' c72c9d494ffdcb8616ce183b92393b17a8bdf1ad8b523c9ac42b0507824c214f ../pretrained_lipreading_weights/resnet18_mstcn_video.pth | sha256sum --check
```

The visual source is the unchanged original-author subset from commit
`0cc99fab046bd959578f2baac52e654746da4825`. Its full custom LICENSE and upstream README
are included. The terms restrict research/benchmark use and BBC-content use; commercial
or production permission is not established. Audio TorchAudio source is pinned at
`d8831425203385077a03c1d92cfbbe3bf2106008`, with BSD-2-Clause software and separately
MIT-licensed official weights. Upstream reported recognition results are not this study's
results; human-identity overlap with pretraining is not audited.

When rerunning the audio feature-extraction CLI, pass `--checkpoint ../upstream_audio/wav2vec2_fairseq_base_ls960_asr_ls960.pth` explicitly; the saved CHECKPOINT receipt retains its historical absolute acquisition path. Do not edit that receipt to relocate the package.

Feature extraction is a separate step from `study.py`; its `train/evaluate` phases only consume already hashed feature arrays. From `repo/`, use fresh output directories, for example:

```sh
python -m experiments.hcsn_audio_pretrained_r2_20261101.encoder --manifest experiments/hcsn_audio_pretrained_r2_20261101/TRAIN_COHORT.json --media-root ../video_raw_r2_media --out ../rerun/audio_train_features --split train --checkpoint ../upstream_audio/wav2vec2_fairseq_base_ls960_asr_ls960.pth
python -m experiments.hcsn_audio_pretrained_r2_20261101.study train --features ../rerun/audio_train_features --out ../rerun/audio_heads
```

The optional original `checks.py` preflight has no checkpoint override and its default loader uses the historical absolute path. Its saved result/source identity can be audited without rerunning it; reproducing that optional preflight at a new root needs an explicitly recorded relocation entry point. The commands above neither change frozen scientific source nor require a symlink at the original absolute path.

The CPU-envelope lane additionally requires Linux x86_64, libseccomp.so.2 and permitted TSYNC seccomp filters. Its capability failures are preserved; unsupported environments cannot be described as successful family/GPU/energy measurements.

## Restoring the public chunk transport

Obtain `restore_transport.py` and `TRANSPORT_MANIFEST.json` from the same reviewed publication commit. The manifest pins every part's SHA256, size and Git blob SHA1, plus the complete archive SHA256. The transport manifest and `evidence_parts/` are kept outside the ZIP to avoid self-reference; the helper sources may be inside it.

```sh
python3 restore_transport.py --manifest TRANSPORT_MANIFEST.json --parts-dir evidence_parts --output restored_evidence.zip
python3 restore_transport.py --manifest TRANSPORT_MANIFEST.json --ref REVIEWED_FINAL_COMMIT_SHA --output restored_evidence.zip
```

Use one source mode per invocation. Remote mode requires an explicit commit or branch ref; a final reviewed commit is preferred. It downloads only public raw GitHub blobs and needs no authentication. Successful complete parts are verified and cached; network failures are not retried. Incomplete or corrupt `.partial` files remain available and stop the run until explicitly moved or removed. A complete verified part `.partial` may be promoted to the reusable cache. Final archive publication refuses existing files and symlinks. This step reconstructs bytes only; extract the verified ZIP and run its `restore.py` separately to restore predecessor paths.
