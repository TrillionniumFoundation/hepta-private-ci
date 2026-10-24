# Native partial activation recovery

This path uses the original Supervisor, canonical issuer, lease registry,
checkpoint publication lock, physical material and publisher lifetime owners.
It does not turn an activation error into readiness. The original driver must
first kill/reap its actual failed child and the original Supervisor must retain
that exact `Starting` generation's `Failed` successor.

The Root retains a real `SpawnSpec`, captured publisher lifetime and any started
lane thread before mutating authority. A successful activation transfers the
lane thread into the usual `Active` owner. On failure, the Root observes actual
publisher retirement and joins only that failed publisher's lanes. A lane error
is a teardown diagnostic; it is not evidence that the service was healthy.

## Original cut selection

The Root reads the complete original checkpoint head and opens the retained
physical image named by that head's actual `last_current`. It never obtains a
replacement cut from the mutable current database. The original retired-head
reader validates the actual publisher, whole binding and unchanged image under
the original publication lock. Dirty, Publishing and Fenced phases remain as
read; they are not changed into Current by this observation.

There are two distinct cases:

| Actual retained state | Next authorization |
| --- | --- |
| Canonical writer binding equals the installed whole head | Original writer rotation advances the local generation by exactly one. |
| Canonical proof names exactly head generation plus one, but the head still names the retired predecessor | Original `replace_unactivated_writer_authorization` replaces that failed proof with a different real spawn, owner epoch and authority lease, retaining the same unused next local generation. |

The latter operation still requires original registry retirement of the failed
lease, the full retained predecessor token, the actual failed publisher's
retirement, a different live successor pidfd, the original physical image, and
the original checkpoint and issuer locks. An unrelated or larger generation
gap is rejected.

Before the next original `Supervisor::start`, the Root reads the complete
unretired authority selection for this Agent, including future leases, and
performs exact original revocations. It verifies that this selection is empty
and waits for the actual old local lease expiry using the original clock. This
does not extend, rewrite or pretend to release an issued local lease. The full
canonical state, protected cut, physical material and consumer frontiers are
read again before handing the original recovery objects to the next factory.
At most two failed activations are reconciled by one bounded start operation;
a later failure remains an error with its original state retained.

## Kernel namespace policy

The actual Manager or Recovery image from the same original kernel pair may
complete an interrupted namespace-policy step. Its exact role/PID must match
the retained kernel launch receipt, and the original Root observation must have
been saved and acknowledged durably. History-only images remain ineligible.

The expected scopes must be the exact preceding retired pair or the exact fresh
pair from those receipts. If they are already the fresh pair, the original
issuer helper can only verify that same retained state; it cannot perform an
old-to-new policy CAS. Cross-boot initial-pair reconciliation still additionally
requires the private original PriorBoot full-token witness. No scope reuses an
old boot or namespace, and no failed activation grants a plain fork/exec child
kernel authority.

## Fixed native acceptance cases

Two independent plans use the existing `{schema_version, scenario, nonce}`
input. Each retains the existing 120-second external case window, 120-second
Root sessions, 20-second newly issued writer leases, and original kernel
300/30/5-second limits.

* `activation-after-proof-v1` first performs a real initial operation,
  terminal/Current acknowledgement, retirement, two-period usage window and
  successful original release/reap. During the next actual Recovery activation,
  Root sends SIGKILL through its held pidfd immediately after the original
  canonical writer-proof operation returned. The following original checkpoint
  or lifetime operation must fail. A fresh kernel Manager uses the same unused
  local generation and executes another actual operation and usage window.
* `activation-after-material-v1` uses the same initial ceremony but kills the
  actual Recovery after the original physical material installation and its
  verification completed, before sending the sealed bootstrap. The following
  original launch operation must fail. The protected head already names that
  failed publisher, so the fresh Manager advances one more local generation.
  The successor-specific physical filename preserves the failed attempt's image
  while allowing the different actual publisher's install to complete.

The hook does not return a fabricated failure. It returns to the original
implementation after a real pidfd SIGKILL and `waitid(WNOWAIT)` observation of
`CLD_KILLED/SIGKILL`. Only the original driver reaps the child. Original service
and Supervisor results determine whether recovery is eligible. No ordinary
runtime or earlier acceptance case arms these fixed failures.

The extra event is `activation_recovery_prepared`, containing exactly:

* `failure`: the original Supervisor start error text;
* `supervisor`: actual `active`, `healthy`, `runtime_generation`,
  `spawn_generation`, and `process_system_id` fields;
* `reconciliation`: `failed_spawn_generation`, `failed_peer`, `fault`,
  `registry_failed`, `mode`, `previous`, `canonical_writer`,
  `canonical_proof_sha256`, `issuer_sequence`, `registry_before`,
  `revocations_applied`, `registry_after`, `observed_unix_ms`,
  `local_expiry_unix_ms`, `device_frontier`, and `notes_frontier`.

`registry_failed` is the actual original `AgentLifecycleState`. `previous` is
the actual complete retired checkpoint receipt. `mode` is `installed` or
`unactivated`. A fixed fault contains `point` (`after_proof` or
`after_material`), `peer`, `spawn_generation`, `pidfd_revents`, `wait_kind`,
`wait_value`, and `observed_boottime_ns`; an unrelated actual failure has
`fault: null`. The fault case requires its actual selected fault observation,
not merely any failed start. Existing original `owner_released`,
`owner_stopped`, `kernel_launch_saved`, `continuity_owner`, `source_terminal`,
`history_ack`, `usage_window` and completion events remain unchanged.

These source paths and observation contracts are not native qualification.
Each case requires the same frozen Rust ELF to satisfy the unchanged 8 MiB
file and 16 MiB LOAD bounds, actual guest exit 33, and an independent oracle
checking the real registry, Current/material, kernel receipt, PID/reap,
generation and CPU-effect chain. Existing Root owner reentry and physical
attempt tests must also run with retries disabled. A fresh genesis with no
protected head, or a Root/VM loss before that head exists, is a separate
installation-recovery obligation; this path does not create a synthetic
initial head or reset the original key, issuer state or clock.
