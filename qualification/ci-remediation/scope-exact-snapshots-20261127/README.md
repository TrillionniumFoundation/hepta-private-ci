# Exact snapshots for blocking CI scope

Run 45920462546 at candidate `6e8e0efc562803464acc0d21af127250ec104879`
was cancelled during the initial full-history checkout. Scope selection and its
dependent checks did not execute. The observed fetch lasted approximately five
minutes; that timing alone does not establish the cancellation cause.

The scope planner compares two exact trees. It reads tracked files, Cargo
manifests and embedded source inputs at those revisions; it does not need their
ancestry. Fetch the pull request base and candidate separately at depth one in
the same repository, using the existing pinned checkout action. Push events
only fetch the exact candidate and continue to request full qualification.
Explicit identity checks reject a wrong candidate or a missing base before
scope selection. Complete snapshot blobs are retained; no partial-clone filter
or lazy network fetch is introduced.

The action remains pinned to `de0fac2e4500dabe0009e67214ff5f5447ce83dd`.
Its exact source reuses an existing matching Git repository, disables automatic
garbage collection, cleans and resets the worktree, and fetches an exact SHA
with `--depth=1 --no-tags`. Those operations retain the first snapshot's Git
objects. If directory preparation instead recreates the repository, the new
base-presence check fails rather than producing an incomplete scope.

Real local Git fixture controls compare full-history and shallow-snapshot
plans for source changes, removed dependency edges, renamed/deleted paths,
embedded documents, and push full scope. A missing-base negative control keeps
the dependency planner's full fallback and verifies that the scope CLI cannot
emit a successful empty plan. These controls exercise Git and the actual Python
planners; they do not execute the TypeScript action or establish runner transfer
time. Native checks retain their existing checkout and qualification policy.

The five-minute scope budget, all other job budgets, permission settings,
credentials policy, pinned action versions, full-repository fallback and strict
fan-in handling remain unchanged. Source/control qualification does not close
the original runner failure until the exact new source completes normal CI.
