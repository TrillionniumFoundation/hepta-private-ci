# Root role process launcher

The owner is `root_notes_native_launcher.rs`, with retained image custody in
`root_role_executable.rs`, syscall-only fork setup in `root_role_fork.rs`, and
the exclusive child/pidfd lifetime in `root_role_child.rs`. These modules are
compiled by the ordinary Linux Agentd library. They use the existing sealed
bootstrap implementation and original process-identity contracts.

## Inputs and outputs

Only the actual Root process can launch a role. It supplies an already installed
ELF, bounded arguments and an absolute deadline. The Host's initial FD 0 document
must be the original Root-owned four-seal memfd and name that same Root's actual
boot, PID and start time. Installed configuration carries paths and bindings;
it does not create a lease, grant, recovery cut or writer.

| Process | Fixed credentials | Inherited descriptors |
| --- | --- | --- |
| Host | UID/GID 60001 | Config 0, `/dev/null` 1/2, actual Root pidfd 3 |
| Native-profile Host | UID/GID 60001 | Host set plus supplied control 5/bootstrap 6 |
| Session | UID/GID 1000 | Host-created datagrams 0/4, `/dev/null` 1/2, actual Host pidfd 3 |

Supplementary groups and all capability sets are removed; no-new-privileges is
set before exec. Every inherited descriptor is first marked close-on-exec and
only the fixed role map is exposed. High duplicated source descriptors prevent
FD 3/4/5/6 from overwriting the exec-error pipe or retained executable. The child
executes the retained inode through `execveat`, without reopening its pathname.
The parent checks the actual post-exec credentials and retains the child pidfd.

The launcher limits exec to the smaller of five seconds and the remaining
original lifetime. Later waits can shorten but cannot renew that lifetime.
Failed setup/exec, wait expiry and guard drop terminate and reap that owned
child. Root must be its exclusive reaper; inherited auto-reaping is refused.
There is no numeric-PID adoption or restart policy in this layer.

## Qualification

Ordinary package tests compile the complete launcher and cover ELF/config and
shared launch-frame contracts. Explicit Root parents in
`root_notes_native_launcher_tests.rs` execute an installed Linux `sleep` probe
under real UID 60001. They check the inherited FD set and exact sealed bytes,
minimal environment, normal exit, deadline kill, guard-drop cleanup, actual
post-remapping exec failure, and rejection of Session sockets from a foreign
process. Each test creates its own temporary installation under `/run` and
reaps only its owned child. It never opens a production authority directory.

Run these parents explicitly through `just test` with the nextest expression
`test(root_notes_native_launcher::tests::root_)` and ignored-only selection.
They are deliberately ignored in ordinary unprivileged runs. A skipped parent
is not qualification. Preserve the exact source/toolchain, selected test names,
original output and zero-retry result in the integration acceptance record.

The Linux probe does not run Agentd, create a persistent writer or issue an
effect. A transported HOS2 descriptor does not transfer the kernel's Process
binding. Native G2 still requires the trusted kernel role loader to bind the
final executable and original adapter, followed by real CPU effects, original
outbox/SQLite terminal publication, loss/restart reconciliation and retirement.
Actual Root→Host→Session application readiness and full default five-lane static
image admission remain separate integration results.
