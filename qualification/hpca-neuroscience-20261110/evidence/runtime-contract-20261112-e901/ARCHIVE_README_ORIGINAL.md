# HPCA: retained native greedy-output negative result

Execution source: 0b75caf446a18807e527f8e2ed9937ae3cae515d. Original native job: 1a1cd370436-2564-121a, exit 0. This is the same ai395 host and the eight original retained adapters; the full model/adapter snapshots and exact runtime are in PREEXECUTION.json.

There are 24 already-public operator OOD prompts, nine conditions and 216 completed generation attempts. Every condition has 0/24 valid leading YES/NO labels and 0/24 correct responses under the frozen parser. Every raw emitted sequence is [(2,)]; all-first-token-EOS=True. The raw generated text set is ['']. These are 24 unique tasks, not 216 independent tasks.

The maximum allowance stayed eight tokens, with native EOS stopping. Original two-choice scores normalize only the yes/no logits and are a different inference procedure. This new negative observation does not flip labels, fit a threshold or repair the exposed B2 into confirmation. No training was run.

Preserved here: original result, preexecution record, all row starts/completions, launch/exit metadata, full stdout/stderr, outer GNU time record, 39-test raw log, runtime/source/asset hashes and formatting status. The source/runtime contract passed before the new model execution. GitHub Actions remains a separate acceptance surface. An independent raw-row re-score is still required before citing derived aggregate conclusions.

Measured phase cost is 10.227863733889535 seconds wall / 33.180033789 seconds CPU; it excludes imports, tokenizer and initial hashing. MODEL_RESOURCE.log records the outer model process, not full lifecycle acquisition/host-control/energy costs. Lifetime peak RSS is not additive across conditions.

Independent calibration, future sources and old-task retention remain MISSING. HOLD_NO_GO / DENY_ALL; no scientific, Owner, policy or production adoption claim.
