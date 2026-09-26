# memory.retrieval policy reference

## Admission order

The normative order is: validate owner and generation; enforce generator and channel capacities; canonicalize exact record/channel duplicates; compute weighted scores; apply the score floor; form the policy-admitted set; evaluate admitted channel coverage, proposition/polarity contradiction and OOD; settle HNMF only from admitted support; rank and truncate selections; revalidate exact owner state before text materialization.

A candidate below the admission floor cannot poison an accepted result through OOD, contradiction or recurrent activation. A later low-score candidate cannot remove a higher-score result unless it contributes explicit admitted safety evidence under the same proposition/generation.

## Contradiction semantics

A contradiction key is `(scope, proposition digest, applicability interval, generation)` and each item carries `Supports` or `Opposes`. Two or more items on one side are same-side support. Conflict exists only when both sides are admitted for the same key, or when a positive-weight active engram contradiction edge connects two admitted active nodes. Zero-weight edges are absent semantically.

## Activation and confidence

`minimum_activation` is in `(0, 1]`. Zero activation never yields support, coverage, confidence or contradiction. Receipt confidence is `sum(activation × node confidence) / sum(activation)`. Calibration, source-independence corrections and risk-class thresholds remain profile-owned and must be versioned.

## Product profiles

`compatibility` uses the canonical owner-ranked path and forbids an attached HNMF provider. `shadow` requires a current provider, evaluates HNMF and records non-exposure evidence without changing delivery. `canary` applies HNMF to a deterministic bounded sample and evaluates the remainder as shadow. `required`/`hnmf-required` applies HNMF to every request and fails closed on absent, stale, expired or revoked context.

## Vector channel

The Vector channel may receive positive weight only from a registered encoder/index owner whose batch is bound to the same generation and model/encoder identity. Lexical, graph, reciprocal-rank or learned-ranker scores may not be relabelled as vector evidence. Until that owner exists and is independently qualified, production profiles keep Vector disabled.
