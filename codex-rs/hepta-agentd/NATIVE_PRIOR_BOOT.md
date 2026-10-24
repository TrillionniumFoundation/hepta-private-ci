# Actual VM loss and prior-boot Unknown

`prior-boot-unknown-v1` uses the same plan shape as the six existing scenarios:
`schema_version`, `scenario`, and a 64-character lowercase hexadecimal `nonce`.
The plan does not choose a boot, state path, identity, key, K/D, Current or result.
The actual mounted original installation selects Fresh or Retained. The same raw
`/dev/vda` volume must survive two separate QEMU processes without formatting,
replacement or logical database reconstruction between them.

This is a VM-process failure test. It does not claim host power-loss durability.
Each boot retains the original 120-second acceptance window, 20-second writer
lease, 120-second Root session and kernel grant/recovery/watchdog limits. The
existing synchronous EFAULT callback remains bounded to two seconds.

## First boot

After the original owner becomes ready, Root asks its original descriptor and
writer for `TransportObservation`. This reports the actual physical database
path, device/inode, separate Install/Query ioctl counts, and the actual one-time
pre-monitor pending snapshot. The initial counts and pending set must be empty.

Root observes the original registry, issuer and clock before dispatch, then
prepares `prior-boot-unresolved` through the original writer. The unchanged
FileTransport substitutes one real inaccessible response mapping for this exact
prepared Install. A real `-1/EFAULT` reports the original two-second callback
boundary before the FileTransport returns. The original Current barrier, HOS2
gate and FinalUse lock still hold; the normal monitor is neither paused nor
delayed by a test hook.

Root independently captures its actual Current, retained physical material and
two protected FinalUse frontiers. It saves one bounded immutable observation
through the original Root administration directory and verifies actual durability
before emitting `prior_boot_cut`. The host must immediately SIGKILL that QEMU
process. No successful Host dispatch reply or first-boot completion is produced.

The host records its real process signal/exit and monotonic timing separately
from the guest's BOOTTIME samples. These two clocks do not prove the guest's
precise kill instant or that the callback was still pending at that instant.
The guest samples establish the durable cut before its callback deadline;
actual stopped-disk evidence establishes the unresolved state at VM death.
Offline acceptance must inspect both the selected retained material and
the actual mutable physical database plus its WAL, using private forensic copies
without modifying the original raw volume. A late kill that allowed the original
source terminal to be appended must fail, even if the older archive is Unknown.

## Retained boot

The original cold-open path independently checks the installed public pin,
canonical writer proof, complete protected head and verified retained image. It
opens the existing clock/registry/issuer and retires the complete original active
lease selection through original revision-checked revoke. It waits for the real
old local lease expiry. Private PriorBoot evidence and the original physical
factory perform the strict next-generation adoption. Only the original Root
policy CAS authorizes the actual new kernel namespaces.

The saved observation is opened by its exact old boot and nonce after this
independent recovery. It is never an authority constructor input. Root checks its
Current token against the actual complete previous head, material bytes, unchanged
installation inode/bytes/public pin and exact retained issuer sequence. The
original Host's pre-monitor snapshot must contain the same Indeterminate K/D.

`ObservePreviousBoot` reads that operation through the original immutable
outbox/event validation, calls the original `AgentdHos2Device::observe`, and
records its real boot-mismatch refusal. This happens before any Query ioctl; it
is not described as a kernel Unknown response. Original retained operation bytes
and state are checked again, and original drain blockers must remain one.

A new-boot request then uses original prepare, FinalUse, dispatch, terminal,
Current publication and retirement. The original workload window must span at
least two periods under its new cap. A second original old-K observation must
still refuse without changing the descriptor's Install/Query counts across that
observation. Notes frontier stays unchanged; Device frontier includes the actual
new claim. Original pending work remains a blocker.

