# Pure PoN dependency proposal: source and acceptance contract

This is a lock-generation proposal, not native qualification and not closure of
all RustSec findings. The committed workspace manifest, `codex-rs/Cargo.lock` and
`MODULE.bazel.lock` are unchanged in this preparation. No local Cargo, Rust or Bazel
command was executed. Python control tests do not count as native verification.

## Reviewed candidates

| Existing graph | Proposed graph | Reason and remaining validation |
| --- | --- | --- |
| `ctutils 0.4.2` | `ctutils 0.4.6` | Both direct parents accept `^0.4`. Release 0.4.4 fixes the published timing issues; 0.4.5 adds Thumb-1 comparison/Choice hardening; 0.4.6 adds borrow-mask primitives. All are within the existing compatible dependency range. Native consumers still require qualification. |
| Workspace `zstd = "0.13"`, `zstd 0.13.3`, `zstd-safe 7.2.4` | Workspace `zstd = "0.14.3"`, one `zstd 0.14.3`, one `zstd-safe 8.2.0` | The fixed pair is already present through the workspace's `zip` dependency. The proposal must remove the old pair, not merely add a second fixed copy. The source uses ordinary fresh stream encoders/decoders; API compatibility remains a native-test question. |
| `aws-config 1.8.12 → p256 0.13.2 → elliptic-curve 0.13.8 → crypto-bigint 0.5.5` | Separate provider migration required | Published `aws-config 1.13.0` still requires `p256 ^0.13.2`. Its old curve requirements cannot resolve `crypto-bigint 0.7.x`. This blocker stays explicitly open in every proposal receipt. |

`upstream-versions.json` retains complete selected official index records, including
checksums, dependency ranges, release timestamps and yank state, at index commit
`2a8f22b30d18acd13913a6c2ecdcb105ed49cb18`. They are evidence for checking actual
solver output, not replacement Cargo or Bazel locks. `api-source-identities.json`
records hashes and official URLs for the inspected upstream implementation files.

