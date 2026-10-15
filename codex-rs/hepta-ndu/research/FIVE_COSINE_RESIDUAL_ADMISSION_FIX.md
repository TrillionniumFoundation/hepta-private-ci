# Admitted TRAIN census correction for the cosine residual study

Date: 2026-10-15.

The v2 residual run `38663640831` passed the new receipt-binding regressions,
all inherited residual/cosine/crossed/Encoder tests, immutable origin checks and
all five archive SHA checks. It then stopped before Encoder loading or residual
fitting with:

```
five_causal_experiments.Invalid:
complete admitted TRAIN own-source census required
```

The failure is retained as a real blocked execution. It is not a negative model
result and does not establish zero gain.

## Root cause

Question selection happens before answer and evidence eligibility. The selected
TRAIN list therefore includes questions that are later rejected by the existing
training admission rules. The saved relevance plan contains only the admitted
question units. The previous residual reconstruction incorrectly required the
annotated admitted rows to equal the entire pre-eligibility selected identity
set.

The correct invariant is narrower and stricter:

- every saved admitted relevance unit has exactly one annotated-answer original
  source row;
- no annotated-answer row exists outside the saved admitted unit census;
- every admitted unit is traceable to the original selected audit list;
- selected but non-admitted questions remain recorded and are never fabricated
  into training;
- missing donor status does not remove an admitted question's own source;
- no replacement question or donor is selected.

## v3 correction

`shared_gate_cosine_residual_trial_v3.py` retains the immutable-artifact receipt
correction from v2 and changes only the TRAIN own-source projection. It records
selected, admitted and selected-but-not-admitted counts and digests in the rebuild
receipt. New pure regressions cover selected supersets, exact admission coverage,
missing/extra/duplicate rows, units outside selection, unavailable donors, input
immutability and direct CLI execution.

A separate v3 workflow and artifact name preserve the cancellation and all three
blocked attempts. `cancel-in-progress=false` prevents unrelated branch pushes
from cancelling this exact run. The cosine threshold, residual architecture,
arms, labels, seeds, 256-step budget, learning rate, donors and SELECT readout are
unchanged.

No model execution, residual benefit, semantic accuracy, Reader admission or
production permission is claimed until the v3 workflow completes.
