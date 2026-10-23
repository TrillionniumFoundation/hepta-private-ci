# H4 independent boundary check: this TRAIN batch and two fixed actions

Read-only saved-artifact arithmetic, 2026-10-23T16:39:49.547155+00:00.
No dataset construction, model/native execution, fitting, new service timing or
bootstrap occurred. Full cost/acceptance auditing is separate.

`groups == source_ids`; all 3072 rows cover 192 physical sources with exactly
16 rows each. Equal physical-source weighting therefore equals row weighting
within each seed; the reported overall values give each of three seeds weight
1/3. No source, seed, input or unfavorable observation was removed. Recomputed
`NC_full - NC_low` equals saved g exactly; source-equal free-oracle/content-gap
and headroom values match the saved report within 1e-12.

| Seed | Free raw oracle minus selected NDU/full | Content gap N−NC/full | Priced proxy headroom vs own continue | Proxy-net oracle minus NDU/full |
| --- | ---: | ---: | ---: | ---: |
| 11 | +0.000975404828 | +0.000295494499 | +0.005051723364 | -0.002179039815 |
| 23 | -0.001283117629 | +0.002159140973 | +0.000876023344 | -0.002756336625 |
| 47 | -0.000332429816 | +0.000966005128 | +0.000633575312 | +0.000423931037 |

Across seeds, `mean(max(NC_full, NC_low) - N_full)` is
**-0.000213380872**;
`mean(N_full - NC_full)` is **+0.001140213533**.
The free-label raw oracle has no timing assumption: it is an empirical ceiling
for selectors restricted to these two fixed per-input NC sampling laws on this
TRAIN batch. It is not an upper bound for other weights, feedback actions,
outcome-conditioned content edits, unseen sources or a complete-lifecycle net
objective. Seed 11's raw difference is positive; seeds 23/47 are negative.

Mean conditional proxy-net oracle minus NDU/full is
**-0.001503815134**. Seed 47 is positive
(+0.000423931037), so there is no all-seed negative claim. Its median-additivity
residual, saved as `go_proxy_vs_measured_go_cost_difference`, is
**-0.003931687441** utility units: stopped-median plus clamped paired-median
increment does not equal measured always-go cost. Preserve the original three
signed increments and preparation/H terms; the proxy is not a strict CPU-net
upper bound or evidence of a deployed policy win. Raw and priced headroom must
not be interchanged.

There is no positive empirical complete-budget basis here for enlarging the
critic on these current weights and two actions. This is a bounded development
finding, not a proof that every dynamic family is impossible, nor held-out
confirmation. Cheaper routing, different content parameters, different legal
content actions and uncertainty about costs require their own evidence; no old
failure, test state or baseline is changed by this check.

A possible next proposal follows
[the finite-code compile note](../../independent/FINITE_CODE_COMPILE_NOTE.md):
predeclare a small legal pair-feedback kernel and compare it fairly with its
compiled terminal joint decoder, the independent decoder and an effective
static NDU alternative. Score the actual pushed joint law, not multiplied
terminal marginals; keep the raw/risk utility and decoder semantics fixed.
Charge context/kernel construction, feedback/critic training and selection,
storage, sampling and real outputs, giving every comparator applicable reuse.
First test finite-law/content equivalence and whether conditional action value
exists; do not assume sequential computation adds value beyond joint coupling.
This paragraph is planning only and authorizes no new probe, fit or formal test.

Input SHA256 values (unchanged after this check):

- `content-values.npz`: `b62c2e67f6b90492d4d1e36fd42e4167c81a7544799b010e8430664d1e46a1ee`.
- `headroom-analysis.json`: `458c454766ab142847b08cfec00f20c92fa4f84b88964e3bfbec58c1179a3e2f`.
- `train-metadata.json`: `4f3f2f73b83d5bd7baab43b53e5bde42cc2f1aa243ae2bb75476f9a796ba3800`.
