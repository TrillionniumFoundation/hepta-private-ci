# Verified branch retirement

Repository administration for the explicitly requested consolidation of
`TrillionniumFoundation/hepta-private-ci`. The only development authority is
`docs/DEVELOPMENT.md` on `main`; this directory is not a second development plan.

The workflow attempts the default-branch change once with its own runtime token.
A permission refusal is not bypassed. The live default and `main` are never deleted.
It freezes all branch heads, reports unmerged deltas and real Git merge previews,
and verifies and uploads a full Git bundle before attempting any deletion.
Only a frozen, unchanged head already retained by `main` is eligible. An explicit
per-ref lease and an atomic push reject races or server protection failures.
Unmerged, newly created, or advanced branches remain for content-level review.
Inventory uses Git's complete ref advertisement and has no 1,000-branch cutoff.
The checked-in `protected-branches.json` excludes the native HIA branches,
their descendants (including branches without HIA in their names), and the
supporting base of the open HIA/Cell PR. Its v2 policy retains historical commit
pins, previous named tips and freshly observed HIA tips as ancestry seeds. Exact
names remain protected when their heads advance beyond the recorded observation. Update the explicit manifest from
current branch/PR evidence before planning; a missing ancestry object stops the
operation. `--protected-manifest` selects the planning manifest, which is frozen
inside the digest-bound v3 plan and rechecked at apply. One complete parent graph
classifies all branch tips; shallow, grafted, incomplete or unordered history is
rejected, and Git replacement objects are disabled. Older policies and plans
are rejected.
`singleRustMainRefVerified` permits those protected refs to remain; the separate
`singleMainRefVerified` still means that only `main` exists remotely.
The program never replaces source trees, resolves conflicts, changes server protection,
or treats ancestry, a successful cleanup, or a CI job as source qualification.

Each retained plan directory permits one application attempt. Before any deletion, an exclusively
created `attempt.json` records the exact deletion names and SHAs plus the
updated `protectionManifest`, including HIA tips first observed during apply.
The file is flushed and synced, with its parent directory also synced on POSIX.
An existing attempt marker, including an incomplete one without a final receipt,
refuses another mutation attempt. Reconcile uncertain outcomes by reading the
remote refs and retained records. Further cleanup requires a fresh complete plan
whose protection policy retains the preceding attempt's observed names and pins,
alongside newer HIA evidence. Do not remove the marker or discard its protection
observations to retry. The final receipt includes the same observed policy.

Run `python3 -m unittest -v test_hepta_branch_consolidation.py` in this directory.
The CLI defaults to no action unless `plan` or `apply` is supplied; `apply` also
requires the independently retained SHA-256 of `plan.json`. Backup artifact
retention is 30 days. Preserve the bundle elsewhere before its artifact expires
when a separate long-term backup is required. Historical objects also remain in
`main` ancestry. A deleted name can be restored using the exact branch/SHA pair
in `plan.json`; the bundle contains `refs/remotes/origin/<original-name>`.
