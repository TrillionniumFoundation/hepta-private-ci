# Explicit original late-writer CLI entry

Status: corrected source candidate; supersedes the v1 candidate described below; static review and byte checks only. This candidate is based on `7666bcc2c650298f2e1d47e615a25864fe792fa1` (tree `7495444ffe639ad28ac64aad5cc68e70c097c4aa`). It has not been compiled, run through the original closed-caller verifier, or exercised as a Root component. Existing native results belong to their recorded source, not this candidate.

## What the entry connects

The existing `main.rs` calls `AgentdProductionStartup::from_process_environment`, receives its result, and eventually runs the ordinary `AgentdProductionLaunch`. This candidate adds an explicit `--root-production-entry late-writer` branch inside that existing Startup path. The default branch and `main.rs` are retained. The opt-in branch uses the same complete inherited-input parser, existing three-right writer purpose, original five-lane receive, Root-bound Config loader, optional original Learning/Model connections, and final live-session checks as the existing `receive_original_late_writer` API.

The entry is conditional on an actual host having supplied those capabilities. The repository already contains a production sender in `native_g2_entry/activation.rs::send_original`: it seals the original bootstrap, obtains the original writer descriptor, and calls `send_root_production_writer_handoff`. Its native PID-1 role pin is specific to that environment and is not copied into this entry. The default `hepta-authority-host` CLI still exposes its existing fresh two-right sender; this candidate does not add a three-right recovery sender to that CLI.

## Authority and startup order

1. The new selector recognizes only an explicit flag/value pair. An absent selector leaves the argument bytes and existing parser behavior unchanged. Duplicate, incomplete, or unknown entry selection is rejected before descriptor ownership is taken.
2. During single-thread arg0 preparation, the existing parser takes the actual inherited descriptors exactly once. It rejects incomplete and aliased rights as before. The actual process UID/GID must match the original dedicated recipient. The session deadline is captured once at this point.
3. A private read-only helper derives expected comparison data from the existing Supervisor environment and original Fleet registry. It requires the exact current `Starting` generation, canonical fleet/home/run/CODEX_HOME/workspace paths, and registered resource values. It does not acquire the writer, construct Config, rotate a lease, transition Fleet, or issue an authorization.
4. The first runtime consumes those same retained descriptors and the same absolute deadline. The original three-right receive and five-lane receive establish authority. The original Root-bound Config loader independently checks the registered identity and writer grant. Original sender/process binding and live-session checks remain at the end.
5. Existing main and Launch execution still require all their actual Primary, application, socket, and readiness inputs. The explicit entry never falls back to the fresh two-right or ordinary path after failure.

The old receive body from `let (bootstrap, root_pidfd, writer)` through its final live check is 3,679 bytes and byte-identical in the new shared consumer. Its SHA-256 is `290ff576c04c02ee62507d8162241b0661706a41df3b2eeae574dbbafed1250b`. The original UID check and remaining-deadline helpers are also unchanged. Moving parsing into the retained typed input preserves the single-thread descriptor boundary; no raw descriptor round-trip or second parse is introduced.

The existing public `receive_original_late_writer(arguments, expected)` signature and return type remain available and delegate to the same implementation. Its external caller inventory remains empty. The actual CLI path is represented by four new closed boundaries for preparing and consuming the private input and Startup types. A same-file delegation is protected by function-order checks, not mislabeled as an external caller.

## Correction: original filesystem custody and genuinely read-only comparison

The first draft (`d56a052f60bfc5fe3b5c5b45570bf85397464985`) used `FleetRegistry::open_existing` for the expected-identity read. That description as read-only was wrong: the original constructor invokes `migrate_legacy_matrix_roots`, which may create missing Matrix directories or apply private permissions and directory syncs even before writer admission. The old candidate and its review remain historical evidence; that read-only conclusion is withdrawn.

This corrected candidate introduces `FleetRegistry::read_existing_snapshot` in a small private Registry child module. It constructs only the internal path view, performs the same original five control-directory physical checks, then calls the unchanged complete `load`. The caller receives a `FleetSnapshot` data value, not a writable Registry. Missing or unsafe Matrix paths are refused, with no migration, chmod, initialization, fallback, writer lock or lifecycle transition. The original `open_existing`, migration, Config load, and all existing Registry methods are unchanged. The explicit entry's three-right-to-five-lane sequence is unchanged.

