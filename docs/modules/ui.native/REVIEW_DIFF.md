# ui.native ordinary-source review map

The review object is a normal Git commit chain. No source archive, compressed
patch capsule, apply-once workflow or workflow-generated future tree is part of
the candidate.

## Frozen implementation chain

| Role | Commit | Review scope |
|---|---|---|
| canonical review base | `6f145464d9d58233c59aafe262a1250a5ea873a8` | target branch identity used as ordered parent 1 |
| WAL/index source | `4bc29cf124dc5532d04349e478bc82f5d4959fd9` | exact active index, journal-v7 WAL/checkpoint, retirement-v3 disk index and recovery tests |
| exact-source convergence | `3e7274e8b87fbacbe0a91d076e62d21b08e02a8f` | one read-only qualification graph, storage budgets and ordinary-source cleanup |
| portal/resource boundary | `23d20707aebcdf8e5646d2bc3d74fd6751ec83d9` | portal-first picker, verified Linux resource identity/FD handoff, absolute launchers and Windows identity/WinRT adapters |
| lanes and persistent paging | `172fb1edaa5471c7cb28e14582c2b2a2dc1ff6f3` | picker/read/mutation lane split, shutdown join and 64-record durable history pages |
| frozen product implementation | `bfa63c9aec5f1cdc6c3a8b554cbaaabf11676f52` | closed unsigned package inventory with Windows AUMID registrar and portal declarations |
| qualification metadata continuation | current PR head | state anchors, technical/development docs, source-freeze tests, SBOM/provenance sealing and pending evidence manifest |

The immutable implementation tree is
`136c62bfe0cc0ca6c7455169162c3f5a1b951f8a`.

## Recommended review commands

```bash
git diff --stat 6f145464d9d58233c59aafe262a1250a5ea873a8..bfa63c9aec5f1cdc6c3a8b554cbaaabf11676f52
git diff 6f145464d9d58233c59aafe262a1250a5ea873a8..bfa63c9aec5f1cdc6c3a8b554cbaaabf11676f52 -- apps/hepta-native/src
git diff 23d20707aebcdf8e5646d2bc3d74fd6751ec83d9^..23d20707aebcdf8e5646d2bc3d74fd6751ec83d9
git diff 172fb1edaa5471c7cb28e14582c2b2a2dc1ff6f3^..172fb1edaa5471c7cb28e14582c2b2a2dc1ff6f3
git show --stat --oneline bfa63c9aec5f1cdc6c3a8b554cbaaabf11676f52
```

Review in this order:

1. journal/WAL transitions, fsync/checkpoint cut points and recovery;
2. retirement authority versus rebuildable index acceleration;
3. Linux path identity binding and exact FD handoff;
4. portal request observation, bounds and explicit Zenity compatibility;
5. single mutation authority, read/picker lanes and shutdown ownership;
6. bounded persistent history pages;
7. Windows shortcut/AUMID registrar and WinRT adapter;
8. deterministic package inventory;
9. exact-head/ordered-parent subjects, storage budgets, SBOM/provenance binding
   and permanently false release flags.

The ordinary source establishes a reviewable implementation candidate. It does
not establish physical accessibility, visible portal/notification behavior,
production signing, deployment or release authorization.
