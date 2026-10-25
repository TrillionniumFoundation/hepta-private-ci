# Skills extension development and technical boundaries

This package installs the original skill extension, discovers host/executor and
orchestrator catalogs, exposes bounded list/read tools, and renders selected skill
instructions through the extension API. Loading a skill does not grant filesystem,
process or device authority; executor access still uses the original executor
filesystem and its policy.

## Code ownership

| Area | Source | Contract |
| --- | --- | --- |
| Public installation and providers | [lib.rs](src/lib.rs), [provider](src/provider.rs) | Existing extension/provider interfaces |
| Host roots | [host_roots.rs](src/host_roots.rs) | Config-layer, plugin, extra and repository roots; configured ancestor markers and path deduplication |
| Host lifecycle | [host_service.rs](src/host_service.rs), [host_snapshot.rs](src/host_snapshot.rs) | Existing load ownership, immutable snapshots and cache invalidation |
| Loading and merging | [loader](src/loader/mod.rs) | Preserve provider/source identities and bounded scans |
| Tools and rendering | [tools](src/tools/mod.rs), [render.rs](src/render.rs) | Original tool schemas and model-facing exposure |

Repository discovery uses the configured project markers, including the original
default Git marker when not overridden. A nonempty marker list with no matching
ancestor and an empty list which disables searching are distinct cases. Tests
must establish their own marker premise instead of depending on a shared temp
parent. Production discovery must not be weakened to make a fixture pass.

## Development and acceptance

From codex-rs run the original owning command
`just test --locked -p codex-skills-extension`, then scoped
`just fix -p codex-skills-extension` and `just fmt` under the repository workflow.
Keep semantic test phases separate from mechanical finish; preserve original
root, scope, source and executor-authority assertions.

[The missing-marker qualification](acceptance/2026-10-23-missing-marker/README.md)
records the real baseline failure, first correction failure and175/175 owning
pass with unchanged assertions. It is Rust1.95 Linux scope evidence; final
Rust1.96 workspace and native Organ qualification remain separate.
