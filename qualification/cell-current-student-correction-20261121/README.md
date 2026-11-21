# Current-student A correction candidate

This is a new bounded experiment, based on evidence head `e147c1d851b0a5b5c03dbeb0285d443bd7057973`.
The completed experiment's 56 calls and two 32-update fits remain closed. No old future task is eligible for new blind confirmation.

`corrections.py` verifies the original six-input A readback, the original engine protocol, and both current-student manifests. It selects the first actual native failure for each student and A project: document student attrs/rich; native student attrs/platformdirs. The total 16 A calls, 12 native executions and 4 admission refusals remain in the evidence. The second attempts remain provenance, not additional independent projects.

Every correction prefix is the actual request, that student's failed assistant action and actual native feedback. Those tokens are masked. The sole target is the previously verified maintainer repair, checked against the saved failed source and exact verified AFTER bytes. Full source snapshots bind provenance; the model context contains the emitted replacement function, not a claim that an entire source file was added to the prompt.

Both separate continuations use the native chat layout. Their parents and own-policy data differ, so the two continuations are not an information-matched contrast of layouts. Each has a new 8-update cap, for 16 total; no generation or native execution is included in this candidate. Confirmation needs a separately frozen unexposed panel and evaluation budget.

## Execution

1. Run `python corrections.py --source-root SOURCE --output NEW_PREPARED` and publish the frozen code, corrections and protocol before training.
2. Use the original qualified Python environment to run `python learner.py encode --prepared NEW_PREPARED --artifact-root ARTIFACT --framework-root ORIGINAL_FRAMEWORK --engine-directory ORIGINAL_LAYOUT`. This loads only the tokenizer, verifies all base/adapter files and runtime hashes, refuses truncation, and saves exact token groups and compute budgets. Publish that receipt before fitting.
3. Run the same command with `train --mode document_evidence`, then `train --mode native_feedback`. Each fit takes a nonblocking candidate-local owner lock and writes an exclusive budget claim. A failed or interrupted claim is retained; the script does not retry. It loads the exact current adapter, verifies its parameter digest, starts an empty AdamW optimizer, retains the parent files, and saves a new adapter under the candidate digest. Each optimizer step has a durable `UPDATE_STARTED` before execution and `UPDATE_COMPLETED` after it. Failure receipts distinguish durable completions, full step rows, and the conservative possible actual update upper bound; a damaged journal keeps the full reserved cap.

Original desktop paths: ARTIFACT `/dev/shm/hepta-cell-experiments-v3-20261116-0c078a`; ORIGINAL_FRAMEWORK `/home/qian-qi/work/hepta-e1-matched-info-20261118-2e9b/source`; ORIGINAL_LAYOUT `/home/qian-qi/work/hepta-upstream-layout-learning-20261118-2e9b-checkpoint2/source/qualification/cell-upstream-layout-learning-20261118`. The candidate must be deployed into a new owner directory. It does not rewrite these original sources, acquire old locks, or initialize a replacement LoRA.

## E1 interface and limits

`comparison.prepare_request` provides frozen and bounded lexical retrieval controls over the same permitted A evidence, preserving the original query and history. `learner.load_model` loads either retained parents or new saved children with base/adapter/parameter verification for the existing predictor interface. Calling inference requires the separately bounded evaluation phase.

`final_only` and `all_actions` encode identically here: each record has only one verified positive assistant turn. `comparison.require_distinct_objectives` refuses to call this a distinct comparison. Failed assistant actions are never positive labels. A future trajectory-supervision experiment needs verified positive intermediate actions and a separate protocol. The 49-parameter direct solver and WSP program search are distinct hypothesis classes and cost scopes.

`python -m unittest -v test_corrections.py` runs offline integration checks against retained archives, real chat serialization, parent/state provenance, corruption rejection, exclusive freezes, and the degenerate objective. It performs no inference or native test execution.
