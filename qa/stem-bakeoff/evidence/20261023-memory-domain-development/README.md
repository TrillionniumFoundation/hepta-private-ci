# Three-incident real CI memory development run

The fixed 416-update run completed with `source_integrity_verified=true`.
All four neural candidates recalled the three known repair IDs. Gradient split
and random split also rejected all three registered synthetic checksum requests,
but **exact source retrieval matched that 6/6 result with much less stored data**.
The predeclared source-only selection rule therefore selected `exact_source`.
This run establishes no neural advantage over the strongest retrieval control,
no capacity advantage, no net compression, and no future-task generalization.

The task is short-ID recall (`bind`, `order`, `assert`) from three already stored
failure symptoms. It does not learn or execute complete debugging procedures.
The separate natural Python/Git procedural replay is a different experiment and
is archived separately. No existing artificial procedure benchmark result is
replaced by this run.

## Fixed source, dataset and protocol

Local source revision: `a26aeb74cf63c7489deb5ece7e2b9a86e5697748`.
The original producer and trial are already versioned under
`scripts/memory_cell_domain/`. `source_snapshot/scripts/` retains every exact
Python source member named by this run's protocol, plus its original README.
Packaging does not substitute current modified repository files for these pins.

Dataset SHA-256:

`1642fc42e890f25e32fc5b66289cf07ee3bcf6a81fb4636fd2c2c9333ee74875`

Protocol SHA-256:

`4c011c5cf450a7bf949135a4a2713059b5e41507d54d1e9444b2686b9cf16198`

Result SHA-256:

`9890eaf1fd5e9bc00b977a2056ec70dadb9557d7794fdfe7faab98b40c48eb74`

The dataset is exactly the original producer output, including its input
manifest and ten content-addressed original run/commit/log source records.
There are three root-cause groups, zero validation cases and zero future cases.
All three natural incidents were previously seen before registration. Wording
variants, repeated source visits and synthetic negatives do not create new
independent incidents.

## Chronology of the actual three inputs

All dates below are 2026-10-23 UTC. Direct-parent fix and same-workflow later
success are verified, but only one pair has a fix timestamp after completion of
the hosted failure. Source hashes and original metadata/logs are retained in
`domain-chronology.json` and `inputs/ci-incidents/`.

| Input / repair ID | Failed test exit / failed-run completion | Fix commit time | Successful-run completion | Historical interpretation |
| --- | --- | --- | --- | --- |
| Bound fixture evidence / `bind` | 09:41:09.841 / 09:41:12 | 09:40:56 (`e9ecf9c50877b58879e1b3d61a766cf512466d5f`) | 09:41:38 | Paired historical replay only; fix predates hosted failure |
| Covariance diagnostic order / `order` | 10:42:39.538 / 10:42:41 | 10:44:42 (`455e16648ce7069400f5a8e679e4fd0c1a1da613`) | 10:45:24 | Strict historical failure-completion → fix → success order |
| Exception-message order / `assert` | 10:50:20.755 / 10:50:23 | 10:49:36 (`8ab132fce55be881a1410639d4db96e4eee8b1b1`) | 10:50:31 | Paired historical replay only; fix predates hosted failure |

This chronology audit was first reported before the domain result was read. It
does not alter the trial's source data, partitions, labels, budget or protocol.
The producer checks failure-before-success ordering, not fix-after-failure
completion. Its finite-development status remains appropriate. Timestamp order
also does not prove what a developer had observed or why a change was made.

## Comparison and observed outcomes

The fixed seed is 19031 and visits per source are 32. The rank-4 parent trained
on the first chronological case for 32 updates. Each candidate then used 96
updates and exactly 7,640 input tokens: rank-4 single continuation, rank-8
function-preserving expansion, two rank-4 gradient-split children, and two
rank-4 random-split children. Total candidate source visits and supervised tokens
match. Expanded and both two-child controls have 1,843,200 adapter parameter
bytes; the single rank-4 control has 921,600. Total system costs are not equal.

Three measured parent gradient forward/backward probes determine the gradient
partition. Both splits preserve whole root-cause groups and have sizes [2,1].
Their assignments differ, but their final outcomes are identical. Child ancestry
retains inherited parent roots; splitting does not erase or privatize ancestry.

