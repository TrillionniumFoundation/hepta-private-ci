# Verify the physical-login boundary of the paired consent command

A development launcher handed the released Linux `hepta-paired-consent` command an actual connected Unix socket on fd 3 and a pidfd for that launcher on fd 4. The launcher's original `DeploymentFinalUseIssuer` signed the two development consent statements. Its temporary key is generated anew for each run. The evidence store verified each Ed25519 envelope at enqueue, leased each message to a development consumer, recorded the acknowledgement, closed SQLite, and recovered the original signature and acknowledgement on a read-only reopen.

For each permitted use, the new command read its one retained delivery and sent the expected `runtime.authbus.human_text.verify.v1` request through the inherited socket. The launcher inspected the original frame with a non-consuming peek and computed its SHA-256 from the received bytes. The production `HostAuthorityService` then consumed that very frame. The launcher had no registered physical user session. The service returned `Unavailable`, the command exited 1, and its stdout was empty in both cases. `RESULT.ndjson` preserves both observations. `INDEPENDENT_REPEAT.ndjson` repeats both processes from fresh issuer state, with new signature, delivery and received-frame hashes. This run admits zero users and supplies zero future tasks.

| Case | Cold SQLite check | Exact consent request reached Root | Product result | CLI stdout |
| --- | --- | --- | --- | ---: |
| Development training consent | Acknowledged | Yes | Unavailable | 0 bytes |
| Development evaluation-only consent | Acknowledged | Yes | Unavailable | 0 bytes |

Both socket endpoints originate in the isolated UID-0 launcher's socketpair and have that launcher's Linux peer credentials. The separate CLI receives one endpoint through descriptor inheritance. These fields identify the development launcher. A real positive readback additionally requires a live original UI and the registered seat session, a permission binding, and the exact human-linked issuer signature. A generic development signature and a genuine queue acknowledgement alone cannot supply these. The host service enforces the physical session before consulting its retained human binding. The study enrollment authority remains responsible for distinct people and the original intake log for arrival order.

Run from the repository root on Linux with unprivileged user, mount and network namespaces available. The script mounts a temporary development root. The read-only toolchain runtime and procfs allow the kernel pidfd checks. It creates fresh clock, issuer and evidence state only inside that temporary filesystem. Supply the printed artifact paths if the Cargo target directory is customized.

```sh
(cd codex-rs && cargo build --locked -p codex-hepta-agentd \
    --bin hepta-paired-consent --example paired_consent_process)
sh qualification/paired-consent-process-20261123/run-isolated.sh \
    codex-rs/target/debug/examples/paired_consent_process \
    codex-rs/target/debug/hepta-paired-consent
```

The original product target passed the standard Cargo build in #7019. On the constrained research host, the full Cargo example build stopped while recompiling `codex-core` after rustc received SIGKILL. The example source was instead compiled against the Rust 1.96.0 product graph already built by Cargo for #7019. The resulting example ELF SHA-256 is `9cbd81a6b5ac5a9193913c0cb57fa180717859c0cc9478380ae1a3ecaf0af438`. That exact executable ran both fresh trials.

Published CLI SHA-256 is `a506026a28ed0a8be8c113bca473009e21c18ad08acc976b3cbaf4ec306381e5`. New keys, signatures, delivery IDs and frame hashes are expected on independent runs. The two scope labels, acknowledgement and wire checks, service response, process exit codes and output counts can be compared directly.

[Original purpose-bound host command](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7019) · [Read-only human verification in the original host service](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/68ea291400fef2a412591f36f5e6ba2efbd26db3/codex-rs/hepta-agentd/src/authority_host_human_text.rs) · [Original physical-seat and leader validation](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/68ea291400fef2a412591f36f5e6ba2efbd26db3/codex-rs/hepta-agentd/src/authority_host_logind.rs)
