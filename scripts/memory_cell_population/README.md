# Memory population: registered heterogeneous research

This study asks five separate questions: whether dividing a learned parent helps
at a matched adapter budget; whether question-only routing earns its cost; whether
adapter quantization preserves useful answers; whether different memory operations
work; and what the results can actually establish about a general memory system.
Every checkpoint and receipt remains a research artifact. No production install,
external frontier authority, universal memory claim, or automatic promotion is
granted by these scripts.

## Architecture and comparison

A new rank-4 parent learns sixteen semantic sources. Actual gradients from the
64 source training examples produce signed 32-dimensional sketches. A seeded
balanced clustering procedure assigns whole source dependency groups to two
children. An event history stays together; all training examples from a program
stay together. Family labels and final answers are not partition features.

Both rank-4 children start from the exact verified parent. The single-cell
comparator expands that same parent to rank 8 with identical LoRA scaling:
copy the learned A/B columns, preserve newly initialized A rows, and zero the
new B columns. The low-rank product is checked before the derived version is
saved and ordinarily reloaded. The new columns can subsequently learn.
Expansion accepts only an unchanged verified parent and an untouched target.

The candidates receive the same number of optimizer updates, visits per source
example, input tokens, and float32 adapter bytes. They do not receive the same
total system storage or wall time. Partition probes, the router, every retained
version, source records, owner databases, and every diagnostic expert read are
recorded separately. The common parent is charged once per independent seed.

The resulting topology is a bounded parent/two-child research population, not
an arbitrary self-organizing meta-network. All learned experts use the same
adapter architecture; heterogeneous operations do not by themselves demonstrate
the emergence of new architectural cell types.

## Fixed cohorts and write budget

The preregistered seeds are **1907, 2719, and 4051**. A source ledger has 44 roots:
16 semantic records, 24 events, and four affine-mod-11 programs. Programs supply
six source training examples each, yielding 64 examples in total.

| Stage | Rank | Examples | Optimizer updates |
|---|---:|---:|---:|
| New common parent | 4 | 16 | 512 |
| Gradient partition probe | 4 | 64 | 0; 64 forward/backward probes |
| Expanded single | 8 | 64 | 1,024 |
| First literal child | 4 | 32 | 512 |
| Second literal child | 4 | 32 | 512 |

All candidate examples receive sixteen visits. AdamW uses learning rate 0.001.
The parent model seed is the cohort seed plus 10,000. No command-line argument
can change the registered recipe. Actual tokenizer admission retains per-source,
per-template full and supervised token counts for independent schedule auditing.

Final evaluation contains 64 retained keys with different wording, sixteen event
queries between recorded times, sixteen unseen program inputs, and 24 unsupported
requests. Parent semantic answers are also read with final wording to check that
every previously correct memory remains correct. Final question text is used for
tokenization admission; final answers and performance never select or fit a model.

## Question-only learned router and strong controls

The router is a small learned softmax classifier over hashed question features.
Its training targets come from the children's actual supported source answers.
Positive expert ties receive soft targets. Unknown training requests teach the
reject class. All router fitting finishes before source-only topology selection,
which in turn finishes before final model reads.

Every final route is persisted before fresh reader processes start. The worker
gets only the question, scope, checkpoint identity, allowed roots, rank, seed and
the registered control. It receives no source table, answer lexicon or probe gold.
Actual owner admission checks the version before and after each worker.

The experiment compares learned routing, expected uniform random routing, the
eligible oracle, and a deterministic metadata-capability route. The latter uses
the supplied structured operation and source-key/time metadata, without answers.
It is a strong baseline and is not a learned natural-language parser. Raw learned
OOD rejection is reported separately from metadata-assisted abstention.

All expert outputs are actually computed for this diagnostic comparison. A
post-scored guard does not establish a live zero-callback dispatch saving.
Oracle answers are evaluation-only and cannot select the production route.

## Gates fixed before outputs

