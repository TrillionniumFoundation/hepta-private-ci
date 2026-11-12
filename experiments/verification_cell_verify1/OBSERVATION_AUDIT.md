# Retained observation consistency gate

Run after the existing observation collector:

```sh
python -B -m experiments.verification_cell_verify1.observation_audit --input RUN_DIRECTORY --output NEW_AUDIT.json
```

The auditor reads saved JSON only. It binds the planned roster, trajectory
identities, event order, cost rows, optional budget, frozen model arithmetic,
training-input digest, terminal labels and recomputed diagnostics/arm summaries.
It refuses incomplete failure archives, malformed JSON, duplicate identities,
unknown terminal labels and contradictory records. Output creation is exclusive;
invalid input produces an INVALID_OR_INCOMPLETE receipt and exit status 2.
It never opens databases, reruns effects/checks, fits a model or predicts.

The v1 recorder measures sequential, non-nested operations. Their wall charges
must fit inside the corresponding phase and whole-run elapsed spans, including
the train fit; retained event clocks must cover preceding metered durations.
Checker reports also bind the exact goal, property, assumptions, checker/version,
frontier, state version and authority contract. Reconciliation cannot replay
effects. Rehashing a modified outer terminal label cannot bypass those checks.

The attribution reread and diagnostic projections cap byte reads and iterable
consumption before materializing inputs. Unknown labels still refuse attribution.

CONSISTENT_COMPLETE_RECORDS means internal consistency of the supplied v1
fixture records. Stream order and relative clocks do not authenticate chronology;
matching records do not authenticate the source, public-feature projection or
business truth. Historical source hashes are not rebound to today's files.
Source independence, causal false rejection, generalization, complete physical
cost and production qualification remain unestablished. HOLD / NONE.
