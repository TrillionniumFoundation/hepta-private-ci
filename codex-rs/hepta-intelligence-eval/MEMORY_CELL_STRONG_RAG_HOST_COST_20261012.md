# MemoryCell — Qwen frozen-reader CPU-host cost attribution (2026-10-12)

**Disposition: NO-GO for treating prompt-token reduction as a demonstrated
wall-time or lifecycle-cost win.** This is a read-only audit of three **completed,
previously pinned** Qwen2.5-3B sharded model runs, not new inference, new tasks,
a training improvement, or production benchmarking. The fourth completed
sharded/nonsharded cross-run replication is covered by the separate
[four-run research receipt](MEMORY_CELL_STRONG_RAG_FOUR_RUN_REPLICATION_20261012.md);
this host audit requires *per-answer and per-host shard receipts* and therefore
uses three full sharded archives (A/B/D), **336 model responses**.

## Original sources and pinning

| Run | Actions | Generating commit | Original result ZIP SHA-256 |
| --- | --- | --- | --- |
| A | [38148514657](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38148514657) | `8250698244417eb14994518af05fa6f79e783066` | `7c991f0996fc24c650efb28f6266da51ed1655b78585e11b78dbc424707b7b7f` |
| B | [38146546731](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38146546731) | `eba9af092cca1c2875552ffaea2219678143a73c` | `b4cf1346ce4c5b1625cdc57845bcca33fcf82f84340433b602d76258c10c1138` |
| D | [38161049090](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38161049090) | `e0e413d670be8982b9986a119696c6ca164ca518` | `d59560882e217d8772e4044ec33b8cdb10f5297f19b0a6e03e53266407c839a0` |

The Python auditor checks each complete outer ZIP SHA, ZIP entries and internal
`SHA256SUMS`; 267 + 267 + 300 entries are covered. It verifies original unscored
versus scored model answer bytes, all 40 calibration and 72 evaluation entries
*per run*, exactly 32 shard CPU receipts per run, each shard SHA-pinned input,
original commit, frozen source plan
`9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897`
and Qwen inventory
`f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225`.
All **112 distinct question/arm prompts** have identical saved complete input
token-ID digests across the three original runs. The three runs are repeated
observations on the **same eight public, program-authored cases**, not 24
independent cases.

## Observed CPU instruction-set split

| Host's reported instruction feature | Actual Qwen model calls | Median reader seconds per call | Median seconds per generated token | Calls exceeding 180 s |
| --- | ---: | ---: | ---: | ---: |
| Reports `avx512_bf16`, `amx_bf16` or `bf16` | 95 | **13.47** | **1.06** | 0 |
| Reports none of those flags | 241 | **977.01** | **100.93** | 200 |

For **77 matched question/arm prompt positions** where both host classes were
observed, the median of the per-position ratio of non-BF16-feature to
BF16-featured **seconds per generated token** is **97.58×**. This is an
*observational association*, not a randomized hardware effect estimate:
CPU generation, frequency, instruction masks, thermal/load conditions,
virtualization and runtime settings may vary. The audit records host CPU
model strings, requires the declared two Torch intra-op threads, and never
silently normalizes or repairs raw answers. CPU advertising a feature does
not prove a particular kernel used it.

The earlier monolithic [run 38163763497](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38163763497)
reported **922.323 seconds for one Qwen call** against a 180-second
per-call gate on a BF16-feature-lacking AMD EPYC 7763 host. It retained the
single original answer and failed calibration, correctly withholding any
complete model-effect claim. That failure is consistent with, but is not a
randomized confirmation of, the host instruction-set association above.

## Token compression is not a measured latency win

`entity_time` (full-path) and `organized` (correction-aware) **each answer
8/8** of the same authored evaluation questions in every run; this audit does
not create any extra independent source-family task gain. Across eight reads,
`entity_time` uses **5,752** complete input tokens and `organized` uses
**5,179**, a saving of **573 tokens or 9.96%**. But the observed *sum of
original recorded reader seconds* is:

| Run | Full-path reader seconds | Organized reader seconds | Organized minus full-path | Native-BF16 advertised host calls, full-path → organized |
| --- | ---: | ---: | ---: | ---: |
| A | 7,753.78 | 7,274.01 | −479.77 s | 2/8 → 2/8 |
| B | 6,440.35 | 3,555.66 | −2,884.69 s | 0/8 → 2/8 |
| D | 5,603.83 | 6,780.40 | **+1,176.57 s** | 2/8 → 1/8 |

Each arm's eight calls were dispatched across heterogeneous hosted runners,
so the arm-level time difference is **confounded** by CPU allocation. Summed
reader seconds are not the elapsed wall time of the parallel matrix and are
not calibrated server-billing totals. The B and D host mismatches illustrate
why **fewer prompt tokens alone cannot qualify an operational speed claim**.
Nor can this protocol certify deployed indexing, source retention, revocation,
recovery, training, or lifecycle cost.

## Reproduction and gates

`strong_rag_host_cost_audit.py` accepts three exact original ZIP archives
named `A-full.zip`, `B-full.zip`, `D-full.zip` in a directory, recomputes the
report without a model, and rejects tampered originals, changed source,
duplicate JSON fields, unsafe ZIP entries, altered raw answers, missing shards,
changed Torch threads or missing host CPU metadata. The self-contained
`test_strong_rag_host_cost_audit.py` includes eight tests, one of which
replays all **336 real answers** when `HEPTA_MEMORY_BF16_COST_ARCHIVES` points
to the three verified ZIP files. The read-only GitHub Actions workflow
`hepta-memory-strong-rag-host-cost.yml` fetches the pinned existing artifacts,
re-runs the tests and auditor and byte-compares the generated JSON against
the committed receipt. It does not download model weights or create answers.

**Scientific admission:** four earlier completed frozen-reader runs establish
that complete path selection beats single-hop 4/8 on the authored development
set, while organizing versus complete path adds **0 task successes and
0 complete program-declared citation chains**, despite 573 saved input tokens.
More repeats of these same exposed cases cannot establish independent
parametric-memory superiority. Source-family-disjoint prospective evaluation,
human citation entailment, actual deployed lifecycle accounting and signed
production acceptance remain **not satisfied**. Do not turn an instruction-set
performance correlation into a model-learning claim or a production promotion.
