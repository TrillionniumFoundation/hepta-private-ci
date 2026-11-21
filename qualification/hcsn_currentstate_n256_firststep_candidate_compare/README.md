# N256 warm-1 sparse candidate versus archived dense oracle

Status: **SCIPY 1.17 LIST-ROW REPAIR CANDIDATE / ONE NEW IDENTITY / HOLD /
`all_closed=false`**.

This isolated stage consumes the exact warm 0→0.001 dense-oracle capsule from
Draft #6818 without re-executing that oracle.  It runs the already frozen
signed-content sparse candidate for one segment, serializes the complete state
and all packet alpha/generator/output tensors with the same canonical v2
serializer, and compares all 69,728 FP64 coordinates in canonical order.

The existing zero-error gate is unchanged: coordinate identities and every
eight-byte FP64 value must be exactly equal.  Absolute and ULP diagnostics are
recorded but cannot rescue a mismatch.  The single hosted child is limited to
4 GiB, one thread, 600 seconds, one dynamic segment and two sparse exponential
actions.  The parent captures current host, ancestor-cgroup, allocation,
calendar and complete cost originals before and after the child.

The original #6819 identity remains terminal RED: SciPy 1.17 rejected its
one-dimensional `csr_matrix` input before a result/counter record was written,
so its executed dynamic/exponential counts remain UNKNOWN. Draft #6820
preserves those originals. The first repair #6821 also remains RED because a
single nested tuple is not a supported SciPy 1.17 constructor input; #6822
preserves that evidence and its counters remain UNKNOWN.

A post-failure, zero-model probe in the exact local NumPy/SciPy versions tested
five constructor forms: the two tuple forms failed, while list-row, ndarray
column and explicit coordinate forms passed. This separately frozen identity
uses the list-row form and runs one three-element hosted compatibility
constructor before starting the bounded candidate.

Publishing this repair branch is its only numerical trigger.  A failure remains
RED and its artifact is uploaded; this identity is never retried under a new key.
The archived dense oracle, source #6817, evidence #6818, prior YAML/runtime
REDs, OOMs, cancellations and UNKNOWN records are not modified.

Even an exact match closes only this fixed-input, fixed-runtime N256 warm-1
candidate/oracle boundary.  It does not qualify later cycles, arbitrary
histories, N512, finite-domain coverage, full-network training, equal-budget
task benefit, asynchronous cost, C2 full replay, HPCA external custody or
production adoption.  Global HOLD and `all_closed=false` remain.
