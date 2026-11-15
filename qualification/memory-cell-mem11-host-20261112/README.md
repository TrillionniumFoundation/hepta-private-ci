# Strict namespace host evidence

**HOLD / NoUpdate. The original hosted Ubuntu 24.04 failure remains open.**
This stage adds read-only environment observations and a setup-only diagnostic;
it changes no namespace, mount, network, capability, timeout or eight-test assertion.
The existing required job remains on Ubuntu 24.04 with all eight controls required.

## Source and validation

- Source parent: `5890d883cc3a34bfb063ffe3597e6b279ead2baf` (#6104).
- Source commit: `22ed45c4cd2c05d9ed3d01043714fcf553d8c1e0`.
- Complete source tree: `78f6d722385cf04d16deef61baf498932373d941`.
- Four recorder controls passed, zero failures/skips. These exercise missing
  policy files, bounded partial reads, missing-tool failure custody and refusal
  to overwrite an observation. They are not eight namespace controls.
- Repository `just fmt` completed after tests. Both Python ASTs match the tested
  bytes; Ruff and `git diff --check` passed. Original failed formatter setup
  (missing sparse-checkout working directory) remains in the archive.
- A local cloud-host probe failed closed with bubblewrap 0.12.0. It is not a
  hosted GitHub runner reproduction or an AppArmor attribution.

The workflow records read-only policy values, the process AppArmor label and
capability/Seccomp fields, bwrap bytes/version and an unchanged strict launcher
probe before the required tests. Permission errors and missing files retain
their original errors and UNKNOWN attribution. The diagnostic itself is never
counted as a required test or used to excuse an unavailable namespace.

## Actual ai395 diagnostic

One original durable runtime job `1a1ce39099e-2564-1594` succeeded, exit 0,
with complete durable stdout/stderr. The complete observed files and their
readback size/SHA-256 records are archived. No second diagnostic was executed.

| Observation | Recorded value |
| --- | --- |
| Python / kernel | 3.14.4 / 7.0.0-38-generic |
| bwrap | 0.11.1; binary SHA-256 `523da3e7399044be5163aee6f57a77a6bef7454376e28f0a0627920bae1b76b6` |
| AppArmor enabled | `Y` |
| Both unprivileged AppArmor restriction values | `1`, before and after |
| Parent UID / effective capabilities / Seccomp | 1000 / zero / 0 |
| Strict setup probe | EXECUTED; all six namespace identities differ from the parent |
| Probe inputs | sealed memfd; off context zero bytes; empty private home/cache/workspace |
| Policy/process snapshot comparison | before and after equal |

This establishes that restriction values of 1 alone do not explain the hosted
failure. It does not establish identical AppArmor profiles, kernels, namespaces
or runner authority. AppArmor audit attribution remains **UNKNOWN**.
The setup probe is separate from #6098's earlier eight-case run; it is not a new
8/8 test result, real-model call or scored memory-benefit episode.

## Original hosted failure retained

The archive retains the complete decoded job log from [job 130889681325](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43129457006/job/130889681325),
run 43129457006 attempt 1, source `47a907d9f8d0f8815ac537983f68f2783ba56e3c`.
Its original result is six passes, two failures, zero skips. Both actual
namespace cases fail before the actor with `Failed RTM_NEWADDR: Operation not
permitted`. No original attempt is rerun, relabeled or replaced.

[Ubuntu's primary explanation](https://ubuntu.com/blog/ubuntu-23-10-restricted-unprivileged-user-namespaces)
describes per-application AppArmor user-namespace policy. The error and general
documentation are insufficient to identify the original runner's specific
denial without its capability/profile/audit evidence. This stage disables no
AppArmor or kernel setting, installs no privileged policy, grants no capability,
shares no network and adds no alternate runner or weakened fallback.

Authenticated provider/owner/source authority, original provider recovery, causal
benefit, strong baselines, full costs and all inherited adoption gates remain
open. New-head hosted CI is required independently of this diagnostic.
