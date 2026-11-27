# Replay and fitted-parameter accountability

The three base modules model.py, study.py and prepare.py in this directory are unmodified copies from the common RSICD literal-BP panel. The two studies share architecture, raw input, tokenizer, initialization seeds, prefix minibatch generation and scoring. The separate methods in construct.py never call the base fit function or a gradient. fit.py executes all methods under PyTorch inference mode and actively rejects calls to Tensor.backward, torch.autograd.grad or torch.autograd.backward. Only import_bp.py inspects external BP results, after both studies have sealed their selected states.

Use CPU PyTorch and NumPy with one Torch/BLAS thread. The original raw 32×32 RGB array has SHA-256 d79c414bb32c3ffb88f1714c20b6bdb531a68a7a95999370c86aea7367b768b1. Input images come from the original-author RSICD gallery. Only the canonical author caption whose SHA was fixed before this panel supplies training/evaluation words. The complete confirmation inputs, token targets and image ordering, raw per-image losses, all train/development model receipts and every fitted matrix or low-rank recipe are stored in the two local archives. The separate paired archive has the BP and causal SDPA matched/shifted image measurements, independent replay receipts and the joint comparison. Both the read-only base and extension use the same fixed pretrained-component-free operation.

    export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
    python pack.py restore . /tmp/rsicd-restored evidence
    python pack.py restore . /tmp/rsicd-restored recipes
    python pack.py restore . /tmp/rsicd-restored paired
    export FULLSTACK_DATA=/tmp/rsicd-restored
    python verify.py /tmp/rsicd-restored /tmp/recount-local.json
    python verify.py /tmp/rsicd-restored /tmp/recount-joint.json --bp /tmp/rsicd-restored/bp
    cmp /tmp/recount-local.json /tmp/rsicd-restored/result-local.json
    cmp /tmp/recount-joint.json /tmp/rsicd-restored/result-joint.json
    python cold.py score /tmp/rsicd-restored --destination /tmp/replayed-scores
    python replay.py /tmp/rsicd-restored /tmp/replayed-scores

The last two steps run the actual original forward path, rebuild every dense model tensor from its base seed and saved coefficient factors, re-evaluate every selected image against its genuine and shifted pixels and compare the regenerated original arrays exactly. Per-image NLL sums are retained so global token-weighted results can be reconstructed independently of PyTorch. Original measured timings describe this machine and software, with both CPU and real elapsed clocks under actual concurrent load.

For fitting, reconstruct the RSICD canonical pixel and caption inputs with the upstream original sources and immutable checksums in the protocols. The prepared raw-pixel directory in the original run contains pixels32.npy, rows.json and prepared.json. prepare_fit.py constructs the canonical restricted train/dev tokens and verifies they reproduce the supplied canonical file. See runner.py for sequential cold-seal handoff and parallelism. Keep the fit-only split separate from confirmation targets. The published experiment's immutable state seals and raw files are the authority for which checkpoints actually met each time budget. Timing-dependent candidate eligibility can differ after a fresh run.

The shuffle control permutes hidden-stage supervision while preserving true dictionary fitting. The random-feature control fits hidden layers to unlabeled random input keys. The dictionary-only control modifies the tied input/output representation while keeping physical stages fixed. The separately fitted frozen-feature probe breaks tying at its output and is marked accordingly. The hard constants in ANNEX.md specify an architecture-compatible local training rule. Parameter bit changes, raw learned coefficient count, data-conditioned rank and empirical paired task quality answer different questions. The measured interval for an upper loss bound uses the original registered +0.05 nats per target token. A paired interval strictly within ±0.05 is stronger.
