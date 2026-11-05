# UUID identity correction, candidate v2

This isolated revision changes only `execution.py`, `benchmark.py` and
`tests/test_execution.py`. The package still has 32 files and 26 Python sources.
The v1 directory, original baseline and previously frozen receipts remain intact.

The primary source is PyTorch v2.8.0 `torch/csrc/cuda/Module.cpp`, Git blob
`b44ce311ecd9245a97ee52513d04d187fb77ff80`: the public CUDA UUID object's string
conversion returns bare 8-4-4-4-12 hexadecimal. Comparing that raw value directly
with NVIDIA's canonical `GPU-` representation is not a valid identity check.

`canonical_gpu_uuid` accepts exactly one bare or literal `GPU-` prefixed grouped
hexadecimal string and returns `GPU-` plus lowercase hex. Whitespace, shortened
UUIDs, ordinals, multiple devices, MIG identifiers and nontext values are refused.
`configure_cuda` retains `uuid_raw`, puts the canonical value in its existing
`uuid` field, and independently normalizes and verifies the SMI UUID field.
Malformed or mismatched device identity cannot fall back to a logical ordinal.

EnergyCounter uses a canonical UUID lookup and checks the returned NVML UUID
before registering `nvml_<canonical UUID>`. It retains both raw and canonical
CUDA/NVML values and a separate `mapping_verified` flag. That flag does not mean
an energy counter is readable: unavailable and unsupported counters remain null.

An actual comparison on the selected device with nvidia-ml-py 13.610.43 accepted
both bare and prefixed UUID lookup and returned the same canonical string. We do
not attribute the old energy unavailability to mandatory rejection of bare
lookup. The confirmed problems are representation-sensitive comparisons and
counter-key identity; physical power/energy `NOT_SUPPORTED` remains independent.

Five new non-Torch methods cover real-format 16-byte UUID stringification,
canonicalization and rejection, early refusal without an ordinal fallback,
same-device NVML binding, invalid readback and unsupported energy. Existing mock
device fixtures now use valid UUIDs. The available suite actually ran 109
methods: 52 passed, 57 skipped, zero failures/errors. The strict invocation
returned exit 2 with zero tests because this preparation environment has no
PyTorch. Neither receipt qualifies tensor or CUDA execution.

Original model implementations, every existing numerical/optimizer/data function,
the sampler arithmetic, original full configuration bytes, rematerialization
module, seeds, budgets and scientific thresholds are unchanged. This revision
still requires the actual strict CPU, full-shape, parity and complete-budget
gates. Its source hash changes, so old cached results cannot qualify this source.
