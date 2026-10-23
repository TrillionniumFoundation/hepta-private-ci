# Historical module source origins: 2026-10-01

These seven immutable snapshots preserve the complete implementation maps from
`a126987b84737dbc2ee2592442a314117bddb4a2` (tree
`a22fd0074c45ae6f3cef2092cd6e273bf9c26c30`). They are historical navigation
records and grant no execution, qualification, acceptance or release authority.
Do not regenerate or replace these snapshots when current source observations
change. Each current map binds its archive by path and exact Git blob SHA.

The existing strict validator correctly rejected their old `sourceBase` values:
the commits exist and their recorded trees match, but they are not ancestors of
the integrated main baseline. `observedAtHead` alone cannot rescue such a source
base. The ancestry requirement and existing negative regressions are unchanged.

## Observed history

The repository is not shallow. Both lines share merge base
`7ddbfac88525196e7a4b31387ceae194958275f5`. The historical side line orders these
real commits as follows; each forward ancestry test returns 0:

1. `22cd31ebf4f36e4e6e1582b768fc8c847040acdb`
2. `41b2da214f5541da09e0313e7b8576add6ed3839`
3. `1133f7e5a5afd348e6fbed5694144572dda59a9a`
4. `55e8b38debd6333f376b77889e689c9b4825b9e8`

The main line has `a126987b84737dbc2ee2592442a314117bddb4a2` immediately after
the shared base. Each of the four side-line commits returns 1 for
`git merge-base --is-ancestor <side-commit> a126987b84737dbc2ee2592442a314117bddb4a2`.
That result means non-ancestry; it is not a missing-object or shallow-history
error. The main commit subject includes `#1000`. A squash integration is inferred
from this graph and content, rather than asserted as an ancestry relation. The
entire `55e8b3…` to `a126987…` tree diff consists of 12 metadata lines in
`docs/modules/control.engineering/IMPLEMENTATION_MAP.json`.

## Baseline byte observations

The existing `evidence_paths` inventory covers source roots, tests, callers,
delegates and the technical guide. Comparing each map's prior observation (or
source base where no observation existed) to the integrated baseline produces no
changed path in that canonical inventory. All explicit `sourceObjects` recorded
in the original maps also match the actual baseline snapshot objects.

| Module | Prior canonical observation | Canonical evidence paths | Explicit source-object entries |
|---|---|---:|---:|
| `automation.taskflow` | `41b2da…` | 15 | 15 |
| `objective.compiler` | `41b2da…` | 17 | 17 |
| `cognitive.read` | `41b2da…` | 23 | 27 |
| `learning.ledger` | `41b2da…` | 26 | 26 |
| `learning.artifacts` | `22cd31…` | 17 | 17 |
| `control.engineering` | `55e8b3…`; original source base `1133f7…` | 31 | 31 |
| `utility.ndu` | `22cd31…` | 22 | 22 |

`cognitive.read` has four additional explicit source-object paths outside the
canonical inventory. Three are unchanged; `scripts/hepta-implementation-maps.py`
changed between its old observation and the baseline. The original map already
records that script's actual baseline blob. Its archive records this distinction:
canonical evidence equality does not claim that the extra script was unchanged.

These observations apply to the integrated baseline, not subsequent Agentd
changes. Later changes to mapped callers and tests still require the official
strict migration and current-candidate verification.

## Field mapping and authority

- Each wrapper retains `originalMap` in full, its baseline Git blob SHA, original
  source base and old observation. Nested roles, custom receipts and claims are
  historical snapshots; none become current execution evidence.
- Current `sourceBase` now names the actual integrated baseline and its exact
  tree. Existing `observedAtHead` fields initially name that same baseline.
  Existing `sourceBaseRole` fields describe the new source observation after
  squash; the previous integration role remains in the archive.
- `historicalSourceOrigin` binds the archive path/blob and original map snapshot.
  `learning.ledger` and `utility.ndu` retain their previous `currentSourceEvidence`
  as explicitly historical `historicalSourceEvidence`. `cognitive.read` similarly
  labels its old reviewed base as `historicalObservedImplementationBase`.
  `control.engineering` keeps its original integration baseline with a historical
  role, separate from the current source observation.
- `objective.compiler` re-observes its module and product-composition source
  candidates using `git log -1 --format=%H -- <registered paths>` and the actual
  commit tree. This produces source navigation identities, not test receipts.
- Current boolean claims are unchanged. Source blobs/objects and generated
  indexes must subsequently be refreshed by the official migration, followed by
  strict exact-candidate verification. Successful source verification does not
  establish product execution or independent qualification.

No Git parent was added, no historical commit was rewritten, and no ancestry
validator was relaxed. The original provenance remains independently inspectable
without pretending that the side line is an ancestor of current main.
