# ui.native ordinary-source review map

The review object is a normal Git commit chain. No source archive, compressed
patch capsule or workflow-generated future tree is part of the candidate.

## Commit chain

| Role | Commit | Review scope |
|---|---|---|
| pre-storage baseline | `9213ff850d3dd91f8734ec954e1e5981db3480fa` | picker handle materialization and prior native candidate |
| WAL/index source | `4bc29cf124dc5532d04349e478bc82f5d4959fd9` | exact active index, journal-v7 WAL/checkpoint, retirement-v3 disk index, recovery tests and pressure presentation |
| convergence source | `0ef8638eaf7c4ae733ac2d10eba67d9308ef7e17` | remove 16 self-mutating workflows, add one read-only qualification chain, declare storage budgets and harden platform launcher identity |
| Rust 1.95 normalization | `392c11672192d94afe8f878c2c94199e5be41ac4` | ordinary formatter delta for the reviewed platform source |
| frozen implementation source | `a417e5756d4dba18737b9d3e6aa8b13016c23662` | exact-source 4096-active/1,000,000-retired qualification harness, deterministic rebuild subject and syscall-derived durability accounting |
| metadata continuation | current review head | bind technical/development docs, delivery state, implementation map, branch-protection contract and pending qualification manifest to the frozen implementation source |

## Recommended review commands

```bash
git diff --stat 9213ff850d3dd91f8734ec954e1e5981db3480fa..a417e5756d4dba18737b9d3e6aa8b13016c23662
git diff 9213ff850d3dd91f8734ec954e1e5981db3480fa..4bc29cf124dc5532d04349e478bc82f5d4959fd9 -- apps/hepta-native/src
git diff 4bc29cf124dc5532d04349e478bc82f5d4959fd9..a417e5756d4dba18737b9d3e6aa8b13016c23662
git show --stat --oneline a417e5756d4dba18737b9d3e6aa8b13016c23662
```

Review storage in order: journal invariants and exact index; frame durability;
WAL replay/checkpoint cut points; retirement authority versus acceleration;
migration/corruption/partial-tail tests; 4096-active transition evidence;
one-million-retired indexed cold open and deterministic rebuild; syscall-derived
write amplification and fsync accounting.

Review platform and CI in order: fixed executable identity and environment;
absence of apply/commit/push; exact-head checkout; ordered-parent merge;
Linux/macOS/Windows matrix; immutable storage-scale artifact; false release flags
and pending independent evidence manifest.

The ordinary source chain establishes a reviewable implementation candidate. It
does not establish physical accessibility, installed-package behavior, verified
Open/Reveal resource handoff, portal/WinRT completeness, signing, deployment or
release authorization.