The ctutils release source is
[`79275f704220fe32574c2a61973af40e4e1925b2`](https://github.com/RustCrypto/utils/commit/79275f704220fe32574c2a61973af40e4e1925b2).
The exact published `ctutils 0.4.6` archive checksum is
`fe3e9d21d39e6f39ff46e03d5b621424f88ee23d8a1672c6bfc9ccc7f2da4f6a`.
Its Rust 1.87 minimum is below this repository's pinned Rust 1.96.0. Choosing the
later compatible release retains the additional architecture hardening; it does
not assert any measured speedup or constant-time proof of the final binary.

The five original advisory records are
[RUSTSEC-2026-0385](https://rustsec.org/advisories/RUSTSEC-2026-0385.html),
[RUSTSEC-2026-0387](https://rustsec.org/advisories/RUSTSEC-2026-0387.html),
[RUSTSEC-2026-0391](https://rustsec.org/advisories/RUSTSEC-2026-0391.html),
[RUSTSEC-2026-0398](https://rustsec.org/advisories/RUSTSEC-2026-0398.html), and
[RUSTSEC-2026-0403](https://rustsec.org/advisories/RUSTSEC-2026-0403.html).
The graph findings are not evidence of five successfully exploited product paths.
No advisory is suppressed and no feature is removed.

## Explicit hosted generation

The independent workflow is `hepta-pon-rustsec-lock-proposal.yml`. Its restricted
pull-request trigger covers only this workflow, its proposal script/control tests,
and this evidence directory. Only opened, synchronized or reopened PR events are
accepted. The PR head must belong to this repository and explicitly not be a fork.
Both its base repository and PR event/ref identity are checked before checkout.
The checked-out source is the exact PR head SHA, not GitHub's synthetic merge SHA;
both identities are recorded separately. Existing qualification jobs are unchanged.

Optional manual dispatch accepts a required `source_sha`: the complete lowercase
SHA of the reviewed workflow branch head, matching the run SHA and checkout.
Dispatch and PR sources are mutually exclusive. Missing/short SHAs, dispatch
inputs on a PR, a PR source in a dispatch, foreign/fork repositories and mismatched
checkout identities fail. A tree-equivalent SHA from another publication is not
interchangeable. The ordinary PR update can trigger generation without requiring
registration of a new dispatch-only workflow on the default branch.

The workflow has `contents: read`, does not retain checkout credentials, passes no
secrets, does not push or create a PR, and does not change runner security policy.
It installs the pinned toolchain and tools, but requests no product build or test.
Its original Bazel lock recipes may run dependency-resolution tooling. Therefore
this is metadata generation, not a claim that no executable runs on the host.

The script refuses local execution before it can launch a Cargo or Bazel command.
It first requires a clean exact source, retains the three original files byte for
byte, and records their SHA-256 values. The only declared manifest mutation is the
single reviewed workspace zstd line. Finalization checks the entire resulting
manifest against those declared bytes, so unrelated feature changes fail even if
they occur in the same allowed file.

Commands are fixed and sequential:

1. Record the actual Cargo, Bazel and just versions.
2. In `codex-rs`, run `cargo +1.96.0 update --package ctutils --precise 0.4.6`.
3. In `codex-rs`, run `cargo +1.96.0 metadata --locked --all-features --format-version 1`.
4. At the repository root, run the original `just bazel-lock-update` recipe.
5. At the repository root, run the original `just bazel-lock-check` recipe.

The manifest change is made before resolution. Cargo, not this script, chooses
and checksums the graph. The proposal reviewer must confirm the exact intended
target versions, absence of duplicate vulnerable zstd wrappers, the unchanged
`credentials-login` feature and all unrelated resolver changes. The finalizer
fails if selected package checksums differ from the reviewed registry records.
It rejects any tracked modification outside the manifest and both locks, staged
changes, and new untracked checkout files.

## Failure, interruption and artifact interpretation

The resolution step has a 35-minute budget. The job has a 75-minute ceiling, with
smaller bounded setup, finalization and upload steps to reserve an artifact window.
The script never kills native processes by PID. Every started command gets its
raw stdout/stderr files and a persisted `running` record before execution. An
ordinary failure retains its actual return code and prevents later commands from
starting. GitHub interruption can leave a stage with unknown exit status; that
stage remains unknown, and later commands remain `not_started`.

Finalization and artifact upload use `always()`. A runner loss or hard job-level
termination can still prevent artifact delivery; missing evidence must remain
unknown. The GitHub job log is also required when setup fails before command logs
exist. Neither a timeout nor a missing artifact can be reclassified as success.

The artifact name is
`hepta-pon-dependency-proposal-<run_id>-<run_attempt>` and retention is 14 days. It
contains originals, proposed files, a scoped binary patch, raw command logs,
`record.json`, and a SHA-256/size listing of every retained file in `files.json`.
It never archives a workspace, credentials directory, private key, or environment
dump. The proposed graph is still uncommitted and therefore the final clean-tree
qualification guard is expected to fail after successful generation. A red job
with `ready_for_review: true` is usable proposal evidence, not a passing CI gate.

## Applying a generated proposal

Retrieve the artifact from the exact expected run and attempt. Validate every
`files.json` entry, compare the recorded source SHA/tree to the published source,
and compare each original input hash to the corresponding source commit. Review
all resolver differences, including the full Bazel platform graph. Do not accept
logs from a different tree or an earlier failed attempt as replacement evidence.

Only an ordinary subsequent source commit may install the manifest and both
generated locks together. No checksum is hand-edited. The original native,
formatting, platform and RustSec gates must then run on that committed source.
The existing aws-config/P-256 blocker remains open even if the ctutils/zstd
advisories disappear. This preparation provides no assertion about throughput,
PoN consensus safety, PQ authorization, real Hepta improvement or WAN acceptance.

## Local control verification

Twelve Python control tests cover source/mutation boundaries, refusal of local native
execution, target registry identities, duplicate vulnerable packages, exit-code
and interruption accounting, and final artifact hashes. Ruff and actionlint also
pass. The exact local command results are recorded separately in
`local-control-verification.json`; these are control-script checks only.
