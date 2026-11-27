# Exact-head architecture failure diagnosis

Run [45434923531](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45434923531), source-head job `138608367061`, tested commit `fb00e4422c293ffb318c9d7535e1991a3bbac707` and tree `eb6786c562522c78b9f80c42fcaf7d24bd2bba45`.

The job completed with **failure**. Its earlier 21 recorded commands passed, covering repository-control rejection, inference and streaming digest, durable operations, retirement recovery, module generations and rollback, writer handoff, topology, plasticity, objective contracts, objective behavior, prompt optimization, and final-use linearization. The command records contain 465 positive test occurrences. They include overlapping package and selector runs, so this is **not a count of unique independent tests**.

The sole Rust compile error in the final command is E0433 at `codex-rs/app-server/src/request_processors/thread_summary.rs:190`: the production path uses `MultiAgentMode`, whose import was accidentally guarded by `cfg(test)`. Consequently the `browser_servo` selector executed **zero tests**. The existing fourth-candidate fix removes the erroneous test-only guards while preserving the mode value and all permission behavior. This is the same source cause observed in the Windows consumer compilation; it is not a new untriaged failure.

The full UTF-8 log is retained outside the source tree: 547,136 bytes, SHA-256 `399b5e970128c87515a983a69d2e8dd154f90d99af5fe977b8c0bf41224ae592`. The original CI reports artifact `14944097213` with ZIP SHA-256 `2e726962dec750fb506783d793c4a3568140a4c39a2c33522ccdeeea14ed88ab`. That artifact was not independently downloaded for this receipt; the diagnosis uses the complete job-log response.

The new import fix still requires execution at the new exact head. Later adoption, process-restart, and other dependent native stages were not reached. The base-merge job's successful condition-selected checks skipped its native build/test steps, so they do not establish native prospective-merge validation. No old-head rerun was requested.
