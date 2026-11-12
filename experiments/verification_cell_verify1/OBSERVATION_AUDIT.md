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

CONSISTENT_COMPLETE_RECORDS means internal consistency of the supplied v1
fixture records. Stream order and relative clocks do not authenticate chronology;
matching records do not authenticate the source, public-feature projection or
business truth. Historical source hashes are not rebound to today's files.
Source independence, causal false rejection, generalization, complete physical
cost and production qualification remain unestablished. HOLD / NONE.
