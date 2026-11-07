# Execution limit evidence and accounting scope

The original runtime request specified CPUQuota 200%, MemoryMax 12 GiB, nice 10,
and a 330-second supervisor timeout. Its immutable launch response is retained
in LAUNCH_RESPONSE.json; it identifies the systemd backend, job and request
digest. It does **not** return effective cgroup limits. Those cgroup settings
are requested limits, not independently read-back verified limits in this packet.

The executed supervisor source sets RLIMIT_CPU to 180/181 seconds per child,
uses a 60-second Torch-test timeout and a 240-second model-child timeout, and
sets OMP/MKL thread counts to two. The actual probe sets Torch threads to two.
The terminal runtime state confirms no timeout or automatic retry.

EXECUTION.json measures each complete child process. Probe stage meters sit
inside the model child; adding them to the child envelope double-counts work.
The original Torch test child and model child are distinct costs. Final-source
Torch verification has its own separate execution receipt and is additional
verification expenditure, not a second model trial.

Energy, effective cgroup readback, prior acquisition, tool dispatch, remote
transfer and total study expenditure are not fully measured. No nine-category
deployment invoice or net-benefit claim can be derived from this CPU-only probe.
The local focused regression and source reviews are additional research work;
their complete physical expenditure is also not present in the probe envelope.
