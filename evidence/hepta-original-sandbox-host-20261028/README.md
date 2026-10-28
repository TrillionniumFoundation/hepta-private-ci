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

## First actual matrix and exact-version prerequisite repair

Run `40621425121` at `80ce9e5a95e8f2195f82276cddc29068eebc03af`
did not qualify a new host. The Ubuntu 26.04 job `122596121738` failed before
the probe: setup-python has no exact 3.12.3 build for that operating system.
Its finalizer then also lacked OUT because evidence initialization happened
after runtime setup. The Ubuntu 24.04 job `122596122007` reached the original
probe and failed. Both complete job logs are retained unchanged in gzip form;
neither failure becomes a pass in this successor.

The successor initializes the evidence directory and source identity before
runtime setup. Ubuntu 24.04 still uses the original setup-python step. Only
Ubuntu 26.04 builds exact CPython 3.12.3 from the official
[source release](https://www.python.org/downloads/release/python-3123/), under a
new, separately recorded 420-second build budget within the unchanged 600-second
job. Configure, make and installation use the existing command owner and retain
their real terminal record. The build is installed in the job's temporary
directory; the system interpreter is not replaced.

The 20,625,068-byte source archive has SHA-256
`56bfef1fdfc1221ce6720e43a661e3eb41785dd914ce99698d8c7896af4bdaa1`.
The actual official download matches the release-page MD5 and the SHA-256 digest
inside the official Sigstore metadata. The metadata and source-pin record are
retained; no independent Sigstore signature verification is claimed. Every
hosted download must match this exact size and SHA-256 before extraction.

The new build must report version 3.12.3 and import the SSL, compression, ctypes
and SQLite modules. Its executable hash and version are retained. It is an
explicit source build on 26.04, not a claim of byte identity with the 24.04
prebuilt interpreter. The unchanged host-resource and sandbox checks run only
after that exact-version prerequisite succeeds. AppArmor requirements, namespace
flags and the 0.5-second probe budget remain unchanged.
