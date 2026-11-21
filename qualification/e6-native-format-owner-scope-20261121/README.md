# Native Rust formatter owner scope

This proposal makes the native qualification workflow's maintenance formatter operate on the same six Rust crates already declared by its retained postimage guard. It preserves the default and global formatter modes.

Base: `72fb96148a3d12db0d3482f46ab0653f7353d532`, tree `8e90cff71a6bc5ccdbe85c1d9f50c03fe546a8f0`. The change is independent of the later lifecycle waiter candidate. It has not completed an end-to-end native qualification run.

The formatter executed that base checkout plus exactly the three reviewed, uncommitted candidate files. The published postimages include Ruff's actual layout changes. A later publication commit is not presented as an already executed native source.

## Problem and behavior

The original [#6858 daemon run](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44867872646) included historical Rust snapshots in its `just fmt --base` selection. A snapshot outside the maintained crates failed under the fallback Rust 2021 edition; other snapshot edits were rejected by the existing postimage owner guard. Those original failure records remain preserved in [#6859](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6859).

The new repeatable `--rust-owner` mode first expands configuration impact, then intersects the resulting Rust paths with explicit crate boundaries. It dispatches only the Rust formatter group, preserves the original Cargo edition/toolchain resolution, and rejects invalid owners, owner aliases, symlinks and resolved source escapes. Formatter failures remain failures. Default and `--all` groups retain their previous implementations.

The native workflow defines one fixed six-crate `RUST_OWNERS` tuple. Both formatter arguments and retained postimage validation use that tuple and component-aware path comparison. No historical evidence, ignore rule, allowlist, edition fallback, test selection or native budget is changed.

## Actual verification and cost

The original formatter-control suite ran once before formatting: **31 tests passed**, including all 25 existing tests and six added controls. The added controls cover committed/untracked inputs, nested retained snapshots, prefix lookalikes, root configuration expansion followed by intersection, symlink escapes, invalid CLI scopes, actual subprocess failure propagation, and zero dispatch for exclusively unowned changes. The original 25 method ASTs remain identical.

Root launched the single approved format owner on ROG: job `1a1fcaeb9ac-ffbe-1df0`. `/home/qian-qi/.cargo/bin/just fmt`, from the isolated checkout's `codex-rs`, exited **0** in **0.677171626 seconds**. The whole owner took **32.274156465 seconds**, including **24.972300111 seconds** to prepare and identify the frozen Ruff dependency. These times are nested; they must not be added together. CPU affinity was `[0, 1]`.

The actual registry dispatched Ruff **0.15.13** for two Python scripts. Ruff changed only the new tests' layout; both Python ASTs remained identical. The workflow YAML had no registered formatter and its bytes remained identical. `just` **1.58.0**, `uv` **0.13.9**, and the actual Ruff binary were hashed before and after and remained unchanged. The command's successful child output is suppressed by the repository formatter; empty raw outer stdout/stderr are preserved as observed.

All 23 preparation/format/read-only verification commands exited zero without timeout. There was **one format attempt**, no test rerun after formatting, no new native/model execution, and no Rust build. The original failed CI is not reclassified by this local format success. Total physical network bytes were not measured.

`SUMMARY.json` binds the three actual post-format source hashes, tool identities, costs and scope. The archive includes the original 31-test logs, all **51 host receipt files**, three independently read formatted sources, complete outer logs/status, the 16,559-entry baseline index, exact launch inputs, and an independent AST/path review index. There are **78 members** in total; launch and local review documents are identified separately from host originals.

## Restore and review retained evidence

The two parts are actual binary Git blobs, each at most 360,000 bytes. They reconstruct a new locally assembled evidence container; this is not represented as an original host-produced tar. Every member's exact size and SHA-256 is listed in `MANIFEST.json`. No archived script needs to be executed to review the results.

```sh
cat FORMAT_EVIDENCE.tar.gz.part000 FORMAT_EVIDENCE.tar.gz.part001 > FORMAT_EVIDENCE.tar.gz
sha256sum FORMAT_EVIDENCE.tar.gz
tar -tzf FORMAT_EVIDENCE.tar.gz
```

The reconstructed container is **684,487 bytes**, SHA-256 `09e8768a11795378927d23b5eaab98d39908d6a211128fa8f9f24597a83b8912`. Inspect/extract into a fresh directory and compare the listed member hashes. `review/STATIC_POSTIMAGE_REVIEW.json` indexes the unchanged original helpers and test methods, shared owner constant, and formatter-before/after AST identities; it is a read-only structural review, not a formal proof or another test run.
