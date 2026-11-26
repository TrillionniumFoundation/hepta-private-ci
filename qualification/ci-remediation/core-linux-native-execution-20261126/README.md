# Core integration test execution on the prepared Linux host

The GNU and musl jobs for source
`97ab00451799667faebac2c455a1e3176ebc90cb` failed the same Core integration
shard in [run 45732887025](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45732887025).
Both jobs checked out merge `4d0f8f3141501b94112020beca166eedc7694592`,
whose complete tree equals the source tree. The final Core failure log has
849,480 bytes and SHA-256
`bfb52dba9184cfd753ed025a4d5847339680cd90240f2298bb082f2dc9427317`.
Each of the three original attempts recorded 86 passed, five failed, one ignored,
and 1,335 filtered cases in shard 4 of 16. These are attempt counts, not separate
test populations. The two jobs share identical failed outputs and remote action
records; they do not establish independent GNU and musl reproductions.

Four failures explicitly report that bubblewrap cannot create a user namespace:
the apply-patch symlink-escape case, strict guardian network review, background
network denial, and workspace-root writes. Their intended operations could not
reach the boundary that their assertions exercise. The fifth, execpolicy amendment,
records only exit code 1 instead of 0; the same underlying cause is plausible but
unproven. The logs do not identify whether the remote namespace restriction was
permanent or transient.

Both existing jobs successfully prepared their Linux host with
`kernel.unprivileged_userns_clone = 1` and
`kernel.apparmor_restrict_unprivileged_userns = 0`. Their Core tests nevertheless
executed remotely. The preparation path is `prepare-bazel-ci` -> `setup-bazel-ci`
-> `setup-ci`; this change does not modify any of those actions or host settings.

The single `.bazelrc` rule routes only descriptions for
`//codex-rs/core:core-all-test` to the existing `sandboxed,local` strategy list,
following the operator trust test precedent. The target's existing `no-sandbox`
tag remains unchanged, so Bazel can select the local strategy. The target-name
boundary excludes Core unit tests, Wine variants, and similarly prefixed targets.
Compilation remains eligible for RBE. Test code, product bubblewrap confinement,
test selection, all 16 shards, original retries, timeouts, caches, runner matrix,
and resource settings are unchanged. No sandbox environment variable is changed.

Static review cannot qualify the new execution placement. A normal CI run must
record actual local execution and the complete Core test outcomes, retaining any
first-attempt failures. A cached success alone cannot establish that the new local
placement executed. The fifth original failure remains unconfirmed until its
real outcome is observed. This change does not qualify Windows DELETE protection
or model quality.
