# Preserve the original sandbox failure and qualify an unmodified host

The observed-execution candidate at `4c542f81a61a66531d219670545f8fd0e7149d29`
failed its actual original sandbox prerequisite in run
[40619831342](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40619831342),
job `122590897457`. Its command was exactly:

~~~text
bwrap --unshare-user --unshare-net --ro-bind / / /bin/true
~~~

The original 0.5-second command budget was retained. The child exited 1 without
a timeout. Its exact 61-byte log reports a loopback RTM_NEWADDR permission
failure. Before/after source identities match the same commit and tree
`4188be94692de3f4b4780ad073cc98ccc64d4511`.

This directory retains the original metadata-only ZIP, all 19 member hashes,
the full original decoded job log compressed without content changes, and an
independent readback of the actual result and raw command log. No model payload
is present in the original metadata artifact.

## Independent host capability experiment

The new workflow runs the same original probe independently on `ubuntu-24.04`
and `ubuntu-26.04`. GitHub's
[official runner catalog](https://github.com/actions/runner-images) lists both
images; its [26.04 image record](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2604-Readme.md)
identifies the available image. Availability does not establish sandbox
compatibility. The new 26.04 result is **NOT_RUN** at this source freeze.

Both lanes use the existing command owner, exact CPython 3.12.3, unchanged
12-GiB host observation gate, distribution bubblewrap installation, identical
namespace flags and the original 0.5-second probe budget. They additionally
require AppArmor enabled and its unprivileged-user-namespace restriction equal
to 1, recording those actual readbacks and the distribution profile hash when
available. The workflow changes no AppArmor profile, sysctl, privilege flag,
network-sharing flag or model acceptance rule.

Each matrix job retains its own result. The old-image failure is not reclassified
as success if another image passes. Only an actually successful host probe can
justify a later full native and model run on that host. This experiment runs no
model training, downloads no model materials, and grants no installation,
independent future-quality, resource-capacity or production qualification.

The resource helper reports visible observations and preserves its existing
`resource_capacity_qualified = false` boundary. The model's complete runtime
resource accounting is still required in the later full run.

The new workflow parsed as YAML and all four Bash blocks passed syntax checks.
Source, arguments and original failure evidence are bound in `readback.json`
and the publication manifest. Existing local executor controls remain at the
exact #4147 source that passed 77 tests; this workflow changes no Python code.
