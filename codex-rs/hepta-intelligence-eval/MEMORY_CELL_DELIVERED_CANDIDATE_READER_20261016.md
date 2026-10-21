# MemoryCell — source-delivered original Reader causal probe (2026-10-16)

**Status: experimental source until a successful original model run is observed.**
No new neural inference, independent source population or qualified reviewer
judgment is inferred from pushing the code.

## Why this is the immediate next experiment

The previous frozen SmolLM2-135M candidate-ranking benchmark mined **all**
possible site/mode IDs in the full original query scope, including sources not
delivered to the actual evidence arm. This was a meaningful *answer-space
Oracle upper bound*, but not an admissible online RAG or MemoryCell policy.

The new implementation constructs answer options **only from the original
events actually delivered in each arm** plus a fixed refusal sentence.
The empty arm has only the refusal option. There is no answer-conditioned
candidate selection, hidden-corpus scan, label peek or post-hoc addition of
target values.

The Reader is the same SHA-pinned 30-layer original 135M FP32 CPU model;
the original six-arm prompt, max 2,048 input tokens and deterministic
conditional mean token-log-likelihood ranking remain unchanged.
Every arm invokes an actual model forward pass, even the empty arm. Candidate
counts and forced-scoring token costs are arm-dependent and are measured,
not asserted to be equal. This is **forced-choice recognition**, not
autonomous/free-generation Reader capability or new trained memory.

## Sealed source and scoring order

The original authored eight-case six-arm source archive is pinned to SHA-256
31c6f191ecf62095779f7c9a5dd6c5b2f89c6ae408fe9c26f74e017a2d62c47a.
The old immutable Reader archive is GitHub artifact 11586991191, exact ZIP
SHA-256 07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af.
The existing model file pins reject any changed weights/tokenizer.

All 48 original call records are fsynced before the original answer labels
are opened. The journal records actually delivered source IDs, source-byte
hashes, option IDs, model/input identity, forced scoring and failures.
The original typed source-local reader subsequently checks whether the
winning candidate has a *complete provenance chain*. A terminal answer
still present after deleting its necessary prerequisite is NOT promoted
to a valid supported answer. The original authored constrained procedure
worker is executed once per original procedure question and arm: 12
original checks in total.

Report each of the following distinctly: forced-choice correctness;
deterministic typed chain completeness; source-bound task success; original
worker checks and passes; total tokens, hypotheses and observed CPU time.
These typed citation paths are NOT generated neural citations, externally
reviewed entailment or proof of an autonomous coding agent.

## Independent process / retained evidence boundaries

A second Python process reloads the unchanged original source archive,
checks every source-local candidate, model-result ranking, task identity and
score row, recomputes every typed causal chain, then independently reruns the
twelve constrained original program checks. This verifier does **zero model
forwards** and cannot prove the original logits were produced by the claimed
hardware, despite pinned tensors and replayed score structure.

The raw question/answer journal stays in the ephemeral host workspace.
Only sanitized source/code SHAs, aggregate results, original-journal digests,
test failures, CPU resource receipts and no-go flags enter GitHub Actions
artifacts. A completed hosted run does not create new source families,
independent semantic human reviews, or fully observed lifecycle cost.
Unknown revocation/recovery costs remain null, not zero.

## Reproduction on a compatible compute host

    python3 -m unittest discover -s scripts/memory_cell -p test_delivered_candidate_reader.py -v
    python3 scripts/memory_cell/hf_original_parity.py stage PINNED_MODEL_ZIP MODEL_DIR
    python3 scripts/memory_cell/delivered_candidate_reader.py PINNED_EVENT_ZIP MODEL_DIR PRIVATE_RUN --source-commit EXACT_COMMIT
    python3 scripts/memory_cell/delivered_candidate_replay.py PINNED_EVENT_ZIP PRIVATE_RUN REPLAY.json --source-commit EXACT_COMMIT

The source-only regression fixtures are synthetic mechanics tests, not fresh
models. The dedicated read-only GH workflow must run on the exact source
commit, and its terminal result and true source pin must be inspected before
calling inference completed.

**NO-GO:** No promotion, learned parameter-memory superiority, production
selected-reader activation, new independent-family claim, or blocking-ci
waiver follows from this old exposed authored question cohort.