Each router runs 400 updates on 24 source observations. Its utilities come from
that child's actual raw decoder output and source ancestry, not copied wording
labels. All four source wordings are crossed with all three incidents, for both
the positive repair query and the synthetic unknown checksum query. Final routes
are recorded before final reads. A rejected route makes no decoder call;
full-expert diagnostics are separate, charged reads.

| Arm | Known repair-ID recall | Synthetic checksum requests | Total on these six requests |
| --- | ---: | ---: | ---: |
| Parent control | 1/3 | 0/3 | 1/6 |
| Single rank 4 | 3/3 | 0/3 | 3/6 |
| Expanded rank 8 | 3/3 | 0/3 | 3/6 |
| Gradient split + router | 3/3 | 3/3 | 6/6 |
| Random split + router | 3/3 | 3/3 | 6/6 |
| Exact source retrieval — selected | 3/3 | 3/3 | 6/6 |
| BM25 | 3/3 | 0/3 | 3/6 |
| TF-IDF | 3/3 | 0/3 | 3/6 |
| Frozen feature nearest neighbor | 3/3 | 0/3 | 3/6 |
| Frozen feature label centroid | 3/3 | 0/3 | 3/6 |

Known recall uses another wording of the same stored symptom. The three unknown
requests ask for an explicitly unrecorded checksum of those same incidents.
They are synthetic negatives, not a real OOD or future-task cohort. Exact lookup
recognizes the registered operation; its rejection is not general natural
language understanding. Neural known-recall source-admitted correctness matches
the raw 3/3 scores. Future and validation denominators are zero, with null scores.

On the three known queries, both two-expert panels have an admitted oracle score
of 1.0 and expected uniform selection of 0.5. These are diagnostic summaries of
the already computed panel, not independent executions of new policies. The
source-only selection was persisted with `final_outputs_seen=false`; exact
lookup, gradient split and random split tied on 6/6 source selection, and exact
lookup won the declared storage tie-break.

## Complete retained evidence and measured costs

`trial/` retains every original trial file: protocol, source observations, actual
executed-read journal, frozen routes, final raw predictions and full-expert
diagnostics, selection, result, gradient sketches, training receipts, exact
storage baselines, retrieval indexes, feature arrays, both routers, and all eight
saved adapter/config/lineage sets (including the expansion intermediate).
`trial.log` is the original execution log. Absolute historical paths in receipts
are retained as provenance and are not rewritten during packaging.

There were 416 decoder optimizer updates, 800 linear-router updates, three
gradient forward/backward probes, 15 frozen-feature forwards, and 186 actual
decoder reads: 138 source, 24 dispatched and 24 full-expert diagnostic reads.
The decoder reads consumed 14,714 prompt tokens and generated 373 tokens.
Training consumed 33,016 input tokens and 832 supervised tokens. Decoder
training forwards total 416. Packaging performed no additional decoder reads,
fitting or training. A separate post-run audit reexecuted 12 saved linear-router
predictions; those are additional audit work, outside the original trial costs.

Measured trial wall time was 385.292 seconds, CPU time 695.863 seconds, and
process peak RSS 1,825,447,936 bytes. Its measurement scope starts after dataset
validation; import/cold-start time and energy were not measured. All executed
diagnostic reads are charged. Stored model snapshots are complete, while runtime
and OS storage are excluded from the reported deployment-byte comparison.

| Candidate | Reported deployment artifact bytes |
| --- | ---: |
| Exact source | 349,694 |
| TF-IDF | 353,448 |
| BM25 | 374,270 |
| Frozen nearest / centroid | 272,493,614 each |
| Single rank 4 | 273,455,308 |
| Gradient split | 274,427,183 |
| Random split | 274,427,219 |
| Expanded rank 8 | 276,262,338 |

These totals retain source evidence and required artifacts; neural/frozen-feature
arms count the shared base once. They are not equal-compute comparisons. The
shared pretrained base alone is 271,170,520 disk bytes. The three complete
structured source records are 3,393 JSON bytes, 1,490 zlib bytes, 1,564 LZMA bytes
or 8,192 SQLite bytes; their referenced original source bodies are retained
separately. None of these measurements establishes a net memory compression
advantage for the learned candidates.

