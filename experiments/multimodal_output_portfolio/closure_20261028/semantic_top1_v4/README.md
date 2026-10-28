# Original top1 observer v4: registered study and portable mechanism

This is a new observer study for the existing two-second natural action/sound task. It preserves the selected single action label, selected single sound label, all 63 action classes and 17 sound classes, and the original empirical adequacy gate: each modality must achieve at least 60% accuracy and strictly exceed its own training-majority baseline. The original v3 negative result remains unchanged. No v4 semantic improvement has yet been measured.

The current executable delivery is a fixed eight-training-source feature, codec and resource pilot. It contains no observer fitting, generator update, candidate selection, old development/calibration prediction access, policy calibration, or qualification. The full fitting implementation must be independently pinned before optimizer execution, without changing this registration's candidates, selection rule, or budget.

## Frozen identities and access boundaries

[REGISTRATION.json](ci/REGISTRATION.json) is an exact copy of the registration created before this pilot. Its internal identity is `07152eb03b3df4d98ca97f5cf7b21b884eaac9311e9ece9c82d705c5143e30c2`; its file SHA256 is `dbbe54b0b15e789f4955f020e5a2cbef91c1759810c886400d801308824708b5`. It binds the original v3 source protocol, ontology, decode law, original feature code, all 512 observer-training videos, five source folds, and the eight mechanism videos.

The portable seed includes the exact original source-allocation metadata and only eight prepared **observer_train** directories. Other role metadata in that allocation is needed to preserve its exact identity; no prepared development, calibration, policy, or qualification data are included or read. Every retained event from each of the eight selected sources is required. An unavailable source or failed event is retained as a failure, without replacing the source.

The fixed source order is `video_6277`, `video_3212`, `video_1685`, `video_7513`, `video_3466`, `video_4523`, `video_6067`, and `video_8274`, totaling 43 events. The seed contains 24 regular files and 1,339,286 compressed bytes. It is encoded as 47 JSON Lines chunks so each source-control object stays below 40,000 bytes. [PILOT.json](ci/PILOT.json) checks every chunk, the reconstructed archive, every extracted file, source roles, event labels/order, original media hashes, and the original training-reference feature hashes. Extraction rejects links, duplicate members, and paths outside the exact manifest.

## Why these candidates

The [training-only diagnostic](../natural_results/TRAINING_ONLY_NEXT_STUDY_DIAGNOSTIC_001.json) found that the 512 observer sources contain 2,517 retained events. Their selected-label coverage is 55/63 action classes and 14/17 sound classes. Nineteen represented action classes appear in only one to four training videos. Multiple annotated sounds occur within many two-second windows, but that does not establish an upper bound on selected-top1 accuracy. Exact same-window inputs do not explain a large fraction of the observed weakness: the inspected S3D and TSM cached rows had no exact duplicate conflicts, and the finite PANN table's maximum agreement was approximately 0.9992. These are checks on the observed training table, not population guarantees.

The original pooled representations discard some time ordering. The new candidates preserve time bins and test whether this helps recognize the same selected labels. Full-window labels are used only by an explicitly separate auxiliary training head. They do not replace the top1 target or change the terminal score. The [separate set-label task proposal](../semantic_multilabel_proposal.md) remains unregistered.

| Modality | Fixed candidate order | Inputs |
| --- | --- | --- |
| Action | Existing pooled S3D MLP; temporal TSM; temporal TSM plus 0.25 auxiliary BCE | 1,424 pooled features or eight ordered 2,048-dimensional tokens |
| Sound | Existing pooled PANN ridge, lambda 100; temporal PANN; temporal PANN plus 0.25 auxiliary BCE | 1,551 pooled features or eight ordered 1,280-dimensional tokens |

The temporal head has a 128-dimensional learned projection and position embeddings, SiLU, dropout 0.15, scalar temporal attention, and a top1 classification head. Auxiliary variants add an independent sigmoid head for annotations overlapping the same target interval by at least 0.15 seconds. Missing annotations are training zeros for this auxiliary loss; they are not evidence that a physical event is absent.

## Fixed selection and fitting budget

Sources are sorted by a registered SHA256 rule and assigned by rank modulo five, producing source counts 103/103/102/102/102. Every event from a source stays in one fold. Feature normalization is fitted only on each training fold, with source-uniform weights. The neural sampler first chooses a training source uniformly, then one retained event from that source uniformly. Validation events never fit normalization or model parameters.

Each neural fit uses AdamW with learning rate 0.001, weight decay 0.01, batch size 64, and exactly 1,024 updates. Fold seeds are 7319 through 7323; the final refit seed is 7324. There are 25 neural cross-validation fits and five deterministic ridge solves, followed by at most two selected neural refits. The maximum is 27,648 optimizer updates. Recovery is required every 64 updates, including model, optimizer, sampler/global RNG, completed step, and source/feature/code identities. Only the latest recovery and completed models are retained; interrupted work cannot be reported as a completed budget.

Selection uses source-uniform out-of-fold top1 accuracy, with exactly one validation prediction per retained event. Ties use the registered candidate order. Both selected modalities must reach 60% and beat their fold-fitted majority control before any fresh adequacy media are decoded. All candidate/fold results must be reported.

The fresh observer adequacy allocation rule is registered for 128 new original videos with one event each. It keeps the original task eligibility/order, excludes all 1,024 current allocations plus historical 112 and host 16 sources, and selects eligible videos by a fixed SHA256 ordering. Exact IDs, events and archive identity must be frozen before their media or predictions are read. This pilot has allocated and consumed none of those 128 sources. The original policy64 and qualification64 are not reused as observer calibration. Failure of the new adequacy gate stops subsequent generator/policy qualification under this protocol.

