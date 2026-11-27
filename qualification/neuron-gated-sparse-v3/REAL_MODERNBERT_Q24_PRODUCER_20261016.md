# Physical ModernBERT public Encoder to 32D Q24 research producer

**DRAFT / DENY_ALL / NO MAIN MERGE / NO PHYSICAL SPLIT.**

This experiment uses the actual original public CellBank research from [PR #1825](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1825), fixed Git SHA 758205d3de23ccbf76649b1446c271101dc917b0, rather than constructing a substitute untrained Encoder. The model answerdotai/ModernBERT-base is pinned to Hugging Face commit 8949b909ec900327062f0ebf497f51aef5e6f0c8 and validated against all stock safetensors tensor values. The real BANKING77 4-intent 64/32 subset comes from PolyAI immutable source commit 57ec275d8078af65b7731c2a98be812d844a6d6b (CC-BY-4.0), exactly as in the original successful hosted work.

## Execution stages

1. Independently check out the exact original source commit, verify the physical pretrained tokenizer/weights and case registry, then call the original LocalHFEncoder on every one of 64 fit + 32 heldout source texts using the same frozen four-option joint question format. The 768D pooled vectors are real pretrained model outputs, not synthetic projections.
2. Fit PCA mean, top-32 orthogonal SVD directions and 32 normalization scales **only on 64 unlabeled training examples**. Fixed-order sign normalization prevents arbitrary PCA sign flipping. Neither heldout labels nor heldout feature vectors affect the trained projector or its training-only normalization.
3. Freeze all 96 Q24 vectors with tie-to-even integer rounding bounded to [-8,+8], exact source IDs and text digests but **no labels**. Publish create-only physically serialized projector safetensors and re-open its exact bytes for all 96 bit-for-bit vector replay checks.
4. Create an immutable split registry and producer receipt with SHA256 references to the verified original pretrained snapshot, actual physical projection, registry and output. Run the separate strict Feature Snapshot admission checker from parent PR #2478. Reverify all original pretrained model weights after the last inference.
5. The dedicated hosted physical workflow now checks out both exact Git refs, installs the same pinned stock Transformers/Torch/safetensors versions proven by the original public run, executes mock physical PCA regression tests followed by the actual 96 public Encoder forwards, and retains the small public-only Q24 snapshot plus digest receipts. Raw public text, target labels and original pretrained base weights are not uploaded.

### Status and strict scientific limits

Local CPU Torch physical projector and safetensors execution has passed 6 of 6 tests in ordinary Python and 6 of 6 tests under python -O; **these tests use an explicitly synthetic 768D mock Encoder** and cannot be substituted for the new exact-HEAD hosted real pretrained public-run result. CI must run the actual original full model and test the new source before a physical real-Encoder outcome may be claimed.

Even a successful real Feature Snapshot does not give us a Q24 learning-quality result. The original public Dense16 / Sparse Top-2 outcome is a separate 768D bank experiment, not a V1/V2/V3/SSM/minGRU benchmark on this 32D Q24 feature space. A real fair test must freeze the actual selected no-change V1 baseline, train every candidate using this identical source, keep heldout labels in independent evaluator custody, measure future-window retention and negative transfer, and record complete train/inference FLOPs, RSS, p95/p99, generation/WAL/CAS/signature and 64-4096 scope target-host recovery. NDU and final-use remain DENY_ALL.

**No main merge, model promotion, CNS cutover, credential/effect delegation or physical Cell Split.**
