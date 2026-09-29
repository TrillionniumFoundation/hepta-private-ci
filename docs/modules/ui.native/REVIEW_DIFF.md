# ui.native ordinary-source review map

The review object is a normal Git commit chain. No source archive, compressed
patch capsule or workflow-generated future tree is part of the candidate.

## Commit chain

| Role | Commit | Review scope |
|---|---|---|
| pre-storage baseline | `9213ff850d3dd91f8734ec954e1e5981db3480fa` | picker handle materialization and prior native candidate |
| WAL/index source | `4bc29cf124dc5532d04349e478bc82f5d4959fd9` | exact active index, journal-v7 WAL/checkpoint, retirement-v3 disk index, recovery tests and pressure presentation |
| frozen implementation source | `0ef8638eaf7c4ae733ac2d10eba67d9308ef7e17` | remove 16 self-mutating workflows, add one read-only qualification chain, declare storage budgets, harden platform launcher path/environment |
| metadata continuation | current review head | align technical/development docs, delivery state, implementation map, branch-protection contract and pending qualification manifest |

## Recommended review commands

```bash
git diff --stat 9213ff850d3dd91f8734ec954e1e5981db3480fa..0ef8638eaf7c4ae733ac2d10eba67d9308ef7e17
git diff 9213ff850d3dd91f8734ec954e1e5981db3480fa..4bc29cf124dc5532d04349e478bc82f5d4959fd9 -- apps/hepta-native/src
git diff 4bc29cf124dc5532d04349e478bc82f5d4959fd9..0ef8638eaf7c4ae733ac2d10eba67d9308ef7e17
git show --stat --oneline 0ef8638eaf7c4ae733ac2d10eba67d9308ef7e17
```

Review storage in order: journal invariants and exact index; frame durability;
WAL replay/checkpoint cut points; retirement authority versus acceleration;
migration/corruption/partial-tail tests; UI pressure and UNKNOWN presentation.

Review platform and CI in order: fixed executable identity and environment;
absence of apply/commit/push; exact-head checkout; ordered-parent merge;
Linux/macOS/Windows matrix; false release flags and pending evidence manifest.

The ordinary source chain establishes a reviewable implementation candidate. It
does not establish physical accessibility, million-record performance,
installed-package behavior, signing, deployment or release authorization.
