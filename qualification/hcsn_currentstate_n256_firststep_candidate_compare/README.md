# N256 warm-1 sparse candidate versus archived dense oracle

Status: **SOURCE FROZEN / ONE ATTEMPT / HOLD / `all_closed=false`**.

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

Publishing the frozen branch is the only numerical trigger.  A failure remains
RED and its artifact is uploaded; the run is never retried under a new key.
The archived dense oracle, source #6817, evidence #6818, prior YAML/runtime
REDs, OOMs, cancellations and UNKNOWN records are not modified.

Even an exact match closes only this fixed-input, fixed-runtime N256 warm-1
candidate/oracle boundary.  It does not qualify later cycles, arbitrary
histories, N512, finite-domain coverage, full-network training, equal-budget
task benefit, asynchronous cost, C2 full replay, HPCA external custody or
production adoption.  Global HOLD and `all_closed=false` remain.
