# R13 prepared finite CTMC interface

This interface evaluates a supplied finite row generator in float64. It does not construct the financial model, differentiate through native calls, or identify a continuum diffusion with its finite approximation. The immutable model contains an exact copy of `Q`, its version, its SHA-256 identity, the validated uniformization representation, and a bounded transition cache. See [NATIVE_ZH.md](NATIVE_ZH.md) for measured accuracy, costs and scope.

## C ABI

All functions return an `int32_t` status; zero means success. `size_t` has the target platform's native width. Matrices and batches are row major. Every supplied pointer must address a valid, correctly aligned buffer of the documented length. Null checks and caught Rust panics do not make an invalid C pointer safe.

```c
int32_t hcsn_model_create(size_t n, const double *q,
                          uint64_t version, uint64_t *out_handle);
int32_t hcsn_model_release(uint64_t handle);
int32_t hcsn_model_identity(uint64_t handle, uint64_t expected_version,
                            uint8_t *out_ascii_hex_64);
int32_t hcsn_prepare(uint64_t handle, uint64_t expected_version,
                     double dt, uint32_t mode);
int32_t hcsn_cache_clear(uint64_t handle, uint64_t expected_version);
int32_t hcsn_cache_statistics(uint64_t handle, uint64_t expected_version,
                              uint64_t *out_four_counts);
int32_t hcsn_transition(uint64_t handle, uint64_t expected_version,
                        double dt, double *out_n_by_n);
int32_t hcsn_propagate_batch(uint64_t handle, uint64_t expected_version,
                             double dt, uint32_t mode, size_t batch,
                             const double *prior, double *out);
int32_t hcsn_observe_batch(uint64_t handle, uint64_t expected_version,
                           size_t batch, const double *prior,
                           const double *likelihood, size_t likelihood_rows,
                           double *out);
```

`q` contains `n*n` doubles. `prior` and `out` contain `batch*n` doubles. `likelihood_rows` must be one or `batch`, so `likelihood` contains either `n` or `batch*n` doubles. The identity buffer contains exactly 64 ASCII hex bytes without a terminating NUL. The four cache statistics are generator validations, successful preparations, cache hits and cached payload bytes. The validation count of one describes the immutable construction contract; it is not a process-wide allocation profiler.

The mathematical operations are

\[
  p_{\mathrm{next}}=p\exp(Q\,dt),\qquad
  p_{\mathrm{observed},j}=\frac{p_j\ell_j}{\sum_k p_k\ell_k}.
\]

Observation accepts arbitrary finite nonnegative likelihoods. Scaling each likelihood row by its maximum avoids overflow without changing Bayes' rule. Zero evidence is explicitly refused. Propagation does not renormalize away truncation or floating point mass error. Probability rows must be finite, nonnegative and have total mass within `5e-10` of one.

`mode=0` prepares a sparse uniformization recurrence; `mode=1` prepares a dense transition matrix. `hcsn_transition` always uses the dense cache. The key is the exact float64 bits of `dt` together with the mode, local to one immutable model. There is no rounding to a time bucket. `Q`, its dimension and the supplied model version all enter the identity. The registry uses opaque handles that are not reused; all operations except release require the expected version. A changed generator requires a new model, even if the caller keeps the same application object.

## Limits and refusals

| Status | Meaning |
|---|---|
| 1 | Invalid dimension or batch shape |
| 2 | Invalid numerical domain |
| 3 | Invalid row generator |
| 4 | Probability or observation normalization failure |
| 5 | Work or live-handle limit |
| 6 | Numerical failure |
| 7 | Null pointer |
| 8 | Caught panic or unavailable internal lock/workspace |
| 9 | Unknown or released handle |
| 10 | Model version mismatch |
| 11 | Cache capacity reached |

The current limits are 1,024 states, 4,096 batch rows, 8,388,608 batch elements, 128 live model handles, 32 cache entries per model, 64 MiB of cached transition payload per model and 16,384 time subdivisions. These are local implementation limits, not a complete process memory or production resource envelope. Cached bytes do not include every allocation, registry entry, thread-local workspace or a transition temporarily retained by an in-flight call.

Output buffers are copied only after successful computation of the whole batch. A bad final probability or observation row therefore leaves the entire caller output unchanged. An operation may populate a valid transition cache before a later input check fails; such cache changes do not advance a posterior or an event state. Thread-local scratch capacity is reused. Python may still allocate or convert arrays, and a first use may grow the workspace.

## Python interface

`adapter.py` provides `PreparedModel(q, version=0, mode="dense", library=None)` and a context manager. `prior` can have shape `[n]` or `[batch,n]`; likelihoods can have shape `[n]` or `[batch,n]`.

```python
import numpy as np
from adapter import PreparedModel

q = np.array([[-2.0, 2.0], [1.0, -1.0]], dtype=np.float64)
prior = np.array([1.0, 0.0], dtype=np.float64)
with PreparedModel(q, version=13) as model:
    model.prepare(0.45)
    transition = model.transition(0.45)
    predicted = model.propagate(prior, 0.45)
    posterior = model.observe(predicted, np.array([0.2, 0.8]))
    reusable = np.empty_like(posterior)
    model.propagate(posterior, 0.45, out=reusable)
    identity = model.identity
    counters = model.cache_info()
```

`out` must be a writable, C-contiguous NumPy float64 array with the same shape as `prior`. Output reuse and input/output aliasing are tested. Native nonzero statuses become `ValueError`. The interface is for inference; training in the parent experiment uses the separately defined differentiable operator.

## Irregular time steps and full caches

There is no automatic eviction or approximate time substitution. A new exact `(dt, mode)` beyond capacity returns `cache_limit`. `PreparedModel.clear_cache()` discards prepared transitions while preserving immutable `Q`, version and identity. Repreparation is charged when it occurs.

The research actor in `runtime_adapter.py` commits its posterior, clock, sequence and checkpoint lineage only after propagation and any requested observation succeed. Its cache-full witness fills all 32 entries, observes the refusal without any of those state fields changing, clears the underlying prepared cache, and retries the same request successfully. This witness is [evidence/CACHE_LIMIT_WITNESS.json](evidence/CACHE_LIMIT_WITNESS.json). The actor does not expose an automatic clear/retry policy. A single owner can explicitly manage its prepared model; a production wrapper needs its own resource and retry policy.

## Build and identity

`build.py` invokes the selected Rust compiler directly; no additional Cargo crate is used. It produces `libhcsn_prepared.so` and the event CLI, together with `BUILD_RECEIPT.json`. The tested Linux artifacts and ten runtime source hashes are fixed in [RUNTIME_FREEZE.json](RUNTIME_FREEZE.json). A rebuild is a new binary identity and must be validated as such. Reusing an old audit receipt after a changed build is not sufficient.
