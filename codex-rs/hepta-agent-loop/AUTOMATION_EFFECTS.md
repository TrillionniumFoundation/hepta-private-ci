# Optional native status effect adapter

The `automation-effects` feature adds `AutomationStatusEffectOwner`, an
`EffectOwner` implementation that delegates to the existing AutomationStore,
FinalUseAuthority and ProviderEffectTaskFlowDriver. It links neither Core nor
App Server. It creates no database, run, lease, grant, provider configuration or
output artifact. The fixed tool name is `hepta_automation_status_v1`.

## Original-owner composition

The trusted host first obtains the current native `Frame` from its original
TurnOwner. `automation_status_effect_run_id(&frame)` computes an integrity
mapping over the actual runner operation key, selected `next` index, frame
revision, consumed budget, original deadline and complete tool-call frame.
An independently admitted effect run in the **same AutomationStore** must
already have that ID and a prepared/claimed immutable step. Its original
`AuthorizedEffectIntent` and signed final-use grant bind that run and the exact
wire payload. This naming/digest check does not independently establish
parent-child authority; the existing host admission and signed owner grant
remain necessary.

The separate run is intentional. The original
`AutomationStore::execute_authorized_taskflow_effect_async` settles a provider
observation into both the effect step and its enclosing run. A terminal effect
receipt makes that run Succeeded/Failed. Using the native turn's own run would
therefore terminalize it before the loop could commit the tool result and
prepare another model frame. This adapter preserves those existing semantics;
it does not add a second store or alter settlement behavior. The cost is the
existing effect run, step and append-only event records required by its owner.
Their storage/I/O cost has not been benchmarked here.

Construct `PreboundAutomationStatusEffect` with that exact frame, original
intent, complete wire bytes, owner fence, signed grant and original command ID.
Then attach it with `AutomationStatusEffectOwner::new`, supplying the existing
store, FinalUseAuthority and ProviderEffectTaskFlowDriver. The constructor is a
trusted-host API, not a model-JSON admission path. It neither signs the grant
nor substitutes for the original authority's signature, nonce and revocation
checks. It accepts no alternate tool or changed call arguments. A consumer
must not use a fixture adapter's capability declaration as a production
provider-contract attestation.

## Dispatch, recovery and cancellation

Before first dispatch, the adapter checks the exact call and current effect
fence, Running state, cancellation flag and lease. It delegates original grant
consumption and immutable provider-attempt creation to
`execute_authorized_taskflow_effect_async`. The original owner places the
durable attempt barrier before provider entry.

On replay, `authorized_taskflow_effect_attempt` and
`read_authorized_taskflow_effect_receipt` validate the original immutable
identity, including its command and grant. A retained terminal receipt is read
without another provider request. An uncertain attempt is settled from local
evidence first, then queried only through `ProviderEffectTaskFlowDriver::lookup`
under its original occurrence key. Provider-owned observations pass through
`recover_authorized_taskflow_effect`. The original historical fence may settle
a late receipt without renewing a lease or granting fresh dispatch. Changed
fences, conflicting receipts and unknown lookups do not become completion.
Proven absence never creates a new attempt or consumes a fresh grant here.

The tool result is a defined **status projection**, with original intent,
payload and receipt digests and native/effect identity. The complete original
receipt stays in AutomationStore. Grants, fencing tokens and arbitrary output
bytes are not exposed as tool output. An output-bearing tool still requires
the existing provider/artifact output resolver and a separately admitted tool
contract; this adapter rejects such tools.

The provider driver exposes no cancellation operation. `cancel` prevents a new
local dispatch and returns `Unresolved`. Dropping a future, receiving a
submission receipt or observing terminal status does not fabricate a remote
stop acknowledgement. The native TurnOwner must keep its durable
CancelRequested cursor until the original cancellation owners provide their
required evidence.

## Evidence and activation limits

The scoped integration tests use the real AutomationStore, TaskFlowTurnOwner,
FinalUseAuthority and ProviderEffectTaskFlowDriver, with an explicitly isolated
test issuer and a private file-backed provider fixture. They cover exact
binding rejection, real file-effect retention, original terminal replay,
uncertain/wrong-payload lookup, cancellation after provider persistence, original
revocation, proven absence without a replacement attempt, and stale fences.
They also commit the authentic status through the actual native cursor while
the separate effect run terminalizes. The context preparer in these fixtures
uses an explicit byte-token test profile; it is not production V2 admission.

This closes a library composition seam. Production activation still requires
the existing owner to admit/register the effect run and operation, issue its
exact signed grant, configure a verified provider contract/current trust and
provide any output/cancellation owner required by the intended tool. No real
model, production effect, permission-parity benchmark or same-model Codex A/B
result is established by these controlled fixtures.

Original source at base
`332d8b448758ad45e516a208d940f2358f888e32`:

- `hepta-automation/src/authorized_effect.rs`: original dispatch barrier,
  intent-derived binding, status lookup, recovery and run settlement.
- `hepta-automation/src/taskflow_step.rs`: immutable step/fence validation.
- `hepta-contracts/src/final_use.rs`: original signed nonce/revocation owner.
- `hepta-contracts/src/provider_effect.rs`: provider capability and exact
  payload/occurrence acknowledgement contract.
