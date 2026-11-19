# Frozen snapshots and continuous-DDE Torch VJP

Status: **INTENT / HOLD for Torch**. The new Torch candidate has not executed.
It must not inherit Torch, larger-mesh, full-network, optimizer or restoration
qualification from #6246, #6241 or the independent snapshot controls below.

The pure snapshot-control stage used remote prefreeze
`3cc84fd2783d909bf0e430029a20de305dae03ca` before its only local run. Across
uniform N=7 and graded N=12 it corrupted identity, each of five coefficient
arrays' contents and read-only flags, query times, phase supports, delay and
discount: 30 public VJP rejection attempts, all rejected before reaching a
sentinel reverse solver. There were zero reverse/ODE/exponential/static/Torch
calls or optimizer updates. The original tested source, REQUEST, before/after
hashes and complete execution records are preserved in
`evidence/GUARD001-ORIGINALS.tar.gz`; its inventory and receipt are adjacent.
The published guard script was formatted with full AST equivalence and not
rerun. Use the original archive or prefreeze to reproduce that same request.

The distinct Torch candidate hard-admits N<=12. Its unchanged forward method
is `JointModel.solve`, called through a private adapter that supplies copied
actual Q/k/u/r/d/q and fixed time/support snapshots. It never builds a forward
basis map. Backward calls the #6246 continuous finite-DDE adjoint with the
actual incoming cotangent, rather than returning a cached Jacobian. This is
a numerical continuous-DDE custom VJP, not autodiff of adaptive BDF steps.

All four public live input tensors are saved with Torch version tracking,
cloned values and dtype/device/shape/stride/storage signatures. The backward
must reject normal in-place changes, unsafe `.data` value changes and unsafe
same-value storage replacement. Live caller metadata is checked only to
reject changes; the actual adjoint uses its forward-used immutable snapshot.
Internal snapshot corruption remains covered separately by the pure controls.

`TORCH-REQUEST.json` predeclares uniform N=7 and graded N=12, two signed-content
channels, fixed phase supports and times 0/.13/.29/.53 with delay .21. Its
CPU FP64 first stage has no optimizer. A genuine scalar Torch gradcheck will
perturb all 69 ambient input coordinates and retain high/low values and all
forward/backward journals. It also compares the full raw VJP and forward
outputs with retained independent basis data, and retains complete gradients
of an explicit softmax/probability-times-marks client. No normalization occurs
inside the raw amplitude API: its nonnegative finite probability measures
have the declared ambient signed linear extension.

Twelve input-mutation controls and eight caller-metadata controls must reject
before any adjoint call. These 20 native mutation controls use uniform N=7
through the shared bridge; no separate graded mutation suite is claimed.
The entire new probe is capped at 220 model forwards,
32 adjoints and one million recorded array scalars. The existing adjoint's
per-call caps still apply. The forward's 4096-step check is a post-solve check,
not a hard early termination bound; hosted execution has a ten-minute job
timeout. Stored payload caps are not RSS limits. The wrapper records complete
child-process time/CPU/RSS including imports and source admission.

Source, REQUEST and workflow are frozen remotely before the single new
PR-triggered hosted CPU admission. Until its authoritative result exists,
Torch runtime validation, all native guard controls and independent audit
remain OPEN. Adam updates/restoration are a later independent stage. Physics,
delay, supports, migration, broader tasks, N=128/512 and full-network training
remain unqualified.

Pre-admission static review found that a NaN call limit or a later raised live
limit could bypass the earlier ledger check. The source now requires exact
positive bounded integer limits and exact nonnegative integer counters, locks
the limits at admission, and independently checks the absolute 220/32 caps at
every forward/backward admission. This fix has no prior Torch runtime credit;
the native probe uses one controlled default ledger. The earlier source
revision is retained in Git and was never admitted.
