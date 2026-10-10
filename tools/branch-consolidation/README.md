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
The program never replaces source trees, resolves conflicts, changes protection,
or treats ancestry, a successful cleanup, or a CI job as source qualification.

Run `python3 -m unittest -v test_hepta_branch_consolidation.py` in this directory.
The CLI defaults to no action unless `plan` or `apply` is supplied; `apply` also
requires the independently retained SHA-256 of `plan.json`. Backup artifact
retention is 30 days. Preserve the bundle elsewhere before its artifact expires
when a separate long-term backup is required. Historical objects also remain in
`main` ancestry. A deleted name can be restored using the exact branch/SHA pair
in `plan.json`; the bundle contains `refs/remotes/origin/<original-name>`.