A legitimate non-Root Config deployment also needs the original filesystem read custody. The existing `root_agentd_filesystem.rs` handoff (`3ff802ccbf081df5a4e85db40fd98cfa2151d762`) explicitly gives the dedicated group read/search access to Root-owned Fleet/control directories with mode 02750 and to original manifest/lifecycle/release records with mode 0640. The writer remains Root0600 and is obtained by its original descriptor. Existing `preserve_root_reader_mode` in Registry (`cadd646638f8393652b03d70be57b89c55e7da29`) preserves that read-only mode for subsequent immutable Root-owned control generations under those exact parents.

Those existing provisioned permissions are prerequisites, not changes made by this CLI. A Root-private or merely search-only fixture is rejected if the original snapshot cannot be read. The five-lane Root17 fixtures that only expose outer paths with 0710 are not evidence of a complete Config/Launch deployment. No permissions are broadened by this candidate to make them pass.

## Source and verification scope

The corrected candidate changes ten Rust paths and `CALLERS.toml`; five Rust files are new. A pure-text line comparison reports 555 added and 11 removed Rust lines. This is an estimate from line LCS, not a Git or compiler result.

The metadata retains every original boundary/inventory ID and the original authority block. It adds five boundaries and five protected rows: the candidate totals are 497 boundaries and 363 protected rows. The old protected late-writer order is split along the actual shared preparation/consumption boundary while retaining every authority check. No verifier, global policy, budget, signing role, or initial/update protocol is changed. The final integrator must merge these exact metadata operations with other concurrent changes and update the repository's exact-hash large-file allowance for the resulting `CALLERS.toml`; this candidate hash must not replace a differently integrated file.

Six new Agentd component/data tests are supplied but unexecuted:

- Original registry comparison succeeds without acquiring or changing a held writer; the actual Config loader still refuses that held writer.
- Stale or already Running generation is refused.
- Unregistered roots and path aliases are refused.
- Explicit selection preserves ordinary bytes, including non-UTF-8 values and a selector-looking value.
- Duplicate, unknown, and incomplete entry choices are refused before descriptor ownership.
- A failed actual-owner check consumes the supplied descriptor attempt and cannot fall back to the default path.

Four additional Fleet tests are supplied, also unexecuted: complete snapshot equality without creating a writer, missing Matrix geometry refused without migration, unsafe Matrix permissions refused without chmod, and an aliased control directory refused. The two latter filesystem tests are Unix-specific. The two pre-existing late-writer tests remain as an exact byte prefix. No Root parent test is added. The original QA closure tables were inspected; their existing Root receive calls stay in the same late-writer file, so no QA needle or expected caller path was changed.

Completed static work is limited to forward/reverse exact operation replay for all eleven paths, UTF-8 length/SHA-256/Git object verification, literal protected-marker ordering, and the old-body comparisons above. Literal marker checks are not the original masked-Rust resolver or full closed-set verification. Rust formatting, compilation, the original full verifier, component tests, and later hosted/native validation remain required on the eventual integrated fixed source. The change now includes the hepta-fleet crate; its actual maintenance and unit tests must be scheduled in addition to every original qualification gate. Previous six-crate results do not cover this API.

## Remaining ordinary-loop dependencies

This entry does not make retained A survive a process exit. The retained learning source is still an opaque in-memory capability tied to the original producer/source/ledger/accepted Outcome and original AutomationStore. A legitimate new Supervisor incarnation requires the predecessor's actual process retirement, which destroys that process's in-memory capability. No cross-incarnation historical-source authorization/rebind or same-Running-owner phase switch is implemented here.

The existing Pending successor therefore remains a guarded conditional assembly capability. This candidate supplies a real opt-in consumer entry for legitimate starting inputs; it does not fabricate the missing retained-A input or a published C task. Default dual-CLI recovery, complete ordinary A-to-C reachability, and full daemon-plus-Root cold-loop recovery are not established.

The old B comparison contract, cumulative-budget/capacity checks, authenticated costs, and independent Observer Outcome requirement are unchanged. No task success becomes a business label or learning Outcome. The separate C-feedback work is outside this candidate.

Ordinary complete chains: **0**. Ordinary positive adoptions: **0**. Ordinary NoUpdate/rollback chains: **0**. This candidate supplies no new business, independent-C, or cold-restart acceptance.

The pinned reachability report is Git blob `3c4a565daee69bfc0c166e9ee161f456eac34fab`; its source inventory is `9d8fabd77baea2eee4d917068074018f7a0815ba`. Those reports describe the original fixed source. This candidate changes only the conditional CLI-consumer connection described above.
