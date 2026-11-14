# Fixed-weight crossed-wording routing diagnosis

This is a causal development diagnosis on a previously exposed synthetic cohort. It does not confirm a new memory architecture or close the Phase 3 scientific gates. The old 44-root population checkpoint bytes and reports stay unchanged. There are 64 training examples but only 28 source dependency groups per seed: 16 semantic records, 8 event histories and 4 programs.

## Frozen protocol

Use all three original seeds, in order: 1907, 2719, 4051. Preserve the original parent rank-4 checkpoint, expanded single rank-8 checkpoint and two rank-4 child checkpoints. No decoder training or gradient probes are added.

For each seed, cross the 64 supported source questions and the 12 unsupported source operations with all four original training templates. Both child decoders answer all 304 questions in fresh processes. Router utility is 1 only when the raw exact output is correct **and** the child has the required source capability. No old utility or answer scores are copied into the new training observations.

The original fitted router is compared with a full-cross router fitted on all 304 rows and a counterbalanced router fitted on 76 rows. Counterbalancing chooses positive wording `index % 4` and negative wording `(index // 4 + index % 4) % 4`, giving each wording 16 positive and 3 negative rows. The balanced control is not itself fully crossed. All fitted routers keep the original 512-dimensional feature recipe, 400 optimizer updates and thresholds. No final-data tuning is permitted.

Lexical routing uses unigram and bigram TF-IDF cosine similarity to all source questions. Dense routing uses the actual trained parent checkpoint, with its adapter enabled, and averages the final hidden state over the complete question prompt. Both nearest-source controls transfer a source question's freshly measured expert-utility target, without storing answer values in their route indices. Ties choose the lowest source index, then the lowest expert slot. An unsupported source question or one that neither eligible child answers correctly has a reject target. No similarity threshold is tuned.

Freeze all question-only routes and metadata routes before any new final decoder output. The final panel has 64 retention, 32 transfer and 24 unsupported questions, all previously exposed in the original development experiment. Both children and the single model answer the entire panel. All policies are scored against the same immutable raw matrix. The metadata control uses supplied structured operations and source ancestry; it is not a learned natural-language parser. The oracle and exact expected uniform policy are evaluation-only controls on known questions. Their `all` denominator is 96, while other policies' `all` denominator is 120; compare all policies only on `known`, `retention` or `transfer`, and show oracle/uniform unknown results as not applicable. Counting dependency groups does not establish statistical independence across groups or seeds.

| Added work | Per seed | All three seeds |
|---|---:|---:|
| Source utility decoder queries | 608 | 1,824 |
| Final decoder queries | 360 | 1,080 |
| Total decoder queries | 968 | 2,904 |
| Parent feature forwards | 424 | 1,272 |
| New router optimizer updates | 800 | 2,400 |
| New decoder optimizer updates | 0 | 0 |
| New gradient probes | 0 | 0 |
| Fresh decoder worker processes | 9 | 27 |
| Fresh parent feature worker processes | 1 | 3 |

Parent feature extraction runs in a separate short-lived process, which exits before final decoder readers start. This releases loaded decoder tensors and process allocator memory. The query/feature recipe and measured work counts remain unchanged. The expected runtime was registered as roughly 15–24 minutes overall, based on historical read timings, and is an estimate. There is no positive accuracy gate. A successful executable exit establishes only completion and evidence-integrity checks. Negative outcomes are retained.

## Cost boundaries

Every actual decoder query, input/generated token, generation duration, worker process, load/validation wall time and child CPU time is charged to this added event. Parent feature forwards, feature tokens and storage, fitted router steps/time, nearest-source index bytes and route computation are recorded separately. Whole-event CPU and wall time include overhead; stage times overlap the whole-event measurement and must not be added to it again. Shared raw reads are charged once for the event, rather than duplicated for each counterfactual policy.

The old parent and candidate decoder training, source gradient probes, original router fit, source selection and final reads are retained as separate **sunk costs**. Decoder training totaled 2,560 optimizer updates per historical seed across all measured arms, not 1,536. The old 400-update router is reused; each new router receives its own 400-update fit. Old codec evaluations are outside this diagnosis's cost scope. This is not an equal-total-budget comparison of deployable systems. It does not demonstrate inference latency or memory compression advantage.

