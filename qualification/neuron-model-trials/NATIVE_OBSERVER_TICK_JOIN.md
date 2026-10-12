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
5. AgentdNeuronOwner::read_observer_linked_tick_v1 checks the exact current
   Journal/Witness before AND after this Ledger read. A changed tick checkpoint
   or withdrawn source fails closed.

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
Current tick revalidation is intentionally invalid after a later tick;
it cannot be used to forge archived no-change outcomes.

Run exact-SHA Cargo check/test/Rustfmt/Clippy for hepta-learning-ledger,
hepta-agentd and the independent Neuron trial CI. No production
route, permission, rollout or retained model state is modified.
