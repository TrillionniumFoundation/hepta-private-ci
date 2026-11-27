# Four additional historical workflow originals

This supplement preserves four historical workflows that remained in the active
workflow directory after the original 113-file archive was assembled. The
original 113-file custody manifest and all of its original byte streams remain
unchanged.

The source snapshot is commit `639f84c1aafa6fb5044b690ae21706a7782861ef`.
Each payload is byte-for-byte identical to its earlier first117 snapshot at
`3f40cc95c9fb7843dd1c4100aa42ad290832b498`. The adjacent
`additional4-custody-manifest.json` records Git blob IDs, modes, SHA-256,
original input heads, triggers, and review findings.

## Why these workflows are archived

All four workflows accepted pushes to specific historical branches. They had no
manual dispatch or scheduled trigger. That narrow trigger did not make them
mechanically disabled: on a matching event they could still perform their full
operations.

- `context-compiler-worktree-export.yml` used a self-hosted runner, checked out a
  mutable historical branch, packaged a worktree, and uploaded it with an action
  version tag.
- `desktop-commander-recover-20260925.yml` installed and launched a persistent
  connector on an operator host.
- The fleet and ROG recovery workflows could install or restart that connector
  through SSH and use `actions: write` to cancel specified workflow runs.

Their active paths are removed. Their full original contents remain under
`originals/.github/workflows/`, outside GitHub's active workflow directory.
This change does not execute them, authorize their future execution, replace
current CI gates, or grant any scientific or production qualification.

Only these four exact additional payload paths receive `-text` attributes to
preserve their bytes across checkouts. No formatter, spelling, or test exclusion
is added by this supplement.
