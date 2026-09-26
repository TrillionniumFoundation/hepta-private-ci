# ADR 0003: explicit statement stances, delivery isolation and read-only qualification

Status: implemented source candidate; independent product acceptance remains separate.

## Owner-issued statement evidence

A retrieval channel is not a statement polarity. Each native candidate, union
entry and selected reference carries an ordered set of actual
`ContradictionEvidenceV1 { proposition_digest, polarity }` pairs. Sets are bounded
at 64, unique, nonzero and hashed into native receipt commitments. Merging
channels unions actual pairs; it never forms a Cartesian product of channel
names and legacy group digests. Two opposing stances on the same proposition
conflict even in the same channel. Repeating one stance through several channels
does not create a conflict. Different propositions remain distinct.

The SQLite owner reads immutable revision facts in the same transaction as its
bounded candidate observation. Only exact predicates `supports_proposition` and
`opposes_proposition`, targeting an entity of type `proposition`, supply stances.
The proposition identity binds owner, scope, canonical target and the common
read instant. Both entity and relation validity must contain that instant.
Reading more than 64 applicable fact rows fails closed rather than truncating
away an opposing statement. A generic `contradicts` edge is not silently promoted
into a positive or negative stance. Existing facts need an explicit owner-owned
semantic migration; no text classifier is assumed by this protocol.

Native identity domains and digests bind the added evidence. Canonical
`cognitive.types` wire contracts are not silently rewritten. Persisted receipt
consumers must use the matching native version and may not equate old hashes
with new statement-aware claims. Hash consistency is integrity, not an
independent signature or source-authentication proof.

## Product delivery modes

The real process selector accepts `compatibility`, `hnmf-shadow`, `hnmf-canary`
and `hnmf-required`. All HNMF profiles require explicit trusted provider
composition at startup. The ordinary binary still does not invent a model,
provider, independent recovery witness, calibrated profile or release approval.

`hnmf-shadow` computes a possible HNMF selection without changing compatibility
ordering or delivery. An unusable shadow context cannot poison the compatibility
response. Shadow assignment evidence has no HNMF delivered subset and no exposure
claim; a compatibility ranker is not relabeled as a shadow treatment.

`hnmf-canary` uses a versioned deterministic five-percent owner cohort. The owner,
not the request payload or current body generation, fixes the arm. Treatment uses
required-mode failure closure; control uses shadow isolation. This operational
cohort is not a claim of randomized causal identification. The immutable mode
and cohort policy bind treated read receipts, so switching mode invalidates
previous treated final-use receipts. A cohort change requires a new version and
independent rollout approval.

`hnmf-required` preserves all current-context lease, lifecycle, source-cut and
final-use fences. No automatic fallback occurs on its treatment path.

## Qualification source must not mutate itself

The final candidate contains ordinary reviewable Rust source. Temporary
source-materialization/self-push workflows and their one-shot patch scripts are
removed. Historical commits and logs remain audit history, not an accepted
production workflow. Qualification uses read-only repository permissions,
credential-free checkout, exact source/tree observations and deterministic
ordered-parent synthetic commits without updating repository refs. Test
execution uses the repository `just test` entry point. No failed, cancelled or
skipped lane counts as success.

Actions artifacts retained for 90 days are operational copies only, not approved
long-term WORM storage. Independent current-head review, named-host acceptance,
full-pipeline SLO measurements, durable provider recovery and calibrated encoder
composition remain distinct release requirements.
