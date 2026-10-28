# Formal typed-memory findings

Full-rank parameter recall passes the declared held-read gate. Compression advantage fails; ordinary OLS matches the learned affine family at the declared tolerance. Rank-2 text recall fails completely. No general-memory or algorithm-discovery claim follows.

## Evidence and denominators

Source commit: `6206dfba0a3219534dd1a0274431bf48fd23673c`. Formal seal: `ec975d0e9afc53903ba2d26129446e263d06ebea0abb8b9e729e556546eca3ff`.

Independent transfer audit: **7,023 checks, zero failures**; see `../validation/formal-transfer-audit.json` and the complete companion `formal-typed-findings.json`.

One held UCI retail sample contains **640 events / 3,200 written target fields**. The five seeds vary affine programs, demonstrations, and queried addresses. Event models are byte-identical across seeds within each rank arm.

Each arm and read mode has **64 queries per field per seed**, or **1,600 queries** across five seeds, covering **1,317 unique event-field coordinates**. Repeated process reads and overlapping addresses are not independent domains. There are **640 novel procedural input queries**, including **480 interpolation / 160 extrapolation** inputs; the latter grouping refers to the first program's input range.

## Event recall and low-rank distortion

| Field | Full-rank parameter correct / queries | Rank-2 parameter correct / queries | Rank-2 non-null wrong | Rank-2 abstained |
| --- | ---: | ---: | ---: | ---: |
| quantity | 320/320 | 320/320 | 0 | 0 |
| unit_price_pence | 320/320 | 320/320 | 0 | 0 |
| stock_code | 320/320 | 0/320 | 316 | 4 |
| country | 320/320 | 0/320 | 285 | 35 |
| invoice_no | 320/320 | 0/320 | 320 | 0 |

Overall parameter recall is **1,600/1,600** at full rank and **640/1,600 (40%)** at rank 2. Numeric MAE and MSE are zero in both arms. Rank-2 text recall is **0/960**, including **921 non-null wrong strings** and **39 abstentions**. A format-valid string is not evidence of a correct memory.

Explicit-residual reads are **1,600/1,600** for each arm. Independent codec roundtrips also reproduce all 640 selected records. These are explicit exact codecs, not parameter-only reads.

## Procedural family and controls

Each seed fits three affine programs from 24 demonstrations each. The family and chain are supplied; coefficients are learned. The main procedural query denominator is 128 per seed, not four times that number when reused in fresh readers.

| Seed | Learned affine within 1e-7 | Ordinary OLS within 1e-7 | Affine maximum error | Nearest-demo MSE | Quadratic negative MSE |
| --- | ---: | ---: | ---: | ---: | ---: |
| 401 | 128/128 | 128/128 | 5.82077e-11 | 3.07022e+08 | 1.39981e+11 |
| 409 | 128/128 | 128/128 | 4.36557e-11 | 4.33466e+08 | 1.42681e+11 |
| 419 | 128/128 | 128/128 | 4.36557e-11 | 1.69315e+08 | 1.86038e+11 |
| 421 | 128/128 | 128/128 | 8.73115e-11 | 7.05114e+08 | 1.91964e+11 |
| 431 | 128/128 | 128/128 | 5.82077e-11 | 4.61401e+08 | 1.79919e+11 |

Both learned affine and ordinary OLS pass **640/640** queries at the fixed tolerance. Literal float64 equality is only **127/640** and **36/640**, respectively. Nearest-demo and affine-on-quadratic controls each pass **0/640**. The latter exposes the supplied family's limitation; it does not show algorithm discovery.

Event-to-procedure composition passes **640/640** requests per arm/mode within 0.005, with correct provenance. That chain reads only quantity and unit price, so its success does not repair rank-2 text failure.

## Storage: every model, address, schema, program and replay is charged

The strongest traditional event control is `columns_lzma`, **8,677 B**. The table below compares the same selected event fields and addresses; ratios in this table are event-only.

| Arm | Parameter event bytes | Model + residual event bytes | Exact / strongest traditional |
| --- | ---: | ---: | ---: |
| full_rank | 84,195 | 86,133 | 9.926588× |
| rank_2 | 47,541 | 53,010 | 6.109254× |

Complete event + procedure serving and replay costs differ from the event-only ratio:

| Seed | Full parameter serving | Full exact serving | Full exact + demo replay | Rank-2 exact serving | Rank-2 exact + demo replay | Traditional exact + OLS | Traditional + same demo replay |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 401 | 85,915 | 87,853 | 89,639 | 54,730 | 56,516 | 9,882 | 11,668 |
| 409 | 85,915 | 87,853 | 89,639 | 54,730 | 56,516 | 9,882 | 11,668 |
| 419 | 85,915 | 87,853 | 89,639 | 54,730 | 56,516 | 9,880 | 11,666 |
| 421 | 85,915 | 87,853 | 89,640 | 54,730 | 56,517 | 9,881 | 11,668 |
| 431 | 85,915 | 87,853 | 89,643 | 54,730 | 56,520 | 9,881 | 11,671 |

Required inference Python source is separately reported as **62,932 B**, versus **63,017 B** for the traditional decoder dependency set. The retained official archive is **23,715,478 B** and the selected canonical source is **128,918 B**. Python/NumPy runtime is shared infrastructure; it is excluded from incremental serialized-state ratios and included in observed process cost. Transfer research artifacts including their summary total **4,686,547 B**. No storage advantage is demonstrated under the strong baseline.

## Work and interpretation

Each seed pays for **10 SVD calls** (work proxy **609,280**) and **seven least-squares solves** (proxy **1,008**): three learned affine programs, three ordinary OLS controls, and one nonlinear negative. Across five seeds this is **50 SVD / 35 least-squares solves**, proxies **3,046,400 / 5,040**, plus **20 actual fresh reader processes**. All predeclared arms and negative controls are included; deterministic repeated fits are still charged.

The sealed transfer-stage wall time is **4.798376 s**. The largest observed reader process peak RSS, including shared runtime, is **159,506,432 B**. These are historical receipts, not independently retimed benchmarks; nested timings are not additive.

The 95% full-rank hidden-read gate passes 5/5 seeds; the rank-2 diagnostic passes 0/5. Fresh readers receive no source/target payload. This qualifies explicit-address writes and reads for this retail type and coefficients in a predeclared affine family. It does not establish a new unseen type at formal time, natural-language routing, learned graph topology, superiority over OLS, physical unlearning, or a universal memory system. Maintenance version propagation is reported separately.
