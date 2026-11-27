# Recount the sealed chronological gas experiment

The fixed protocols precede scoring in commits c058985afa9fe85122deb5f140d4f5cca489f9b2 and bcf27f9863810e7ba0040c04a8b132a33998cf44. The source frozen for confirmation is 4ce7ee4373b8640c0951d69b85609c2175dc604d. The original HCSN law table is qualification/hcsn_continuous_20261127/paired_catalog/data/law.npz at b3fdc981568ab9ce122d2fb569372651e0b4b314, SHA-256 b855cd051381570af919ffd5b4b6e7efdb5051947de6f86d3861ecc87e3f4ba7. This implementation uses a piecewise bilinear approximation of the finite-horizon prices and the explicit continuous reference boundary. The table is common across experiments. Install NumPy, SciPy and scikit-learn. Download the official gas archive listed in PROTOCOL.md as gas.zip and verify its recorded hash. The following commands start in this directory.

```bash
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
python evidence_bundle.py restore . /tmp/gas-verified
python verify.py /tmp/gas-verified/models /tmp/gas-verified/scores /tmp/gas-verified/SEAL.json gas.zip /tmp/gas-recount.json
cmp /tmp/gas-verified/SUMMARY.json /tmp/gas-recount.json
```

For a fresh fit, keep the receiver.py module in the sibling hcsn_independent_audiomnist_20261127 directory. Use an empty destination and pin every command to one available physical CPU as appropriate.

```bash
archive=/path/to/gas.zip
law=/path/to/paired_catalog/data/law.npz
mkdir -p fresh-models
python gradcheck.py "$law" fresh-models/gradcheck.json
for seed in 2021 4411 6709; do
  for arm in raw frozen fourier forward bp hybrid_bp; do
    python train.py "$archive" "$law" fresh-models "$arm" "$seed"
  done
  for arm in fp_hcsn fp_relu8 fp_relu32 fp_flat32 fp_shuffle; do
    python forward_projection.py "$archive" "$law" fresh-models "$arm" "$seed"
  done
done
python cold.py seal fresh-models "$archive" "$law" fresh-seal.json fresh-scores
for seed in 2021 4411 6709; do
  for arm in raw frozen fourier forward bp hybrid_bp fp_hcsn fp_relu8 fp_relu32 fp_flat32 fp_shuffle; do
    python cold.py score fresh-models "$archive" "$law" fresh-seal.json fresh-scores "$arm" "$seed"
  done
done
python verify.py fresh-models fresh-scores fresh-seal.json "$archive" fresh-summary.json
```

The fixed CPU-time deadline changes the set of accepted updates across machines. The byte-exact archived score recount and the independent fresh fit have different reproducibility guarantees. End-to-end timings include the measured source initialization, full development search through the reported prefix, cold scorer imports and source reads, model loading and external inference. For a prefix that fell between two development calls, the selection time uses the upper bound (the next completed call). The cost excludes initial network download, interpreter launch before script entry, serialization of checkpoints, evidence packaging and the independent aggregate recount. Read the per-seed receipts before projecting timing to another machine.

Acquisition batches are the held-out conditions. Three batch identities limit uncertainty estimation. The 4,364 later cases span three batches of very unequal sizes, so the registered quality metric weights acquisition batches equally and classes equally within each batch. A pooled micro-accuracy answers a different question. All methods use the same fixed softmax temperature for the optional Brier and calibration diagnostics.