All expert outputs are generated for diagnosis. `live_dispatch_executed` is false. Source diagnostics for nearest-source controls include matching each source question to its own prototype and are labeled as training observations. The full-cross comparison changes wording balance and the number of source observations; the 76-row control reduces that data-volume confound but cannot prove wording is the sole failure mechanism. The existing fixed decoders also retain their capacity/transfer limits.

## Execution

Preparing uses only file hashing and deterministic fixture generation; it performs no model inference, feature extraction or router optimization. Preparation pins the exact repository HEAD, source file digests, checkpoint inventories, original router artifact and historical reports. All newly written evidence must remain below this directory. The base publisher bytes are verified read-only; the original helper's adjacent acquisition-receipt write is deliberately not invoked.

```bash
python -B diagnosis_trial.py prepare \
  --repo /path/to/hepta-private-ci \
  --historical /path/to/retained-population-artifacts \
  --model /path/to/pinned-smollm2-135m \
  --output ./new-run
```

The historical directory must contain `seed-1907`, `seed-2719` and `seed-4051`, each with the original `dataset.json`, `training`, `selection` and `final` artifacts. Checkpoints and the original router are resolved from that fixed relative layout under the explicitly supplied directory. Their manifests, tensor bytes, router digest and original metadata are checked; historical JSON files are never rewritten to change their old absolute paths. Preparation retains the original declared paths as provenance. The supplied repo must contain the required committed `scripts/memory_cell*` modules. Place this driver directory and its output in the desired working location; no scratch-specific input defaults are embedded in the driver.

Execution performs the registered model work. Activate the validated Torch/Transformers/PEFT runtime, use a new output directory for a new run, and retain stdout/stderr:

```bash
python -B diagnosis_trial.py execute --output ./new-run
```

Execution requires unchanged prepared pins and a new `execution-start.json`. It does not retry, overwrite old evidence, choose only positive seeds, or relax thresholds after reading results. On failure it retains the partial evidence and a failure report. A repaired implementation requires a newly prepared diagnosis directory and an explicit accounting of any previously incurred event costs.

## What remains outside this experiment

### Limits already visible in the old fixed-decoder results

These are diagnostic bounds from the unchanged historical `seed-*/final/result.json` files. They do not substitute for new raw generations. On the old retained output matrix, learned routing obtained 2/64, 0/64 and 0/64 retention answers, compared with single-model counts of 45/64, 43/64 and 40/64. Eligible oracle retention was 61/64, 47/64 and 45/64. The old oracle quality gate of at least 75% therefore already failed for two seeds.

Metadata routing matched the eligible oracle on seeds 1907 and 4051, so no router over that same output matrix could exceed metadata by the original required five percentage points on those seeds. Event interpolation oracle accuracy was 31.25%, 37.5% and 31.25%, and procedure extrapolation oracle accuracy was 18.75%, 18.75% and 0%; all are below the original per-family transfer gate of 75%. These are decoder capability limits that changing only the router cannot remove. The new diagnosis preserves the old gates and reports its new raw matrix separately.

### Further experiments and external prerequisites

Equal-total-budget advantage requires another preregistered experiment that charges gradient partitioning, source utility reads, routing features/training, storage, lifecycle work, query routing and decoder reads to each competing system under one end-to-end resource budget. Equal decoder update counts and equal LoRA bytes alone do not establish that claim. Random partitions and fixed-capacity controls should receive the same source information and evaluation opportunities.

Previously unseen independent tasks or future CI incidents are required for a new confirmation cohort. This historical synthetic fixture and three previously used CI incidents cannot provide that evidence by relabeling their questions. Real multi-host behavior likewise requires separate physical hosts and measured remote failures; local subprocess migration cannot establish independent host failure tolerance. These blockers remain even if the crossed-wording router improves.

## Executed and formatted source identities

The completed development run used the exact five source modules retained in
its evidence archive. The readable modules in this directory were formatted
only after that execution finished. Their ASTs are unchanged; the separate
`source-format-equivalence.json` receipt records each original and formatted
SHA-256. No experiment or behavior tests were rerun after this final formatting.

The old prepared protocol intentionally requires its original source bytes and
paths. It must not be silently changed to admit formatted modules. For an exact
source reconstruction, use the archived five modules and the pinned d61 repository
revision. A new `prepare` using this directory records a new source identity and
creates a separate development run; it does not overwrite or turn the historical
cohort into independent confirmation.
