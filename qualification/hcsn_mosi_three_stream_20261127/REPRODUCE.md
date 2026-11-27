# Reproducing the three-stream CMU-MOSI comparison

Original immutable pre-registration 882d49723ac5096239abf9db5e115d2373cb4ae5. Fit, inference, fold validation and independent scoring source frozen at 5db0404968a602d0a1c847be8b25d5ba42c3a0b6. This experiment uses offline, pretrained contextual BERT features, pre-extracted acoustic coordinates and pre-extracted visual coordinates. All layers of each new MOSI sentiment model start from random weights. Upstream feature-extractor training and inference costs were not measured.

Obtain the public MMSA aligned MOSI feature file whose SHA-256 is d3994fd25681f9c7ad6e9c6596a6fe9b4beb85ff7d478ba978b124139002e5f9, as published by https://github.com/thuiar/MMSA . The pinned mirror is https://huggingface.co/datasets/tamb2203579/CMU-MOSI/blob/092c41f8843df675ab8a169e41419e74e6ae05da/Processed/aligned_50.pkl . The CMU official fold file corresponds to https://github.com/CMU-MultiComp-Lab/CMU-MultimodalSDK/blob/4f2eadcd7e7b9e20e83b868cdad385b41830285c/mmsdk/mmdatasdk/dataset/standard_datasets/CMU_MOSI/cmu_mosi_std_folds.py . Source readout code verifies the complete pickle byte hash before permitting the limited array deserializer. The regular experiment needs NumPy, SciPy and PyTorch CPU. Scoring uses the actual archived law table qualification/hcsn_continuous_20261127/paired_catalog/data/law.npz at b3fdc981568ab9ce122d2fb569372651e0b4b314, SHA-256 b855cd051381570af919ffd5b4b6e7efdb5051947de6f86d3861ecc87e3f4ba7.

The evidence bundle includes normalized confirmation inputs, recorded score vectors, source video and clip IDs, all attempted fit histories and selected-model receipts, perturbation donors, timing, selection seal and independent summaries. A second bundle contains all selected weight files referenced by the seal. The provided decoder validates every file hash and archive identity. The following commands start in this study directory. Independent metric reconstruction requires only NumPy.

    export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
    python archive.py restore . /tmp/mosi-restored evidence
    python archive.py restore . /tmp/mosi-restored weights
    python verify.py /tmp/mosi-restored/models /tmp/mosi-restored/cold /tmp/mosi-restored/data/data.json /tmp/mosi-restored/SEAL.json /tmp/mosi-metrics
    cmp /tmp/mosi-restored/result/SUMMARY.json /tmp/mosi-metrics/SUMMARY.json
    cmp /tmp/mosi-restored/result/all_intact_models.json /tmp/mosi-metrics/all_intact_models.json
    python replay.py /tmp/mosi-restored /path/to/paired_catalog/data/law.npz /tmp/mosi-predictions --cores 2 4

Replay reconstructs each held-out prediction, including three cross-video derangements per modality and per joint audio-visual swap. In the original run, torch parameters are float32 and BLAS is single-threaded on Intel Xeon Platinum 8573C. The optional cores argument accepts available CPU IDs on the local machine. Floating-point behavior may differ across CPU kernels or library versions. Input tensors, ground truth, stored predictions, weights and receipts constitute the original run. The source.py and prepare.py modules regenerate the complete processed training/development/test representation from the checksum-pinned input. The primary sources describe a speaker-independent official split. The release exposes video IDs and lacks a separately verifiable person-identity table.

For a new fit, generate the splits using the preparation program. Use an empty model directory, each tuple in models.designs(), and seeds 413, 677, 941.

    python prepare.py aligned_50.pkl official_folds.py /tmp/mosi-data
    python train.py /tmp/mosi-data /path/to/law.npz /tmp/mosi-models WIDTH ARM SEED

Assign each fit to one CPU. Run check_law.py against the sibling hcsn_independent_audiomnist_20261127/receiver.py. Call the seal subcommand of cold.py once the full matrix has finished. Call its score subcommand in a separate process for each tuple, using the positional arguments documented by the script. Scheduling affects which candidates finish before a CPU deadline. Archived scientific counts and prediction replay avoid that ambiguity.

For FP, the Gaussian target maps, training-only normalization, all three hidden solves and final regression are charged. The FP target uses seven linearly interpolated sentiment anchors, and the four-channel price/risk head gives the physical network more readout features than ordinary ReLU at equal hidden width. Inputs have 793 coordinates and six pooled temporal positions. The physical cell implements the price-table approximation, causal boundary movement and expected-reset recurrent state. Training and evaluation use continuous flow. The Transformer encoder uses bidirectional attention over the six supplied bins and starts with random sentiment parameters. Multimodal tests measure dependence on the provided features and their correspondence in this domain.
