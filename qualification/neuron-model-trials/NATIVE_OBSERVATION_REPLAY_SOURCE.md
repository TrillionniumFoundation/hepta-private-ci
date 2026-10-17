# Read-only live Memory + Ledger Replay source bridge

The new AgentdSharedReplayHostV1::read_neuron_trial_shared_source_v1()
reuses the existing Agentd-owned CognitiveStore and authenticated LedgerWriter.
It does not create a second storage authority, writer or independent evaluator.

Within this deliberately one-source Replay profile it:
- resolves the current authorized Memory revision for the actual consumer,
  workspace, parameter scope and policy ID (Recall alone is insufficient);
- verifies a native frozen source using LedgerWriter::read_neuron_trial_source_v1,
  including the original signed Evaluator freeze, acknowledged ledger witness,
  current correction/revocation state and active terminal joins;
- requires every terminal decision to cite the exact currently approved Memory
  source-support digest (same content in a different source does not qualify);
- refuses a partially observed single-source trial cohort: even one Pending
  or Censored episode blocks the strict export rather than being treated as
  a terminal sample or a zero reward;
- binds the exact approved Memory ID, revision and content digest separately
  to the read-only diagnostic digest (never the Memory plaintext);
- revalidates the Memory grant and rereads the Ledger source before returning.

A returned SharedReplayNeuronTrialSourceV1 is only an internal diagnostic with
AuthorityPosture::DENY_ALL. It includes no model input text, outcomes, labels,
secrets, mutable state, selection authority or production effect. The
diagnostic digest is not an external signature. Its two read checks are not
an atomic cross-store transaction; the serving owner must revalidate at
final use and honor revocation after this check.

The existing same-host integration test uses an actual SQLite CognitiveStore
with independently granted and withdrawn source revisions plus an actual
LedgerWriter with generator/observer signed decisions and terminal outcomes.
It additionally denies same-content/different-source use and corrections.

This is one narrower Observation Owner step, not the complete Hepta real task
data feed. Further host-owned work must bind an approved observation payload
with actual question/option order/feature bytes to each Ledger event while
keeping final labels private. The selected production no-change, future time,
independent evaluation and NDU gates remain external and closed.
