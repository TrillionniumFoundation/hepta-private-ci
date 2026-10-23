# H4: current-weight TRAIN headroom collected; no dynamic superiority

**Actual execution completed, worker/overall exit 0. This is a TRAIN diagnostic, not scientific acceptance.**

All fixed 36 service calls completed once: 3 seeds × 3 repeats × 4 paths, each with all 3072 TRAIN rows, 192 physical sources and batches64. This produced 110592 output rows across 1728 batches. No fitted parameter, policy, threshold or model selection changed. The result does not support expanding the current critic: even free label-aware selection between these NC full/low outputs has a slightly lower cross-seed empirical raw-utility ceiling than selected static NDU/full. The prespecified conditional CPU-net proxy also averages negative. Timing nonadditivity prevents calling it a strict complete-CPU impossibility bound.

## Frozen execution and real costs

- Cloud working directory: `/workspace/hepta-private-ci/qualification/joint-generation`; selected environment identity is retained in START/diagnostic.
- Frozen source: `9adc3743a60ab613a0e4cb1ed105e1b5169186aa`; execution commit: `065e18814106f763317f0fedaffa6996ba865f02`.
- Freeze SHA256: `1ee47226e3af40cd9e40e1980e42990429f1ae28e18fb95efc736493e2335425`.
- Started 2026-10-23T16:35:25.325743+00:00; completed 2026-10-23T16:35:38.112698+00:00.
- Full H4 worker/descendant+launcher CPU: **12.813186359 s / 30 s**; wall **12.786974641 s**.
- Declared useful work: **2419694784 / 4000000000** units; known accounting complete, no unsettled calls. Service work2073627648 plus content probes346067136 equals the complete ledger.
- Maximum per-request work25829 <38472 cap; no service budget violations. Retained payload is below32MiB, with its exact final count in postrun-manifest.
- H2 startup failure0.519258463 s +H3 startup failure0.807168997 s remain separately retained. H2+H3+H4 actual technical execution totals **14.139613819 CPU s**, never refunded. H4 no-data entry preflight separately recorded0.769679171 CPU s.

The diagnostic R&D budget is separate from the unchanged original qualification build caps10s/12B per system. Scientific proxy comparisons retain the complete historical T11 arm build costs NC8.537556029s versus N8.307966292s, each divided across3 seeds and H100000 requests, R73435.296875ns and price.02. Critic cost is already inside NC build, never charged twice. Additional saved-result analysis/auditing is separate R&D, not useful-update or runtime credit. Its first analyzer invocation exited0, tool wall0.301893590s; that auxiliary process CPU was not directly metered. Do not call the execution totals above a total for all prior research/development.

## Actual raw content and empirical two-action ceiling

| Seed | NC/full raw | NDU/full raw | N−NC content gap | Free full/low oracle−NDU/full raw |
| --- | ---: | ---: | ---: | ---: |
| 11 | 0.992162599271 | 0.992458093770 | +0.000295494499 | +0.000975404828 |
| 23 | 0.990855004082 | 0.993014145055 | +0.002159140973 | -0.001283117629 |
| 47 | 0.992927845736 | 0.993893850864 | +0.000966005128 | -0.000332429816 |

Across seeds, selected static NDU/full exceeds direct NC/full, each using its own
saved weights, by **+0.001140213533**. The free oracle gains only about+0.000926832661
over NC/full, leaving **−0.000213380872** relative to NDU/full. Its raw signs are
**positive / negative / negative**; seed11 is not discarded. Since every physical
source has16 rows, source-equal and row-equal means coincide. All three seeds are
weighted equally. The observed content deficit is not an isolated causal estimate
of the effect of the arms' differing update counts.

