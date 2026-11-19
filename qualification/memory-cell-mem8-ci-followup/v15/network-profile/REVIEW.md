# Exact 9bd2 network-profile failure review

## Finding

The original `command_exec_permission_profile_starts_selected_network_proxy` assertion remains failed. The returned child response has exit code 1, empty stdout, and a Bubblewrap namespace-permission error. This review does not establish the precise host kernel, LSM, container or user-namespace configuration that denied the operation, and does not propose weakening the profile or converting that error into a successful test.

Source is `9bd2f589debdba4a93baa363817c3669cb103721`, tree `c77785ecb368c44ea699769001a47402c9f50591`. The blocking workflow checks out merge commit `8644d1044c50c7d4bfa47834f2602d133433300d` with the same tree. Original jobs `130526871565` and `130526871689` belong to run `43021840778`.

## Original execution evidence

The failure is in `//codex-rs/app-server:app-server-all-wine-exec-test`, shard 12 of 16. Its three original Bazel attempts each retain the unchanged expected response: exit 0, stdout `1`, empty stderr. The actual namespace error precedes that assertion. The earlier warning that system Bubblewrap was absent also states that the bundled Bubblewrap will be used; that warning is not proof that no Bubblewrap process ran.

Root independently checked both complete raw-log SHA-256 identities and all eight complete bounded test-output blocks identified by the CI audit, stripping only the outer GitHub per-line timestamp. Corresponding GNU/musl payloads are identical, including their internal timestamps and temporary paths. There are three distinct network-test attempt payloads repeated across the two job logs; they are not six independent native replications. The separate core subagent timeout block is also repeated and must be judged by its own final target outcome. See `ROOT_ORIGINAL_BLOCK_AUDIT.json` and the full originals in the CI evidence archive.

## Source path inspected

The exact test source is blob `94a648a829bc407166d70dc58e028a9937aa1267`. It configures a named `networked` permission profile with read-only root access and an enabled proxy, builds `TestAppServer` with `without_auto_env()`, then sends the actual `command/exec` request with that profile. Replacing the profile with unrestricted access or omitting the proxy would change the tested contract.

`TestAppServerBuilder::without_auto_env` selects `TestAppServerEnvironment::None` in blob `489a966b49cc738adfc72acc1bb919656256ac97`. The normal automatic environment selection is consequently not performed by that builder. The Wine runner, blob `6e73e68e9b6c7237181beca458741045b3dfe972`, starts the native integration-test binary and sets the Wine remote-test environment; it does not turn every process in the test binary into a Windows process. The original app-server initialize response reports Linux, and the failing command uses the local Linux Bubblewrap path. This is not a native Windows namespace result.

The app-server BUILD file, blob `6a1950908002a2268d018e414ffe8a39f9d00d42`, supplies Bubblewrap and `no-sandbox` test tags. `defs.bzl`, blob `99f0085a8095f4f5fe41ace52d0dff021be95949`, passes those test tags through to the Wine wrapper. The inspection therefore found no missing tag inheritance that would justify a one-line tag repair. The repository's `.bazelrc`, blob `59c6850487b948779389a481de5161c64fd21ff5`, selects the RBE platform for the Linux CI configuration; the actual physical worker's namespace policy was not captured by the provided originals.

## Remaining closure work

Preserve the failed case and obtain authoritative namespace-capability/denial evidence for the original execution environment or an explicitly qualified replacement execution lane that retains the same source, profile, assertion and command budget. A new lane would need its own execution identity and raw evidence; a result cannot be inferred from a cached target summary, an empty capability probe, or a different process environment.

No skip, assertion change, namespace-policy relaxation, unrestricted fallback, additional native run, real model request or source-ref mutation was performed by this review. The available source and raw evidence support an environment-precondition diagnosis; they do not yet supply a verified environment repair.
