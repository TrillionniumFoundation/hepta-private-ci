# Retrieval policy reference

Status: candidate semantics, not a calibrated production policy. Policy changes require new digests, context publication and exact-source qualification.

## Admission and evidence

Admission requires `weighted_score > 0` and `weighted_score >= minimum_total_score`. Coverage, OOD, proposition conflicts and HNMF seeds derive from that admitted view. The complete observed union remains available for receipt/count accounting. This prevents a below-floor candidate from poisoning a decision; it does not guarantee immunity to additional *admitted* evidence or top-k competition.

Only nonzero-weight channels satisfy coverage. Do not lower coverage/OOD/score limits automatically after an error. `maximum_results` truncates selection, not source enumeration. A saturated generator reports `LimitReached`; it cannot claim causal enumeration completeness.

## Current SQLite baseline

The owner profile exposes lexical, entity, temporal, associative graph, causal, procedural and contradiction-support channels. Each has a one-eighth fixed-point weight. The source baseline uses `maximum_results=16`, `minimum_total_score=0`, `maximum_ood=1`, and `minimum_distinct_channels=1`; the adapter supplies OOD zero. These are compatibility-oriented values, **not calibrated OOD estimates**. Vector evidence is not enabled by changing a label or reusing lexical/RRF scores.

A release profile needs independently measured in-domain/OOD data, false-accept and false-abstain rates, source dependence, query/risk strata and a signed calibration identity. No such accepted profile is created by this remediation.

## Engram semantics

`minimum_activation=0` remains valid for experiments, but every support-producing node must satisfy both `activation > 0` and `activation >= minimum_activation`. Zero is never an active node. Zero-weight synapses do not expand the graph, alter dynamics or create semantic conflicts. A graph digest may still differ when a zero-weight edge is present; semantic neutrality is not byte-identical provenance.

Confidence is the activation-weighted average of node confidence, using checked wide integer arithmetic. A zero total activation returns zero confidence. This arithmetic is deterministic but not a calibration certificate. Nonzero-weight contradiction edges require active endpoints; proposition polarity conflicts are evaluated independently on admitted evidence.

Hard structural limits include 512 generation-bound candidate records, 4096 nodes, 32768 synapses and four settling steps. The default population cap is 64. Capacity increases require revised resource proofs, full-ceiling probes and host SLO evidence, not a silent constant change.

## Publication and policy changes

Bind the retrieval policy digest to `generation_vector.retrieval_profile_digest`; bind the graph to that same generation vector. Context publication signs objective/context/cue, policy, graph and dynamics identity through the context binding digest. Model, tokenizer, template, tool schema, encoder/preprocessor, compact checkpoint and prompt registry generations must come from their actual owners.

After a change, publish an advancing frontier sequence, install the matching signed publication, and reject in-flight work when its final-use context no longer matches. Reinstalling the old publication never refreshes its lease. Rollback to old code or an old policy is a *new authorized publication* at a higher sequence, not a rollback of the authority floor.