The distinct `prior_boot_complete` ends with sync and the original kernel
poweroff. It does not call ordinary `stop_owner`, release the old Unknown, or
claim successful drain/owner exit. Persistent later handoff with this unresolved
work remains a separate lifecycle obligation.

## Exact additional event payloads

The `HEPTA_G2_EVIDENCE_V1` envelope is unchanged. Old six scenario event shapes are
unchanged. This scenario adds the following events, with at most 128 records per
boot and the existing 128 KiB per event bound.

| Event | Exact payload keys |
| --- | --- |
| `boot_phase` | `phase` (`fresh` or `retained`), `kernel_boot`, `installation` |
| `prior_boot_cut` | `current`, `material_path`, `authority_before_dispatch`, `observation_id`, `observation_path`, `durable_payload_json`, `durable_payload_sha256`, `emitted_boottime_ns` |
| `prior_boot_adopted` | `cold_open`, `successor`, `observation_id`, `observation_path`, `durable_payload_json`, `durable_payload_sha256` |
| `prior_boot_observed` | `phase` (`before_new_effect` or `after_new_effect`), `transport`, `observation` |
| `prior_boot_complete` | `current`, `material_path`, `material_sha256`, `authority`, `unresolved_occurrence_key`, `drain_blockers`, `shutdown` (`poweroff_with_unresolved_previous_boot`) |

`installation` is the original installation file observation: `path`, `device`,
`inode`, `bytes`, `sha256`, `expected_verifying_key`. `transport` has `pid`,
`database_path`, `database_device`, `database_inode`, `ioctl_counts`, and
`startup_retained`. `ioctl_counts` contains `install_ioctl_count` and
`query_ioctl_count`; the existing copyout diagnostic/snapshot types are unchanged.

The saved JSON payload has `schema_version`, `nonce`, `kernel_boot`,
`current_token`, `occurrence_key`, `payload_json`, `material_sha256`, `frontiers`,
`boundary`, `installation`, `source_database`, `authority_before_sha256`, and
`issuer_sequence_at_cut`. `boundary` is the actual existing EFAULT callback DTO.
The Current token binds the full original head separately emitted in the cut.
`authority_before_sha256` binds the exact pre-dispatch authority observation.

`cold_open` contains `previous`, `previous_writer`, `writer_proof_sha256`,
`issuer_sequence`, `revocations`, `registry_before`, `revocations_applied`,
`registry_after`, `clock`, `device_frontier`, and `notes_frontier`. `authority`
contains `issuer_sequence`, `writer_proof_sha256`, `writer`, `revocations`,
`registry`, and `clock`. `clock` contains the original `projection` and actual
`observed_unix_ms`; the ceiling remains an upper bound, never an observed time.

The old-K `observation` contains `pid`, `occurrence_key`, `request_json`, `before`,
`after`, `refusal`, `calls_before`, `calls_after`, `drain_blockers`,
`device_frontier`, and `notes_frontier`. Each before/after record contains the
original `operation`, `topic`, `payload_json`, and `state`. It does not contain a
fabricated terminal-absence boolean. Offline original SQL evidence determines
absence of every terminal occurrence for that K.

Saved records remain under the original
`/state/hepta-native/protected/authority/native-launch-observations` directory.
The observation ID is `native-boot-cut.<old actual boot UUID>.<nonce>`; the file is
`observation-v1-<SHA256(observation_id)>.json`, with original owner/mode 0/0600.
Its original wrapper is `{schema_version:1,observation_id,payload:[u8,...]}` and
retains the original complete encoded 16 KiB bound. The existing installation
pin is `/state/hepta-native/protected/installation.json`; consumer-local files
remain on the same volume at `/state/hepta-native/consumer-local` with the
original runtime bind alias. No private signing key is emitted.

Source review, filesystem tests and host parser tests do not qualify this case.
Both actual QEMU runs, same-disk byte identity, real kill result, retained SQL/WAL,
old refusal, original new effect/window and raw kernel poweroff exit are required.
