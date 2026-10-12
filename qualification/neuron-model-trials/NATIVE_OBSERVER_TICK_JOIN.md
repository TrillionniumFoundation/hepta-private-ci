# Independently witnessed Neuron Tick ↔ Ledger Episode link

## Concrete owner path (diagnostic)

1. The actual AgentdNeuronOwner executes one Neuron tick through its existing
   inference.control ModelPort. Only after Journal commit and separately
   acknowledged Witness does it emit AgentdNeuronTickObservationV1.
2. The actual LedgerWriter independently verifies the original Evaluator-signed
   frozen dataset and its current durable source/Witness/revocation frontier,
   and finds the specified Decision and authenticated terminal Outcome.
3. An independently activated Observer signs the domain-separated, canonical
   neuron_trial_observer_tick_link_payload_v1 joining that native source,
   episode/Decision/Outcome, observed Agentd tick digest, objective and model
   generation. The Observer must differ from the decision's generator
   principal, controller, credential chain and signing key.
4. LedgerWriter::read_observer_linked_neuron_tick_v1 verifies the Observer
   against its own live trust distribution; a link issued before the signed
   terminal Outcome's finalization is rejected. The cohort is reread before
   returning a non-authorizing NeuronTrialObservedTickLinkV1.
5. AgentdNeuronOwner::read_observer_linked_tick_v1 first compares the
   entire supplied observation with the most recent successful observation
   retained privately by that same Agentd owner, then checks the exact current
   Journal/Witness before AND after the Ledger read. An externally rehashed
   observation, changed checkpoint or withdrawn source fails closed.

Every returned digest is an integrity commitment; this code does not create
an independent evidence issuer, sign any production assertion, disclose
private observations or labels, infer CNS route selection, load physical
model weights, dispatch an effect, or authorize NDU/production promotion.
The Observer signature attests an episode↔tick association, not an
independently measured host clock or physical inference proof.

The Ledger unit tests use its actual durable owner, frozen signed
Decision/Outcome and ephemeral fixture keys. They cover the positive
signature, signature before terminal finalization, changed tick digest,
wrong objective, missing Episode and wrong signing role. The Agentd
compile-time owner test locks the witnessed method into the actual product
API; neither test set is real Hepta task learning data.

Critical remaining producer-side work: retain a signed historical tick
observation across later Neuron updates, attach actually authorized
observation content/option order to the Ledger Decision, correlate the
real Supervisor selected Cell and CNS route, independently verify final-use
and physical Artifact CAS, then run two genuinely elapsed future windows
through ProductEvaluationRunnerV1 with complete NDU/cost/recovery evidence.
Current tick revalidation is intentionally invalid after any subsequent
direct tick attempt, failed execution, or process restart. The owner retains
only the most recent successfully witnessed observation in memory. A digest
that is internally self-consistent but was not produced by this exact owner
cannot be substituted. This short-lived cache is not a crash-durable
historical observation log and cannot prove archived no-change outcomes.

Run exact-SHA Cargo check/test/Rustfmt/Clippy for hepta-learning-ledger,
hepta-agentd and the independent Neuron trial CI. No production
route, permission, rollout or retained model state is modified.

## Bounded one-to-one Observer-signed cohort

A single valid per-Episode Observer signature does not by itself prevent
the same committed Neuron tick from being credited to several Episodes.
The additive read-only Ledger
\`read_observer_linked_neuron_cohort_v1\` verifies one independent
Observer signature for the complete frozen cohort (maximum 256 terminal
Episodes per diagnostic). The canonical signature payload binds every
native Decision/Outcome pair, Objective, selected candidate/policy/source,
and one distinct external Agentd tick-observation digest and Generation.
The canonical mapping is sorted by Episode identity, not caller order.

The native Ledger owner requires no missing/duplicate/extraneous Episodes,
no duplicate Tick digests, no mixed Neuron model generations within a
frozen no-change cohort, no Pending or Censored outcomes, and an Observer
signature issued after **every** matched finalization. The signer must be
independent of **every** Decision generator. It rereads the live Ledger
source and withdrawal frontier after verifying the signature. The output
is a data-free, recomputable \`NeuronTrialObservedCohortV1\` with DENY_ALL;
its digest is not an authorization credential.

A test uses an actual frozen native Ledger and independently signed
Observer fixture to prove admission and reject early/wrong-role signatures
and swapped tick digests. Additional negative protocol tests demonstrate
that even a caller-rehashed two-Episode source cannot double-credit one
Tick or omit an Episode. They do NOT claim those fabricated cases came
from the real Owner. This read does not persist a historical tick journal;
a production evaluation must still preserve independent tick evidence,
ensure uniqueness across separate windows, and authenticate the actually
selected CNS/Cell/model/Artifact physical runtime at every final use.

## Single-use Agentd owner-issued in-process cohort (new)

AgentdNeuronOwner::tick_with_observation_v1 now retains at most 256
consecutive, actually executed and independently Witness-acknowledged ticks.
This is a memory-only series, never reconstructed from a caller digest.
Each subsequent observed tick must have the next exact logical sequence,
matching previous checkpoint, and the same Scope, Objective and Generation.
Model identity cannot change inside the exclusive NeuronRuntime instance.
Direct ticks, failed execution or Witness uncertainty clear the trail.

AgentdNeuronOwner::read_observer_linked_cohort_v1 verifies the complete series
against the exact Observer-signed native Ledger batch, requires one unique
owner-issued tick per Episode, rechecks the current Witness before and after,
and consumes the entire in-process trail on any read attempt. This prevents
the same in-process issuance from being reused for another signed batch.
An incomplete/mixed-generation batch is rejected, not partially scored.

This is NOT crash-durable historical evidence: process restart loses the
issued series. A separate durable trusted evidence owner must still retain
the original source observations, historical signed Tick acknowledgements,
cross-window uniqueness, actual CNS/Artifact selected model and elapsed
outcomes before production no-change/NDU evaluation can be authorized.
