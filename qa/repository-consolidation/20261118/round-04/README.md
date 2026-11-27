# Round 04 branch and merge-gate repair

This stage continues the ordinary Rust consolidation in PR #6293. The preceding
published candidate is `86d4c92a89d1d4b0388a3b0a8f28280348105274`; its source is
`f571db956745d0702baba6da800b6c923aed34cc` and its source tree is
`8b7633e92ff38bbbd6f5b4d1f7449e532f287b4e`.

## Complete current branch census

The read-only GitHub branch census contains 7,498 names: 7,239 ordinary names,
258 protected HIA/Cell names and main. Four new Cell research branches are
protected by their actual PR changes and ancestry even though their names do
not contain `hia`. The protection set includes 265 historical/current pins and
the two established lineage markers. The ordinary ancestry graph has no
intersection with those pins or markers. See `protected-branch-audit.json`.

At the recorded source, 2,029 ordinary names are ancestors and 5,210 remain
outside the candidate. Those pending names represent 4,962 distinct heads and
1,804 independent frontier heads. Every pending head was examined against its
merge bases using path, file mode and blob identity; there were no unreadable
heads. `structure-summary.json` records the categories. A different postimage
requires source review; these counts do not assert that Git reports a conflict
or that the different implementation is incorrect.

## Six histories with already-present changes

The six heads recorded in `already-present-history.json` add seven ordinary
branch names to ancestry. Three heads have identical final mode/blob entries
for every changed path. Three more retain their complete original changes
inside later edits: independent-index reverse application and forward replay
restore every one of the 31,257 source index entries exactly.

The coordinator additionally ran native `git merge-tree --write-tree` for
each of the six heads. Every merge completed without conflicts and returned
the unchanged source tree `8b7633e92ff38bbbd6f5b4d1f7449e532f287b4e`.
These original commits are included as parents. No source choice is hidden by
a blanket conflict-resolution strategy. After this stage, recorded ordinary
coverage is 2,036 names, with 5,203 still pending.

## Formatter repair

The full and changed-file formatter both classified evidence named
`BUILD.json` as Starlark because of the `BUILD.` prefix. The shared selector now
keeps JSON metadata out of buildifier while preserving actual BUILD,
WORKSPACE, MODULE and Starlark file handling.

The 26 formatter-scope tests passed, including a regression that uses real
Git-tracked metadata alongside actual Starlark inputs and checks both full
and scoped command selection. `format-scope-tests.txt` retains the original
output. Repository `just fmt` subsequently completed without additional
source changes. An initial formatter invocation had an incomplete executable
PATH and could not find `uv`; restoring the existing runtime PATH resolved
the invocation without installing or changing tools.

## Continuing work

The resident-Root failures and remaining Chrono dependency migration are
being repaired and validated separately. The two required checks,
`CI required` and `Architecture required`, remain required for final merge.
This intermediate stage neither changes main nor deletes a branch. HIA/Cell
refs, their PRs and their source contents remain outside this work.
