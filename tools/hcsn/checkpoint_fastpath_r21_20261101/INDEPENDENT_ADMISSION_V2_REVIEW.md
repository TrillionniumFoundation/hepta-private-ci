# Independent V2 admission result

After source publication and readback at `df35a6d3869cbcafce8e15b9e40d4bcdd1164439`, all 60 prospectively declared cases passed. The checker used a newly generated engineering world on CPU 0–6 with one BLAS thread. No frozen source was changed.

The full, packed and anchored normal checkpoints round-trip exactly. Their admitted operation maps contain only the three declared nonnegative integer counters; their probability and anchor arrays are separately owned after restoration. Changes to the input payload, restored actor and exported snapshot do not cross these ownership boundaries.

Thirty counter-shape controls reject bool, list, dict, float, NaN, negative counts, missing/extra keys, and non-dict maps before invoking the inherited restorer. Additional unknown-schema and projection/method controls also reject before delegation. The NaN check is explicitly a direct object control rather than a fabricated canonical JSON checkpoint. Nine checksum, probability and clock controls reach the original restorer and retain its rejection behavior, so the local preflight strengthens metadata admission without bypassing existing state checks.

Nine actual executor controls exercise both restore call sites and the final guard across all three representations. Rechecksummed malformed data returned after persistence is rejected before the inherited restorer runs. A rechecksummed malformed cold-resume checkpoint is rejected before producing a new checkpoint. A changed restored operation count is still detected by the newly generated post-restore checkpoint comparison. Actual committed bytes are retained with these cases.

This closes the discovered mutable-counter and R15 propagation-metadata admission gap in the R21 executor path. The inherited R15/R16 public restoration methods remain unchanged; their V1 counterexample is retained as historical evidence. Resource evidence remains the earlier modest, mixed engineering result and does not qualify a full adoption gain. The V2 cold-process campaign is recorded separately by its owner.
