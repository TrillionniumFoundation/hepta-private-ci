# Original selected-law input recovery

This stage recovers one original input after the transient executor was replaced. It does not recover the lost n128/n512 exports or inherit their execution identity.

The original Actions artifact 13904346161 was downloaded again and matched exactly: 19,217,333 bytes, SHA256 `8c94ecc88540079506e1702634049057bca5fb464b9c97f06fc923e013db81f8`, source `5578bd1931afcb6facbf72176cf479b902301feb`. The retained original experiment SUMMARY is byte-identical (SHA256 `c60378ffc2a51f580a9b7cfd11a09cec5f53d9a9cc37c03b81605bedc54b8715`).

`SELECTED_ORIGINAL_LAW.json` contains the exact JSON numbers from seed37 / c0_b1 / update 24 / position 1 / visit 897: the 25-cell posterior, its four signed-content columns, original physical parameters, grid, gap and episode/model identity. The original journal is 3,797,906 bytes with SHA256 `2a9fc79e38311147451511c5b6ecc17449faa544cc38bcaab567e4f9cbe08517`. Its original line 25 is retained, including its LF, as `selected-line25.original.jsonl`; `origin_line_payload_sha256` explicitly excludes the LF. No floats were rounded or refitted.

The journal hash and selected identity match the previously published actual-migration SUMMARY at `62f392a0ed953f2d04e9c62b4b243f5cceed2a98`, Git blob `4f767e324967951df1ba0799c69bd9d40d0ad038`. Independently reading all 14,336 valid stored states from the restored 12 journals selects the same maximum first-cell posterior: 0.1779507048816143 at visit 897. This is stored-data selection, not a training or numerical audit rerun.

`RECOVERY_RECEIPT.json` preserves artifact, journal, original-line, selected-state and FP64 little-endian array hashes. `GRADED_SELECTION_WITNESS.json` is a labelled extraction of the published selection and journal hash, not a replacement for that original SUMMARY. Every uploaded Git blob was compared with the local Git object hash.

Zero models, optimizer steps, filtering or numerical rollouts were executed. Any new n128/n512 fixed-prior export must record its own source/runtime/input identity. The old lost NPZ files remain lost. This artifact stage grants no numerical, gradient, training, task-benefit or adoption qualification: HOLD_NO_GO.

The commit uses `[skip ci]` because it preserves input bytes only and should not trigger unrelated automatic model fixture execution. This does not waive or change any scientific gate.