| Claim | Required evidence |
|---|---|
| Fission advantage | Mean retention gain at least 5 percentage points over the matched single; no negative seed; parent source and final semantic recall at least 75%; preserve every parent-correct semantic answer |
| Bounded learned routing | At least 75% supported coverage and eligible-oracle recall; at most 5 points regret; at least 5 points over expected uniform random; at least 90% raw OOD rejection, in every seed |
| Advantage over metadata | The routing requirements above plus at least 5 points over the deterministic capability route in every seed |
| Heterogeneous retention | At least 75% separately for semantic, event and procedure keys in every seed |
| Heterogeneous transfer | At least 75% separately for event interpolation and program extrapolation in every seed |
| Primary int8 codec | Complete packed checkpoint no more than 35% of original; retention and transfer loss each no more than 2 points, in every seed |
| Net compression | Complete accounted data/model storage beats the smallest exact full-source representation at equal supported quality |
| General memory | Not certified by this finite suite |

Source selection additionally requires parent semantic recall of 75%, exact
preservation of parent-correct items, at least one new answer for single promotion,
and four additional answers over the best eligible cheaper arm for split promotion.
Serialized router overhead must be at most 1% of the matched adapter budget.
Ties retain the cheaper eligible choice. An unsuccessful parent gate stays visible.

The int8 primary and int4 secondary codecs always evaluate the full-source single
candidate, independently of which topology wins. Both use the same final probes.
The experiment never chooses a bit width from final quality. Decoding materializes
ordinary float32 tensors and receives a new lineage identity. Storage reduction
therefore does not establish reduced inference RAM or integer execution.

## Exact storage and cost accounting

Complete source records are actually round-tripped through JSON, zlib9, LZMA6,
and SQLite. Structured exact operations run from those sources rather than probe
answers. The ledger is synthetic and deterministic: the public seed and retained
generator are an additional exact baseline. The generator must reproduce the
actual measured source-ledger hash, not merely a supplied stale claim.

Report adapter-only packed ratios separately from selected serving artifacts,
the shared base model, and all retained research versions. Runtime libraries and
code are excluded from the stated data/model lower bound; omission cannot create
a claimed net compression advantage. A positive net claim additionally requires
complete equivalent system costs, which this data/model lower-bound study does
not supply. The generic execution environment is also
excluded from data-only exact baselines. A hypothetical uniform assignment's
entropy is not an irreducible lower bound for this seed-generated dataset.

## Reproduce and audit

Use the pinned CPU dependencies in `../memory_cell/requirements.txt`, install
CPU torch 2.5.1, and acquire the publisher-pinned decoder with
`../memory_cell/prepare_parametric.py`. Set `PYTHONPATH` to `memory_cell`,
`memory_cell_growth`, `memory_cell_router`, `memory_cell_codec`, and this folder.

```bash
bash scripts/memory_cell_population/run_tests.sh
python -B scripts/memory_cell_population/population_trial.py \
  --model /absolute/path/to/smol135m --seed 1907 \
  --output /absolute/path/to/new-evidence/seed-1907
```

Run the same command for seeds 2719 and 4051 with exclusive output directories.
Source identity and protocol are persisted before training and checked afterwards.
The output retains raw writes, exact schedules, gradient sketches, source-only
router utilities, frozen choices, worker input/output journals, codec derivatives,
and positive or negative gates. The independent auditor recomputes raw evidence
instead of accepting the aggregate's booleans. All three registered seeds must
appear in the aggregate; failures cannot be dropped or replaced after inspection.

The shadow workflow exercises offline mechanism and integration tests. Full
pretrained experiments are separately costed and reported; unit-test success is
not a pretrained capability result. Historical evidence is never overwritten.
The mechanism job uses `ubuntu-slim` and its documented fifteen-minute limit;
it requires no privileged container operation or downloaded pretrained model.

## Research context

- [A Theory on Mixture-of-Experts in Continual Learning](https://arxiv.org/abs/2406.16437)
  studies a restricted overparameterized linear setting; it does not prove that
  more SmolLM2 memory experts improve this task.
- [Orthogonal Subspace Learning for Language Model Continual Learning](https://arxiv.org/abs/2310.14152)
  motivates controlling interference between low-rank updates. Its experiments
  do not establish arbitrary fission, deletion, or general-memory guarantees.
- [Language Modeling Is Compression](https://arxiv.org/abs/2309.10668) concerns
  predictive models as actual codecs. Storing facts in weights alone is not the
  same as a complete reversible compression format with all side information.
- [Knowledge Capacity Scaling Laws](https://arxiv.org/abs/2404.05405) uses controlled
  factual-knowledge experiments. Its capacity measurements are not a universal
  storage bound for this adapter, training budget, or heterogeneous workload.