The complete saved-array pairing exports are [9,216 row pairings](paired-row.csv),
[576 seed/source pairings](paired-source.csv) and [all seed aggregates](paired-seed.json).
Each source has16 rows; each row includes the physical source and original input
hash. They contain expected decoded raw utilities for NC/full, NC/low and
NDU/full, their rowwise maximum and paired differences, with17 significant
digits. They contain no cost proxy. [The exporter](export_pairings.py) reads
saved arrays only, with zero model calls/data constructions. Its successful
[publication receipt](pairing-export-execution.json) records1.156763179 CPU s
before final receipt serialization, separate R&D. The first CSV publication
attempt tripped a2e-15 aggregate rounding check at2.8866e-15; its partial CSVs and
[failure](pairing-export-failure-v1.json) remain retained. Accurate summation
fixed only that export check; no scientific computation or service was repeated.

The free oracle uses the exact maximum of two **expected decoded raw utilities** for each input, knowing otherwise unavailable labels/outcomes. On these fixed TRAIN rows and current NC weights, any mixture/selector of only those two potential distributions has raw expectation at most that ceiling. This is an empirical content-action limit; it is not a theorem for unseen inputs, retrained weights, richer actions or another task. It also does not alone bound CPU-net utility: a lower raw score might be offset by genuine cost savings.

## Prespecified conditional cost proxy, including all signs

| Seed | New service price c | Oracle margin vs own continue | Content contribution | Runtime contribution | Build contribution | Oracle proxy net−NDU/full |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 11 | 0.005334180327 | +0.005051723364 | -0.000295494499 | -0.006726840538 | -0.000208428142 | -0.002179039815 |
| 23 | 0.000000000000 | +0.000876023344 | -0.002159140973 | -0.001264790854 | -0.000208428142 | -0.002756336625 |
| 47 | 0.000000000000 | +0.000633575312 | -0.000966005128 | +0.000964788995 | -0.000208428142 | +0.000423931037 |

Mean proxy oracle−NDU/full is **−0.001503815134**; signs are **negative / negative / positive**. Seed47 remains +0.000423931037. H4 prices are new simultaneous-wave estimates; H1 old prices/results are unchanged. No new confidence interval, significance declaration, warmup/trimming or favorable-seed/wave selection was performed.

