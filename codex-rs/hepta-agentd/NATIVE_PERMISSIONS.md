# Native Root and Host filesystem ownership

The native CPU installation uses the original Fleet registry and cognitive
store. Root creates and initializes the fresh store, then explicitly transfers
its private cognitive files to the actual Host UID 60001 before activation.
The workload uses UID 60002. The protected authority and material archive stay
under Root control.

| Namespace | Owner and mode | Purpose |
| --- | --- | --- |
| Fleet and Agent control directories, except the runtime directories below | Root:60001, `0750` | Host can search and read its registration; only Root can change control entries. |
| Agent manifest and lifecycle/release state files | Root:60001, `0640` | Root publishes Registry state; Host reads the original state. |
| Agent run directory | Root:60001, `03770` | Host creates its writer lock; original lifecycle/control files retain Root ownership. |
| Fleet run directory | Root:60001, `03770` | The original short Agentd/Matrix/App Server socket paths live here; sticky mode protects Root supervisor endpoints. |
| Agent home, matrix and cognitive directories | 60001:60001, `0700` | Original Host-owned runtime and durable data. |
| Files in those private Host directories | 60001:60001, `0600` | Private data, including the initialized SQLite store. |

Fresh handoff checks physical file types, actual UID/GID, link counts for files,
and final modes. It refuses unexpected owners or symlinks. It does not transfer
the entire Fleet or the protected archive to the Host.

## Original Registry control-owner fence

A sticky run directory alone cannot stop the Host from creating a new,
higher-numbered lifecycle filename. The original Registry therefore derives
its controller from the actual opened Agent root directory. It opens every
manifest and lifecycle/release state file with `O_NOFOLLOW`, validates the
same file descriptor with `fstat`, requires that original controller UID and
no group/world write bits, and reads that descriptor. A replaced path cannot
substitute unchecked bytes after validation. `O_NONBLOCK` lets a FIFO be
rejected without waiting for a writer.

The publisher retains the original atomic publish and directory sync. It
requires the original controller or actual Root, preserves that controller's
UID, and publishes group-readable `0640` state only for an explicitly shared
`0750` control directory. Ordinary same-UID registries keep their owner and
existing umask-derived private modes. The Fleet crate retains its unsafe-code
prohibition and uses safe `rustix` descriptor operations on Unix.

## Acceptance

The regular Fleet suite includes real filesystem checks for ordinary lifecycle
transitions, shared-write rejection, symlink/FIFO rejection, and a held checked
descriptor across path replacement.

The Agentd ignored test
`native_cpu_entry::permissions::tests::native_permissions_keep_original_control_owner_for_real_host_uid`
requires actual Root. It creates an isolated `/run/hepta-native-permissions-*`
namespace, initializes the original registry and SQLite store, and starts an
independent process of the original test executable. That child drops to the
real UID/GID 60001, reads the registration and release state, opens the store,
and creates its real lock and binds all three original socket paths. Root
retains a real supervisor control file and socket in the shared Fleet run
directory. The child must fail to write, remove or replace those Root inodes,
connect to the Root-only socket, change the shared directory mode, modify or
unlink Agent control files, publish a Registry transition, or have a Host-owned higher
generation interpreted as controller state. Root then verifies the same
forgery is refused and publishes an ordinary legitimate transition.

Run the exact parent test; its private ignored helper is only invoked by that
parent. This permission test does not establish native Process authority or
complete daemon qualification. Those require the same frozen Rust entry to
run in the Asterinas derivative and exercise the original owners.
