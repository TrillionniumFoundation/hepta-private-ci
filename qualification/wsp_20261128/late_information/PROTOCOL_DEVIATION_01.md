# Retained protocol-order deviation

The first late-information experiment completed numerically, but did not follow
one pre-fit validation ordering requirement. The original protocol and executed
source are preserved unchanged.

The protocol requires comparison of the reduced expression with a separate
complete bridge forward **before fitting**. The executed runner first checked
the reduced gradient by finite differences, then fitted/selected the BP and
random candidates. The independent complete Rust comparison occurred after
candidate sealing and new TEST generation. Thus that specific pre-fit gate was
not met at its registered time.

The later 15 full candidate comparisons all passed: maximum feature error
2.384185791015625e-7 and score error 4.76837158203125e-7, against the unchanged
2e-6 tolerance. This supports the numerical consistency of the reported frozen
results; it does not retroactively satisfy the required chronology. No test
outcome was used to change candidates, and no training is rerun to erase this
deviation.

The overall scientific record is therefore `COMPLETED_WITH_PROTOCOL_DEVIATION`,
not an unqualified fully compliant prospective experiment. A future reusable
interface must require the completed pre-fit gate before issuing a fit/selection
stage token.

Independent review also noted that the exploratory `compile_sign` helper does
not implement its general all-zero-head ABSTAIN branch. All three executed
parents have nonzero signed-head contrasts, so the omitted general case did not
affect these observations. The reusable compiler must explicitly reject or
abstain when no signed channel can carry the declared price relation.

Interpretation boundaries: BP64 trains the exact reduced four-parameter final
map, not the whole model. Seed137 has radius zero, so DIRECT/RANDOM/BP are KEEP
aliases there. The explicit request mode is a supplied task route; no task
recognition has been learned. Forty paired contexts, not eighty independent
contexts, form the new final task panel, reused across the three parent models.