The proxy uses median paired go−stop service cost, then zero-clamps it, plus stopped preparation/H. A sum of medians need not be a measured route cost. In particular, `(Cstop+c)−measured Cgo` is +0.000262931938 /+0.000176593910 /**−0.003931687441** for seeds11/23/47. That last residual is material. Negative measured increments remain visible; they do not mean free physical computation. These constant-cost/mixture assumptions prevent interpreting proxy negativity as a strict upper bound on complete-system performance.

| Seed | Three signed go−stop CPU/request, microseconds | Actual go−same-NC/full complete paired median, microseconds |
| --- | --- | ---: |
| 11 | +31.774249 / +4.118990 / +19.585856 | +34.418931 |
| 23 | -0.647826 / +5.200246 / -0.914354 | -1.591727 |
| 47 | -3.003494 / +30.801884 / -0.056457 | +7.642010 |

All original 36 calls retain per-row work/CPU/output-byte vectors, 48 batch costs each, preparation, first actual PNG/JSON sample and sampling seed. They do not retain all110592 output payloads/RNG traces and do not assert a cross-codec equivalence result. Full means/three costs and signed sensitivity remain in headroom-analysis.json and reports/.

## Exact weights, historical build and audit files

[T11-binding.json](T11-binding.json) binds all six original model files, internal
model digests, update counts, the three controllers, archive/selection hashes
and fixed reference. NC has488 useful content updates per seed; static NDU has
513/514/514. Models were restored unchanged, never retrained in H4.

[Historical cost detail](historical-build-costs.md) and its
[complete extracted cost ledger](historical-build-costs.json) retain common,
candidate, refinement, selection, critic and work accounting, distinguishing
measured costs from scheduling forecasts. NC8.537556029000005 s and
N8.307966292000007 s are complete original T11 build costs, not new H4 spending.
Their nanosecond identities remain8537556029/8307966292. Model identities and
historical costs are not inferred from the favorable subset of any result.
N/NC consumed11958840147/11901341862 declared units under the unchanged12B cap;
the shared2.502427883 CPU s is fully included in each arm, with no additional
amortization credit. The metadata publication separately records5.419106183 s
of metered preliminary inspection and0.176559224 s through its final two writes.
Other administrative meter gaps remain explicit; those figures are not a total
of all project R&D and are not added again to historical method charges.

The [actual outer process receipt](../codex-cloud-dynamic-h4-source-preflight/actual-worker-execution.json),
[diagnostic ledger](diagnostic.json), [all36 service reports](reports/),
[array analysis](headroom-analysis.json), [independent audit](postrun-audit.json)
and [boundary review](boundary-note.md) preserve their different cost/evidence
boundaries. The worker's original53-file [manifest](manifest.json) is unchanged;
the final publication [manifest](postrun-manifest.json) additionally binds the
postrun reports and exports. Metadata export/audit/formatting costs are separate
R&D and never refunded into a method's content budget; unmetered auxiliary CPU
is explicitly identified rather than claimed to be included in12.813186359 s.

## Reproducibility, preserved failures and scope

The reconstructed TRAIN pixel arrays, labels, source IDs and row hashes are saved. All3072 hashes/source order match Q1, with192 sources×16 rows. Current NC full/low/gain arrays match saved Q1 **exactly** for all3 seeds (maximum absolute difference0). NDU/full values fill the previously missing TRAIN content term. The10 restored model/head/native byte artifacts match original hashes. Startup/exit protected114 historical evidence files; core/r2 test states remain unchanged.

H2 invalid-ledger failure and H3 float-identity failure stay consumed. H3 raw floats differ only below a nanosecond from the frozen decimal costs; source repair compares canonical nanoseconds and preserves strict real caps/configuration identities. Actual entry preflight used the real archive/initialization without model/data work. H4 did not repeat previously observed model or measurement results, because H2/H3 had produced none.

D1 remains a separate true10.022472113s cap failure with its codebook slots never launched. H4 uses only the old rowwise codec; no PNG-cache lifecycle improvement is claimed. The original r2 dynamic gate is still failed and its test unopened; core c1 remains its sealed formal failure with six intervals crossing zero. No new held-out, AV generation, production, merge or authority change occurred.

The earlier CORE audit could not independently reconstruct the complete
TRAIN/validation identity intersection because those full manifests were not
retained; it relied on the frozen evaluator's runtime disjointness check.
H4's complete TRAIN identity export does not retroactively fill that CORE audit
limitation or change its sealed result.

## Boundary judgment and next research

For this fixed finite12-code task, these T11 weights and attempted full/low decisions, there is no present evidence supporting a larger critic or another identical qualification build. The content model opportunity gap already exceeds the free raw routing ceiling on the empirical equal-seed TRAIN mean; the fixed net proxy also fails to close the gap. The actual missing measurements are now collected. The remaining dynamic blocker is substantive advantage, not missing direct-full accounting.

This does **not** establish that every dynamic model is impossible or that a held-out gain is zero. Stop tuning this same critic/timing setup. A follow-up must be an explicit new TRAIN proposal with genuinely informative legal content-state actions or multimodal information heterogeneity and a strong effective static NDU comparator. Give static methods every applicable optimization, including any variance-reduction training change from parallel research.

Finite code-pair reconciliation and its compiled static comparator belong to
the concurrent content group; this task does not duplicate that probe. Its
joint-law/greedy/scoring constraints remain in the
[candidate note](../../independent/FINITE_CODE_COMPILE_NOTE.md).
The [post-H4 dynamic proposal](../../independent/POST_H4_DYNAMIC_PROPOSAL.md)
states that finite12 presently has no supported new dynamic execution candidate.
It proposes an explicit independent public multi-object generation adaptation,
with actual text/patch content transitions, legal paid feedback, nine fixed
action sequences and compiled/distilled/renderer static competitors. This is
only a proposal: task/budget/pixel-scoring feasibility is unknown. No new
training or data executes, and no static-compilation impossibility is claimed.
A changed task cannot solve old r2. Any later formal confirmation still needs
independent data, complete history and prospective cross-confirmation error
control. No later formal test or AV extension is authorized here.