## Model and reproduction boundary

Base: `HuggingFaceTB/SmolLM2-135M-Instruct`, exact revision
`12fd25f77366fa6b3b4b768ec3050bf629380bac`. `base-acquisition.json` retains all six
publisher file hashes and sizes; base identity is
`46b83e37620f8bb1ae57754856718886c6aa1b12d267b5b0993e779f9596f96f`.
The 271 MB shared base and installed Python packages are external requirements,
not duplicated inside this archive. All task-trained adapter bytes are included.

The recorded environment is Python 3.12.14, torch 2.5.1+cpu, transformers 4.57.1,
peft 0.17.1, numpy 1.26.4, safetensors 0.6.2, tokenizers 0.22.2, accelerate 1.10.1
and huggingface-hub 0.35.3. The original source requires an actual Git checkout
to record source HEAD. Use the pinned repository revision and compare its files
against the archived source snapshot. An extracted snapshot alone does not
provide that Git history. From the pinned checkout, with matching dependencies,
the original README's PYTHONPATH setup and the publisher-verified base:

```bash
python -B scripts/memory_cell_domain/domain_trial.py \
  --dataset /absolute/extracted/producer/dataset.json \
  --dataset-sha256 1642fc42e890f25e32fc5b66289cf07ee3bcf6a81fb4636fd2c2c9333ee74875 \
  --model /absolute/path/publisher-verified-smol135m \
  --output /absolute/path/new-domain-run \
  --seed 19031 --visits 32
```

This is a new run, not an archive verification command; it performs real training
and needs its own resource allowance. Packaging performed no such rerun.
`archive-audit.json` independently recomputes the retained answer scores,
source-only router utilities, action/abstention-to-raw-read mappings, exposure and
read counts, selector tie-break, checkpoint file hashes and source pins using
only the standard library. It is a post-run consistency audit, not an independent
execution signer or new scientific confirmation. Every file's full SHA-256 is
in `evidence-manifest.json`; the compressed archive hash is in the outer index.

The source selector's recorded score counts and storage tie-break are checked.
Individual source-selection router slots were not separately persisted in the
original run. `router-source-audit/` closes this reconstruction gap with a
separate short NumPy-only process using the exact saved routers, original a26
router modules, six reconstructed source-selection questions per router and
the already retained decoder rows. It made 12 additional router predictions,
zero decoder reads and zero optimizer updates. A runtime import blocker rejected
any Torch, transformers or PEFT import, and none was loaded.

The reconstructed source slots are gradient split `[1,0,0,null,null,null]` and
random split `[0,1,0,null,null,null]`. Both reproduce the original 6/6 source
scores; the selector still chooses `exact_source`. The separate audit measured
0.652 seconds in-function wall time, 0.630 seconds CPU and 42,995,712 bytes
cumulative process peak RSS. Its exact receipt, raw output log, command, source
hashes and full route probabilities are retained. These costs are not added to
the original 186 decoder reads or the original trial's wall time.

The byte audit reconciles that derivation without executing router parameters.
Final frozen slots were persisted in the original run and are reconciled with
every actual dispatched read and abstention. This reconstruction improves the
evidence trail; it is not a new quality or generalization experiment.

After extraction, use the archived packaging module to verify the archive
without importing Torch, loading a model or running the experiment:

```bash
python3 -B package_domain_evidence.py \
  --verify /absolute/path/hepta-memory-domain-development-20261023.tar.xz
```

To reproduce just the separate 12 router predictions, use the archived
`derive_domain_source_routes.py` with NumPy 1.26.4 and a new output path:

```bash
python3 -B derive_domain_source_routes.py \
  --archive /absolute/path/hepta-memory-domain-development-20261023.tar.xz \
  --output /absolute/path/new-router-derivation
```

The retained derivation's command names the intermediate package it read.
Every consumed member is also present byte-for-byte in this final package and
bound by `input_files` in its receipt; the intermediate compressed container is
not an additional reproduction dependency.
