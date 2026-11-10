# Independent CPU attention-path observation

The frozen v6 model uses **CPU fused scaled-dot-product attention** at the
observed training shape. Two successful profiles record both
`aten::_scaled_dot_product_flash_attention_for_cpu` and
`aten::_scaled_dot_product_flash_attention_for_cpu_backward`; neither records
an attention-math fallback. The [summary](attention-cpu-path-v1.json) binds raw
operator records, Chrome traces, source identities and the exact profile script.

The run uses Torch2.8.0+cpu, FP64, one intra-op and one inter-op thread, a width16
TransformerEncoderLayer with two heads of dimension8, feedforward width64,
dropout0, and an explicit causal mask. The actual first32 training windows form
a padded input of shape32×256×25, with8134 valid labelled events. The common
frontend/head and identity-initialized learned adapter are included. It performs
one training-mode forward and weighted-CE backward, with finite gradients for
all trainable parameters, and no optimizer update.

A second successful run enables `MKL_VERBOSE=1`. Its raw stdout records1809
oneMKL DGEMM calls, each with `NThr:1`; this directly confirms BLAS use beyond
Torch's `aten::mm` and `aten::addmm` operator names. The installed build advertises
MKL and AVX512 capability. This trace does not identify the exact assembly
microkernel or instruction set used inside each individual DGEMM.

These observations qualify the stated CPU execution path at the sampled shape.
They do not establish GPU FlashAttention, an optimized GPU benchmark, comparative
throughput, energy efficiency or general shape coverage. The recorded1.37089s
and1.04031s include profiling and setup overhead and are not timing-comparison
results. Evaluation/inference may select another path and was not profiled here.

Two unsuccessful reviewer preparations remain archived. Version1 incorrectly
required every real window to have256 events instead of permitting the actual
padded shorter window. Version2 used the filename `profile.py`, shadowing Python's
standard-library module and re-executing the script during an import. Neither
produced attention-operator evidence. Version3 uses a unique filename; version4
adds direct MKL verbose evidence without changing the frozen model or data.
