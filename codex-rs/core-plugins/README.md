# codex-core-plugins

This package manages plugin discovery, configured marketplaces, local installs,
remote cache reconciliation and executor-owned plugin resolution. Public exports
are in [src/lib.rs](src/lib.rs); loading a plugin descriptor does not itself
authorize its tools or an external effect.

## Technical contract

`PluginsManager` in [src/manager.rs](src/manager.rs) consumes a
`PluginsConfigInput` containing the configuration stack, provider, enable flags,
service URL and HTTP client factory. It resolves effective plugins/skills/hooks,
lists/reads marketplaces, and owns install/uninstall and remote reconciliation.
Policy projection in [src/marketplace_policy.rs](src/marketplace_policy.rs)
validates configured marketplace sources and roots. Restricted installs require
the marketplace in effective user configuration and a matching normalized root;
reserved managed names cannot be claimed by an unrelated source.

Local `PluginStore` ownership is in [src/store.rs](src/store.rs). Cache roots
are beneath `plugins/cache`, with persistent plugin data beneath `plugins/data`.
Install checks the source directory, manifest name versus `PluginId` and version
segment, then uses the existing atomic directory replacement routine. Invalid
input and contextual I/O failures are distinct `PluginStoreError` variants.
Atomic local replacement is not a transaction with a remote service or proof
of crash durability. Uninstall and remote-install metadata cleanup have their
own filesystem error paths.

The remote installed-bundle cache has a shared semaphore gate. Its
`RemoteInstalledPluginSyncGuard` retains an owned permit; full sync,
reconciliation and direct remote mutations share this gate. Acquisition has the
existing 120-second timeout and can return `LockTimeout` or `Superseded`.
Callers release the guard before unrelated analytics, OAuth or runtime refresh.
Reconciled publication advances the generation so stale metadata fetches cannot
overwrite the snapshot. An uncommitted reconciliation guard abandons its
generation on drop; cancellation after bundle mutation may still require an
effective-plugin refresh. A local error must not be read as remote rollback or
permission to repeat an uncertain external mutation.

`ExecutorPluginProvider::resolve_bound` in [src/provider.rs](src/provider.rs)
uses the selected root's `EnvironmentManager` filesystem, checks its directory
and preferred manifest, and retains that exact filesystem `Arc` alongside the
resolved descriptor. An unavailable environment does not fall back to the
host filesystem. Missing compatible manifests may yield `None`; inspection,
read, parse and descriptor errors retain typed causes. Native/foreign paths
remain `PathUri`s for the selected environment.

Bundle limits are supplied by the caller to
[src/plugin_bundle_archive.rs](src/plugin_bundle_archive.rs). Packing validates
a plugin manifest and caps compressed output; extraction caps total regular-file
bytes and rejects empty/absolute/parent-escaping paths, symlinks, hard links and
unsupported entry types. Extraction can create files before a later error;
the owner must manage its disposable/staging destination. These checks do not
prove trust in plugin content. Executor hook selection has its own allowlist in
[src/executor_hooks.rs](src/executor_hooks.rs); marketplace presence, artifact
recognition and command migration do not create a Hepta production grant.

## Development and validation

Start at `manager.rs:495` for manager-owned state, `:1496` for the remote gate,
`store.rs:340` for install validation and `provider.rs:111` for bound resolution.
Keep provider filesystem identity and cache generation/guard lifetime intact.
Use [src/loader.rs](src/loader.rs) and marketplace policy when changing source
selection; do not bypass them with an ad hoc host-path read.

Run the original package lane from the repository root:

```sh
RUSTUP_TOOLCHAIN=1.95.0 CARGO_BUILD_JOBS=2 CARGO_INCREMENTAL=0 \
  just test --locked --offline \
  -p codex-core-plugins --test-threads 2 --retries 0 --cargo-profile dev-small
```

Existing concrete coverage includes:

- [src/provider_tests.rs](src/provider_tests.rs): supplied/foreign executor
  filesystem resolution, unavailable-environment rejection and malformed
  preferred-manifest rejection without alternate fallback.
- [src/store_tests.rs](src/store_tests.rs): installation, manifest identity,
  versions and symlinked manifest rejection.
- [src/executor_hooks_tests.rs](src/executor_hooks_tests.rs): allowlisted hooks
  and rejection of unallowlisted or file-backed executor hooks.
- [src/plugin_bundle_archive_tests.rs](src/plugin_bundle_archive_tests.rs) and
  [src/startup_sync_archive_tests.rs](src/startup_sync_archive_tests.rs): portable
  manifests, executable modes, traversal and symlink archive cases.
- `manager_tests.rs`, `marketplace_policy_tests.rs` and `remote_tests.rs` cover
  their respective manager, policy and remote fixture contracts. Owned fixtures
  and HTTP mocks do not qualify a live production marketplace or OAuth account.

Exact examples are `provider::tests::unavailable_environment_does_not_fall_back_to_host_filesystem`
(`provider_tests.rs:361`),
`store::tests::install_rejects_manifest_names_that_do_not_match_marketplace_plugin_name`
(`store_tests.rs:734`) and
`startup_sync::archive_security_tests::archive_traversal_cannot_overwrite_a_file_outside_the_destination`
(`startup_sync_archive_tests.rs:55`). Their module IDs follow the source module
declarations; inspect the full owning-binary inventory when qualifying a build.

This manual was source-reviewed against code baseline
`7673ea62fc019f97ad17d205ee1f81f96e0f47a0`. No Rust/test/network/plugin operation
was run for this documentation change. Earlier results remain attached to their
own source identities; production authority and hardware control remain separate.
