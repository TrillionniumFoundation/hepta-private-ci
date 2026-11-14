# Guarded V13 ordinary runtime qualification

`neuron_v13_guarded_acceptance` is an explicit Linux qualification executable.
It runs the existing V13 MiniLM encoder and trained adapter process through the
ordinary Agentd runtime, with actual artifact publication, CURRENT, signed
FinalUse claims, Cell journals and independent witnesses. It uses public fixture
issuer keys and new isolated stores. It does not activate a production model.

## Inputs and execution

Build the example with the repository's pinned Rust toolchain. Use an isolated
target directory when other builds are active:

```sh
cargo build --locked --offline --profile dev-small \
  -p codex-hepta-agentd --example neuron_v13_guarded_acceptance
```

Prepare the original model, complete learning closure and frozen encoder assets
with `make_descriptor.py`. The assembler hashes the qualification sources and
actual interpreter and assets. It does not execute the model. A newly prepared
host environment gets a new descriptor and source receipt; an old environment's
descriptor must not be relabelled as evidence for the new environment.

The executable requires six arguments:

```text
neuron_v13_guarded_acceptance \
  ABSOLUTE_DESCRIPTOR EXPECTED_DESCRIPTOR_SHA256 \
  NEW_OUTPUT_DIRECTORY NEW_ROOT_AUTHORITY_DIRECTORY \
  ABSOLUTE_SECOND_TASK EXPECTED_SECOND_TASK_SHA256
```

Both output directories must be new. Their parents must already exist and be
canonical paths. The authority directory must additionally satisfy the existing
`RootAuthorityDirectory` contract: effective root and root-owned, non-writable
ancestors. The executable creates the two directories with mode 0700. It never
changes sudo rules, installs a service, resets an existing authority frontier,
or modifies a prior owner's files to make a failed run pass.

Both acceptance examples use the production arg0 helper dispatcher. Their
synchronous preflight creates the new Fleet identity and binds its process home
before helper aliases, environment loading or runtime threads are started.
Every embedded App Server receives the resulting real helper paths. Reopened
sessions retain that same home; a different home is rejected. A readiness
failure preserves the underlying runtime error as well as the driver failure.

The second task uses the existing closed `hepta.v13.task-input.v1` schema and
must differ from the descriptor task. Its expected SHA comes from the caller.
The owner constructs the admitted request and obtains its pending expected
context from the durable journal. A producer result cannot supply that context.

A control RPC can lose its response while the original computation continues.
On `CommitUncertain`, the driver first reads the healthy journal and requires
the identical original pending request. It then uses only the existing
`reconcile` readback for that request digest, within the original host-clock
deadline, and records the observed uncertain response on stderr. It never
admits or dispatches a replacement operation. A poisoned journal or witness,
closed service, changed identity or missing pending request fails closed and
requires the corresponding owner recovery; this helper does not repair it.

## Observed lifecycle

The executable checks these steps using the production APIs:

1. Publish an initial generation with one signed FinalUse operation. Start the
   ordinary App Server/Fleet runtime and run the actual V13 process. Leave its
   output unacknowledged and retain the resulting bounded drain failure.
2. Recreate the ordinary runtime and reopen the original signed publication in
   the same runner process. Preserve its prepared worker capability. Check the
   original receipt, output, cost and owner history without another model
   dispatch or FinalUse claim. Write and fsync a receiver file, acknowledge the
   exact output and retain the drained checkpoint.
3. Reopen the predecessor using the original V13 identity, boot and witness
   constructors. Prepare a distinct task/run with the identical full model and
   runtime manifest and a new generation/writer epoch. Consume its separate
   signed FinalUse operation, advance CURRENT, and check the old owner is fenced.
   Run the actual model for the second task, deliver and acknowledge its output,
   drain and record the second checkpoint. Preserve the predecessor bytes.

`AgentdV13GenerationUpdateInputsV1::reopen_predecessor` exposes only the typed
predecessor inputs needed by the existing cold coordinator. It starts no worker,
adds no preparation observation, and grants no dispatch or publication right.
The coordinator still checks the actual journal's drain, witness and CURRENT.

## Evidence and boundaries

`START.json`, publication signatures and witnesses, unacknowledged observations,
delivered bytes and checkpoints are written create-only. `RESULT.json` records
the observed source/input bindings and owner observations. An error writes
`FAILURE.json` and retains the original files. A failed or uncertain operation
must not be retried under a new operation identity and called successful.

This is runtime-instance reopen within one runner process. It is not a fresh OS
process, host reboot, power-loss, or CURRENT/FinalUse unknown-outcome fault
campaign. A future fresh-process run must account for its actual additional
worker preparation observation instead of treating all new preparation cost as
an erroneous duplicate.

The actual delivery is a local fsynced receiver file. It does not establish
external delivery, production privilege separation, production adoption, general
model quality, work-cost eligibility or a complete cryptographic computation
proof. The V13 profile is distinct from public Chain Cell proof profiles.
No result here authorizes combining their independent passes into a claim that
a Chain computation proof reached this runtime's guarded commit boundary.

The Cell journal's single commit frame binds the consumed request identity,
state, prefix, outbox and cost. CURRENT, artifact selection and retained FinalUse
are rechecked by their existing owners. This executable does not claim one
atomic transaction across all those separate stores.
