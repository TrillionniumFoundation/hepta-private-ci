# Agentd and finite Notes Organ

The default `run` entry embeds the original App Server and general Agentd planes.
The Linux `run_notes_organ(config, root)` entry is an explicit finite Notes composition.
Both retain the original Fleet process identity, one run coordinator, AuthBus signature
and replay checks, immutable Objective publication, production writer, local lease,
FinalUse targets and original terminal receipt reconciliation.

## Trusted composition

Before calling the finite entry, the embedding must recover the original protected
writer against the independently retained Root Current, attach the actual Notes
incarnation and its recovery capability, activate the two original FinalUse consumers,
and install the exact same host in `AgentdConfig`. Pass the same live Root session.
Configure the original AuthBus trust, external replay checkpoint and Notes admission
profile. At least two workers on the same Tokio runtime are required.

The finite entry rejects other configured execution planes. Its control allowlist is
Capabilities, Health, Lifecycle, Readiness, ObjectiveStart, ObjectiveAdmission,
RunCancel and RunStatus. Unknown methods are refused. It starts the original operation
reconciler and uses the original generation, deadline and shutdown/drain machinery.
It does not start a model, generic App Server, automation plane or federation reader.
`Lifecycle.app_server_ready` remains false; Health describes the registered Notes
execution service. Text ingress remains gated on a real App Server profile.

## Recovery and evidence boundary

The UI reports historical durable outcomes independently of a new process's ephemeral
run projection. Unknown effects remain unknown; terminal receipt recovery never replays
the application action. Process spawn generation and local lease generation are separate
identities and require the original verifier's exact registered binding.

This source entry alone does not demonstrate a native executable, deployment, the
original 8 MiB ELF / 16 MiB LOAD gate, or full Agentd availability on Asterinas.
Those require the fixed final binary and actual Root/owner/application failure tests.
The original full-daemon size rejection must remain in the qualification record.

## An explicitly retained old Notes operation

`run_notes_organ_with_previous_recovery(config, root, launch)` runs the same
finite control loop and original reconciler with one additional recovery-only
process. The trusted startup manifest supplies `AgentdNotesPreviousRecoveryLaunch`:
an absolute companion helper path and its expected SHA-256, the private Notes
state directory, the exact old target and the original retained operation ID.
It must first observe the old application reaped by its original supervisor.
The current target already installed in `config` remains the only destination
for new Notes effects. Ordinary UI config and Objective messages cannot choose
the predecessor, executable, directory or original owner.

Before startup, the same protected writer verifies its live authority and the
original retained topic, payload, intent, subject, policy generation and
destination. Only an `Indeterminate` or `Committed` source operation qualifies.
The host then starts the hash-bound helper with a private Unix datagram on
stdin, waits at most two seconds for its old-incarnation lock/reopen readiness,
and verifies authority again. Failure prevents finite-service readiness. This
adds no old dispatcher, issuer, effect descriptor, new operation or ledger.
The helper accepts only the selected old operation's Observe and exact ACK.

The helper's verified ELF bytes are sealed in a memfd before use. Linux
`close_range(..., CLOSE_RANGE_CLOEXEC)` prevents other inherited host descriptors
from reaching it, and a parent-death signal prevents an orphan helper from
holding the old store lock after its host exits. The host observes/reaps its
own exited child before restarting that same immutable executable and target.
A timeout while the child is alive does not spawn a second helper or remove a
lock. This process composition requires those Linux facilities; it does not
silently fall back to a wider transport or different program.

After actual readback the original writer commits its existing source outcome
before issuing the original retirement permit. If the helper durably retires
the receipt but its ACK is lost, a later helper can answer `already_released`
for that exact original permit. A fresh app still reports a present null
previous receipt and keeps its own new identity and document unchanged.

The source entry consumes an already authenticated original Root/writer
composition; it is not a replacement Root bootstrap or a standalone source of
production authority. See [Notes Objective contract](NOTES_OBJECTIVE.md) and
[the concrete crash qualification](NOTES_RECOVERY_QUALIFICATION.md).
