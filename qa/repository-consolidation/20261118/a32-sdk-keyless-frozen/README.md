# A32 SDK keyless frozen diagnostic

This directory retains the exact five-file postimage of ordinary commit
`9f1b330e90197d25e7524864d01129b28a0a3d44`, whose sole parent is
`a32d73f00cfc292ff1ed4ac5cef958ca9f238020`. The manifest records every original
Git blob, length and SHA-256. The retained workflows are outside the active
workflow directory.

The current SDK workflow already restores the repository download cache,
propagates a failed cquery even when it printed an executable path, and saves
that cache using the restore step's actual result. These repairs remain in the
current workflow alongside its later Python SDK and conformance improvements.

The original diagnostic is a distinct strict admission mode. It requires an
ordinary user, enabled user namespaces, a positive namespace limit, no active
AppArmor namespace restriction, and a successful bounded unshare probe. It
does not change host policy. The current diagnostic helper instead records
policy and staged output identities without claiming capability. These modes
are not interchangeable, so the original driver and source contract are kept
here in full rather than replacing the current helper.

The frozen driver requires exactly one child of its approved parent, four
specific added files, and one specific SDK workflow repair. It checks the tree,
index, raw file bytes, exact tool hashes and allowed Bazel arguments. A merged
main cannot meet that original source contract. To inspect or reproduce the
historical diagnostic, create a detached worktree at the original commit and
retain its original source guard and host admission checks. Its 120-minute
SDK build budget belongs only to that historical diagnostic; current workflow
budgets are unchanged.

This audit verified the five original blob identities, parent and tree pins,
SDK workflow before/after modes and blobs, source/tool manifest hashes, and
16 unchanged driver AST nodes. Twelve injected acceptance/refusal checks
covered namespace admission and exact Bazel command scope. They did not run
a real namespace probe, download tools, execute Bazel, or qualify native SDK
behavior. Existing native qualification remains pending.
