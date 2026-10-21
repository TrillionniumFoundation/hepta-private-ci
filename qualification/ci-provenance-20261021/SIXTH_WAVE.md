# Auth, native acceptance, turn diffs, and actual runner execution

Source checkpoint `3ba1ea16cafb13be7ebe8a0e1733ced864860628` adds five separately
reviewed Rust groups to the previous continuation; `ef3857e3e` additionally
contains the two independently reviewed CI policy repairs below. These changes are prepared while
published source `48177153ad04605338c3a9a8dbd17defee9981bc` has real native jobs
running. Moving its branch would cancel builds under existing concurrency
rules, so updating that branch waits for those jobs to finish. A separate
continuation branch and PR can run its own original gates after checking that
its complete workflow invocation closure has distinct cancellation groups.
No job was killed or
required gate removed to create a publication window.

## Reviewed source changes

| Group | Defect and resulting behavior | Evidence still required |
| --- | --- | --- |
| WebSocket authentication | Capture one resolved authentication-header snapshot for both connection identity and the actual upgrade. A provider's opaque identity can stabilize rotating signatures while credential, account, task, routing, and other-header changes still force reconnection. Exclude root-turn correlation and the prewarm marker from connection reuse identity; preserve the original durable recovery projection and per-request metadata. Debug output remains redacted. | Original core, model-provider, and transport native tests. |
| SSHSIG verification | Replace the platform child-process dependency with bounded raw Ed25519 verification against the existing externally pinned signer. Enforce armor, field bounds, key and signature shapes, fingerprint, namespace, supported hash, and strict Ed25519 checks. Preserve principal, policy, lifetime and revocation validation in the existing trust owner. | Original acceptance Rust suite on each required platform. |
| Windows directory durability | Retain the same writable parent-directory handle across mutation and durable flush; validate directory identity before and after the flush and refuse reparse redirection. Existing write/rename/flush errors remain errors. | Real Windows execution of the existing and new directory tests. |
| Bedrock setup | Route the existing experimental RPCs through their guarded handlers. Use the actual AWS SDK credential chain for environment fallback, reject inherited command authentication, and replace editable command authentication together with provider/region/profile in one configuration transaction. Capability, forced-login, external-auth and global account-auth gates remain intact. | Actual app-server public JSON-RPC tests, including SDK loopback success and error responses. SDK credentials alone do not establish AWS service authorization. |
| Turn diff roots | Honor the existing cwd-relative feature. Select one display root per environment that covers all baseline/current paths; fall back to the repository root when a parent path is touched and invalidate cached headers on a root change. Feature-off behavior remains repository relative. | The original seven feature cases, both parent-path feature states, and actual apply-patch/cache regression under the core native suite. |
| Keyless Bazel CI | Keep shared CI options, including zero Rust debug information and keep-going behavior, when Linux/macOS cannot use credentialed remote execution. Retain the local disk cache, caller overrides and target/program argument boundaries. | Actual original Bazel analysis/build jobs. |
| Windows Clippy targets | Native MSVC lint selection excludes only the explicit GNU LLVM cross-bin helpers. Native, unit and unrelated manual targets remain; explicit cross mode retains its original helper coverage. Query failure propagates before a partial target list can be emitted. | The original Windows Clippy job. No global skip-incompatible switch was added. |

The original broad owner is #2961 at
`c210d26350ac57e527b4ff59663e5c8d518ff95a`; file groups are retained in
`sixth-wave/owner-review-groups.json`. Bedrock was additionally repaired in
`93f0d80e2bc191d7d79b62780aafc75a1d96995d`, and the turn-diff group in
`97dbdb200085d1d1adec5c9301ba0080a0522874`, before independent integration.
Other changes from that owner are not implicitly approved by these reviews.

The original `just test-github-scripts` suite passed all 106 executions on the
integrated source. The keyless policy tests produced nine failing assertions
against the original behavior; the native Windows selection test produced one.
The real shell wrapper's query-failure control still exits 37 without emitting
partial target coverage. `qualification/ci-policy-20261021` retains both failure
controls, the initially stale consumer assertions, all corrected suite results,
and formatter setup failures followed by the original formatter's success.
The root integration independently ran the original suite (106 executions). Its
full `just fmt --base 5088b49ccdc6e3c226d5dd041393cb7b9967d7c8` initially
failed because the native wrapper did not expose `uv` on PATH; after adding
the installed runtime binary directory, the identical command passed with the
locked cached toolchain. Both attempts and their exact source hashes are retained.
The discovery count retains its existing duplicate detector entry point.

## Independent SSHSIG oracle

`sixth-wave/verify_openssh_fixtures.py` invokes the installed OpenSSH executable
against the exact frozen Rust fixture bytes. All 12 expected outcomes passed:
SHA-256/SHA-512 signatures, a second independent key, legacy version zero and
ignored reserved bytes, plus unsupported version, wrong pinned key, changed
message/namespace/hash, altered signature and truncated packet rejections.
The receipt records command arguments, every exit code and complete output,
fixture hashes, OpenSSH version and executable hash. No signing key is stored.

The wire review also used the upstream [OpenSSH SSHSIG protocol](https://github.com/openssh/openssh-portable/blob/master/PROTOCOL.sshsig)
and [OpenSSH verification implementation](https://github.com/openssh/openssh-portable/blob/master/sshsig.c).
This independent oracle establishes fixture and wire compatibility. It is not
an execution of the new Rust verifier or a replacement for its native suite.

## Queue evidence and publication safety

The repository-scoped 10:34–10:35 UTC snapshot contains 365 workflow runs and
812 jobs. Job records show 178 actually running jobs, all with assigned
runners, and 154 queued jobs without assigned runners. Of the running jobs,
107 belong to workflow records whose top-level status still says `queued`.
Thus a queued workflow record cannot establish that no build is running.
There were 291 runs without any returned jobs at the individual observation
times. These responses are non-atomic and retain their timestamps.

The analysis reads exact source-head workflow YAML and API-referenced reusable
workflow sources before deriving concurrency groups. Resolved groups are
inferences from those inputs, not a concurrency field returned by the Actions
API. Historical events without sufficient PR metadata stay unresolved. The
snapshot does not inspect organization quotas or administrative runner data.

The continuation audit reads all 80 workflow files and the 18-workflow closure
reachable from ten PR entry points. Its retained declaration inventory confirms
that distinct head branches and PR numbers isolate this child from #2968's
running jobs. The global cancelling main group is not a PR entry point; other
global release/manual groups are not invoked by this child. No concurrency
declaration is changed to obtain that isolation.

All original queue responses, workflow-source supplements and analysis are
losslessly compressed and checked against `queue-receipt-1034.json`. This
captures the state at collection time; current job state must be reread before
the remote ref moves. Current-source/current-base required checks and
substantive review remain prerequisites to merge. Research remains
`SHADOW_ONLY / DENY_ALL / NO_GO`.
