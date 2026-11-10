# Common pin-utils native Windows evidence

This evidence-only follow-up preserves the original qualification of source
559809452a3b4524a8edeeb4ec38af665231f4dd from draft #5691. It does not change that
source, its two dependency locks, its workflow, or the advisory policy.

- Native run: https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42785602290
- Native job: https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42785602290/job/129725902195
- Original artifact: 13749607412, 1,940,982 bytes.
- Original ZIP SHA-256: b25d912f46be8cfaed928147c115f6d6ad9f66dc8ef4a949fc8c9e9cdbebde79.
- Initial workflow-validation failure: https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42785266988 .
  It scheduled no jobs; the runner-path binding was corrected before this qualification.

The original ZIP is unchanged. Its 67 hash-manifest entries were independently
verified. All 26 recorded commands exited zero. The full all-features locked
metadata contains 1,512 packages and 1,512 resolve nodes, with no pin-utils.
Patched aws-config 1.12.0 resolves to the existing vendored manifest. Observed
versions are Rust/Cargo 1.96.0, x86_64-pc-windows-msvc, just 1.51.0,
Bazel 9.3.0 and Bazelisk 1.28.1.

Both before/after locks are byte-identical. Required just bazel-lock-update and
just fmt exited zero, and the final worktree diff and status are empty.
The formatter reported no changed files requiring formatting; this does not
claim a new full-repository formatting or consumer-test result.

The retained job log preserves the exact UTF-8 bytes returned by the GitHub
connector's decoded-log endpoint, including its BOM. MANIFEST.json binds the
ZIP, log, verification report and policy replay. VERIFICATION.json is an
independent extraction/check of the original artifact, not a new native run.

The ZIP exceeds the unchanged 512,000-byte blob limit. Exactly one SHA-256/path
entry registers these immutable bytes in the existing asset allowlist.
The unchanged checker is replayed before and after that exact entry; the
original failure and successful constrained registration are retained.
The policy implementation and threshold are unchanged.

Only this scoped native Windows lock qualification passed. The other five
unsuppressed fatal advisories and the complete same-source consumer, platform
and security gates remain OPEN / HOLD. Evidence-head CI is separate and pending.
No new native commands, automatic dependency updates, commits, merges or
deployment were performed by the qualification workflow.
