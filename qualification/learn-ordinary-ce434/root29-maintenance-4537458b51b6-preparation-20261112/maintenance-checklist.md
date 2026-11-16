# Final scoped maintenance — prepared command checklist

Status: prepared only. The execution source SHA/tree, worktree and evidence directory are intentionally unset. Root runs these steps only after the intended validation runs have actually ended.

## Commands

Run from the actual repository's `codex-rs` directory, in this order:

```sh
just fix --locked --offline -p codex-hepta-agentd -p codex-hepta-learning-ledger -p codex-hepta-learning-artifacts -p codex-hepta-intelligence-eval -p codex-hepta-neuron
just fmt --base be8adcbb5e9925f72e05330b8fb30509cba4544b
```

The original `fix` recipe is `cargo clippy --fix --tests --allow-dirty` plus the exact supplied arguments. The original `fmt` recipe calls `scripts/format.py`. Its default comparison is against HEAD, so a clean, already committed candidate can have no formatting inputs. The explicit base `be8adcbb5e9925f72e05330b8fb30509cba4544b` includes committed changes since that exact commit, plus local edits and eligible untracked files; the existing language/configuration scope rules still apply.

## Minimal evidence checklist

1. Before fix, save the actual HEAD, committed tree and complete NUL-delimited status; require the intended clean source. Keep earlier validation receipts pinned to their original source. Read back the original recipe/formatter pins before dispatch.
2. For each command, save exact argv/cwd, actual start/end/elapsed, direct terminal return code, and complete raw stdout/stderr with byte sizes and SHA-256. Unknown execution remains unknown. No kill, automatic retry, new budget or environment change is part of this checklist.
3. After fix, and again after fmt, preserve the full binary diff, changed/untracked path inventory and every actual changed source postimage. Include bytes, type/mode, size, SHA-256 and Git blob ID, with original blob pins or explicit absence/deletions. Preserve the fix postimages before fmt can rewrite them.
4. A dirty worktree does not change `HEAD^{tree}`. Keep the committed tree and the working-source postimage manifest distinct. If maintenance changes source, review and publish those actual bytes as a new commit/tree and read it back; if it changes nothing, verify the unchanged tree and clean status.
5. Keep both maintenance outcomes independently. A later successful fmt does not erase a failed fix. Prior tests remain evidence for their tested SHA; they are not silently transferred to a changed post-maintenance SHA. Do not invoke or schedule tests after fix/fmt.

## Original semantic pins

| Source | Git blob |
|---|---|
| AGENTS.md, especially lines 62–70 | faa57cc0db48123e1011f1eb47692cd3bbbcfc3a |
| justfile | a215a76cf407ace9715bca39c20497014e7dd4dc |
| scripts/format.py | d4eabe70b68605933240e9129245f7f4cccbde5d |
| scripts/just-shell.py | bb2db6ebc4312a301ee39d2793fde16289d046d8 |

All four were read completely and checked against their Git blob IDs during this static preparation. No H operation, command execution, source change or new validation pass occurred.
