# Fence local-control maintenance candidate

The Blob policy job for source `97ab00451799667faebac2c455a1e3176ebc90cb`
failed before checkout with `local_control_inventory_unavailable`
([job 139618955828](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45732887025/job/139618955828)).
Its original 3,859-byte log has SHA-256
`d0b3b41f2fef4e3a5c63018d4e2c9a9c78f1e57f8cc964c117eeb7f55d378dae`.
The Blob checker did not execute. The unavailable input remains unidentified.
An earlier execution passed with the same Fence pin, Ubuntu image, runner,
and provisioner versions; the failure does not establish an image regression.

This candidate updates only the Fence Action pin to official
[v0.10.2](https://github.com/openai/fence/releases/tag/v0.10.2), commit
`63c516e78543f3d8d6088ebad6475a39920863bd`. Its release and bundled manifest
identify source `14b8a1d2715e0323ed9ba8a141f61bea268229d1` and declare binary
SHA-256 `2441fe391bdf2adb511bcc797fedb107debd1ee1deac7294ecdc7f11000517fa`.
The review verified source and Action tree identities; it did not independently
download or execute that binary or run the upstream tests.

[Upstream PR 180](https://github.com/openai/fence/pull/180) allows an eligible
matching acquisition failure to use remaining rounds from the existing three-pair
limit. Actual scan counts can increase. The 50 ms pair interval, shared 5 s Unix
probe deadline and 1 s individual probe cap remain unchanged. That shared deadline
is not a watchdog for every process-table read or the whole startup sequence.
Persistent unavailability still fails, and complete matching snapshots and the
reviewed ownership checks remain required. Basic fixed-label failure diagnostics
are added; the later ownership-detail diagnostics are not included.

The complete reviewed release difference also adds classified DNS rejection
reporting and explicit capacity rejection, rejects oversized NFLOG datagrams, and
tightens bounded Action report validation and log sanitation. It is not solely a
single-function fix. No new runtime retry or timeout was found in this selected
release difference. Later versions with additional host UDP bind or Docker retry
behavior were considered and remain unselected.

The workflow retains audit mode, Fence before checkout, its original runner and
permissions, 30-minute job limit, the original 512,000-byte Blob policy and
allowlist, and the clean-worktree gate. Static source review is not runtime
qualification. A new normal job must reach Fence readiness, actually execute the
original Blob checker, pass the clean-worktree gate, and pass Fence post
verification. Any recurring failure must retain its actual diagnostic evidence.
