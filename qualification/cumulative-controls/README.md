# Cumulative public-task controls

This separate diagnostic retains the completed six-arm source experiment and
adds two control lineages. It never publishes CURRENT, installs a child, or
issues product qualification. Candidate ordinals remain unadmitted candidates.

The first round reuses the original, hash-verified fresh LoRA and full-tune
checkpoints and their actual receipts. Each control then loads its own preceding
weights and executes another ten steps twice. LoRA keeps the original control
learning rate `0.001`; full tuning keeps `0.0001`. Every round creates a new AdamW
optimizer, exactly as the original candidate trainer does. It does not resume
optimizer momentum, restart from pretrained weights, or reinitialize inherited
LoRA factors.

The original ten-step plan bytes, target CID, task order, tokenizer, seed and
runtime source remain unchanged. The new controls use separate schemas and
labels. Their original evaluator protocol role does not make a cumulative control
a fresh ten-step control. Parent checkpoint hashes, actual loaded tensor roots,
ancestor receipt hashes, per-round training counts, cumulative counts, complete
weights, predictions and resource observations are retained.

The comparison verifies cumulative **post-genesis steps, input tokens and
supervised tokens** against the actual source candidates. It does not establish
equal wall time, CPU time, peak memory, total FLOPs, pretraining cost, or equal
economic cost. Original fresh controls and their earlier
`CumulativeBudgetMismatch` observations remain intact. The new report states the
narrow cumulative schedule result separately. Public repeated tasks do not
establish independent future-task quality or `SystemLongitudinal` qualification.

The original source run, commit, artifact IDs, complete ZIP hashes and evidence
index hash must be pinned before execution. Downloading verifies the complete
original ZIPs, extracts only regular relative members, and retains only the
specified candidate and first-round control checkpoints. Each consumed record is
checked against the original evidence index again. A missing or failed source
campaign blocks execution; no fixture or synthetic candidate replaces it.

The dedicated workflow uses a fresh hash-locked CPU Python environment and the
same public material revision. It runs no Rust build, no ordinary Agentd session,
and no candidate training. Source candidate predictions are reverified against
their frozen task/artifact identities. The new control evaluations execute real
forwards through the original evaluator. Costs from different hosted runs are
reported as observations, never assumed equal. All success and failure records
and every newly trained checkpoint must be retained.

The small metadata and archive tests are negative controls for hash, ancestry,
count and path handling. They are not evidence that a neural model loaded or
trained. Only terminal hosted execution receipts can establish that outcome.