## Portable CI execution

[The workflow](../../../../.github/workflows/ndu-natural-observer-v4.yml) runs on Ubuntu 24.04 with read-only repository contents permission, exact candidate checkout, and no persisted credentials. It is limited to this repository's PR4155 or an explicit workflow dispatch. It does not modify references, scientific gates, or the native runtime.

The registered Python 3.12.14 has an Ubuntu 24.04/x64 build in the [official setup-python version manifest](https://raw.githubusercontent.com/actions/python-versions/main/versions-manifest.json); the observed manifest identity and selected records are in [PYTHON_AVAILABILITY.json](ci/PYTHON_AVAILABILITY.json). This does not imply a Windows installer exists. The same Torch 2.8.0+cpu, torchvision 0.23.0+cpu, NumPy 2.3.5, SciPy 1.17.0, and Pillow 12.3.0 versions are required. FFmpeg must be available; its actual build information is retained and any resulting parity failure remains a failure.

A clean runner reacquires the same three previously selected official weight files, totaling 150,094,788 bytes, and checks full SHA256 and length before loading. [PORTABILITY_AMENDMENT002.json](ci/PORTABILITY_AMENDMENT002.json) explicitly authorizes this execution-only exception to the original registration's literal `no_new_pretrained_model_download` flag. The original registration is not edited. No new pretrained model, checkpoint, or hyperparameter is selected. Weight URLs, licenses/acquisition receipts, and the exact pins are included in the portable evidence. The network must support HTTPS to the official PyTorch, Zenodo, MIT HAN Lab, and Google Cloud Storage endpoints, plus the pinned Python/package distributions.

The original 28 GB training ZIP is not downloaded in full. The existing range reader verifies the frozen generation/ETag/length and obtains only the eight selected original-video members. Each member's exact source hash must match the retained training receipt. A changed archive, unreachable endpoint, missing runtime, or failed checksum blocks the attempt; none triggers a replacement source or checkpoint.

The explicit CI runtime adapter resolves the current cgroup from process membership and mount metadata, then reads every visible ancestor cap. Its [AST comparison](ci/RUNTIME_PORT_EQUIVALENCE.json) confirms the numerical mechanism functions and CLI are unchanged from the frozen original. Missing or ambiguous nonroot resource observations fail closed. At a visible hierarchy root where both memory files are legitimately absent, it records host-memory observations and explicitly unknown invisible ancestor restrictions. This is an execution amendment, not a claim of unlimited memory. Fourteen resource and seed behavior guards passed without importing Torch.

Before model import or downloading weights/media, the wrapper requires 1.5 GiB of effective memory headroom and 3 GB free disk. The mechanism rechecks a 384 MiB reserve at source boundaries. Only one heavy process is allowed, with two Torch threads. The estimated model RSS of 650–800 MB is not yet an actual measurement. The future 2,517-event feature cache is approximately 298 MB uncompressed, with 400 MB reserved for features/metadata and 50 MB for model/recovery storage. Those full-study allocations are not performed by this pilot.

The job has a 35-minute timeout and a nominal 1,800-second wrapper budget. Socket and process cleanup can overrun nominal deadlines; this is not a rigorous physical-CPU upper bound. The wrapper reports its process plus completed-child CPU, including dependency installation, weight reacquisition, decode, feature computation, codecs and readback. GitHub checkout/setup/upload administrative CPU lies outside this process and is not estimated as zero. Sampled RSS observations and child `ru_maxrss` are reported with their distinct meanings.

### Run the published pilot

From the repository root, using the registered Python runtime:

```sh
python -B -m unittest experiments.multimodal_output_portfolio.closure_20261028.semantic_top1_v4.ci_tests -v
python -B -m experiments.multimodal_output_portfolio.closure_20261028.semantic_top1_v4.ci_pilot --verify-seed-only --output /tmp/hepta-top1-v4-seed-check
python -B -m experiments.multimodal_output_portfolio.closure_20261028.semantic_top1_v4.ci_pilot --output /tmp/hepta-top1-v4-pilot
```

Use a new output directory per attempt. The seed-only command does not import Torch, install packages, or use the network. The execution command performs the fixed public downloads and dependency installation; it takes no arbitrary source list, checkpoint, model-choice, or holdout argument.

## What a mechanism pass means

For all 43 events, the pilot first recomputes the old pooled features and verifies their registered numerical tolerance against the historical training cache. It then physically writes text, PNG, PCM16 WAV and FFV1 video, reopens them, checks visual byte equality and the defined PCM conversion, and computes the new features from those actual reopened outputs. It preserves every four-file bundle, feature array, hash, source/range receipt, resource observation, and partial failure. It does not substitute target-cache features for output inference.

The local [attempt001](ci/LOCAL_RESOURCE_ATTEMPT001.json) was refused before Torch import: effective shared memory headroom was 4,153,344 bytes, below the registered 1.5 GiB minimum. It downloaded zero sources, ran zero updates, and consumed zero holdout media/predictions. Separate pure-stdlib guards and actual portable-seed validation passed. The portable [attempt002](ci/LOCAL_PORTABLE_RESOURCE_ATTEMPT002.json) also stopped before installation/download on this host; neither blocked attempt ran the feature mechanism. No full feature/RSS mechanism run has yet passed at this snapshot.

Even a future mechanism pass would establish only this registered feature/codec/resource path. It would not establish semantic accuracy, generated-output observer reliability, controller value, open-domain generation, or qualification. Actual generated-output reliability will additionally require output-distribution checks and fixed wrong-event negative controls before any renewed generator qualification claim.
