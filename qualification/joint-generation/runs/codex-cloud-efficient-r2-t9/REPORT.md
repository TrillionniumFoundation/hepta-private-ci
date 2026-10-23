# Local-reuse r2 build: complete build, failed effective-control readiness

Actual exit **2**. Source `8050c19bcbd7bf98aa82ecd24f481c3ddf663b68`,
freeze/execution `02f055ff0440211279228bd72d0b9076f3550f0c`.
All actual CPU and declared-work caps held. The formal r2 fold remains
unconstructed/unopened; r1 is sealed. The complete command is in execution.json.

Validation mean contrasts, not held-out estimates or confidence intervals:

| Comparison | Task utility | Joint success |
|---|---:|---:|
| additive minus same-weight anchor | +0.023051956962 | +0.023953187912 |
| NDU minus additive | +0.004811200382 | +0.004940101847 |
| control minus cheaper same-weight random single view | +0.001311078897 | +0.001376659613 |

Control minus the selected efficient static NDU reference was
**-0.002094252134 complete CPU-net utility**. This gate failed; core positive
validation contrasts and the stronger dynamic claim retain separate states.
Maximum greedy drop was 0.002604166667; decoder corruption reduced every score.

| System | Complete CPU seconds | Declared units | Selected updates, seeds 11/23/47 |
|---|---:|---:|---|
| supervised | 5.652317297 | 11960455809 | 396 / 396 / 396 |
| anchor | 5.337372386 | 11960455809 | 396 / 396 / 396 |
| additive | 5.911573597 | 11960164047 | 387 / 387 / 387 |
| ndu | 5.857846482 | 11963868465 | 386 / 386 / 386 |
| ndu_control | 6.158979821 | 11912037540 | 367 / 367 / 367 |

No system admitted a residual round. This execution was constrained by the
declared-work allocations rather than the ten-second CPU ceiling. The local
allocation/observer improvements did not close the effective-control gate.
The original failure remains intact; there is no identical-source retry.

Actual same-process metadata records NumPy 2.3.5, OpenBLAS 0.3.30 pthreads,
SkylakeX, one configured BLAS thread, one observed task, CPU affinity 0–4,
no trace/profile hook and the same BLAS library SHA as the fixed paired probe.
Metadata discovery consumed 37.795484ms inside charged shared CPU. Earlier t8
slowness was not reproduced or causally resolved by this execution.

Root source tests: 49 passed (0.276s). Independent source tests: final 157
passed (4.594s). The initial independent check's one metadata persistence error
and its corrected affected/full logs are retained separately, not deleted.
No formal evaluation, AV generation, long-interaction or production work ran.

The next candidate targets the now-observed adaptation operator bottleneck:
reuse the existing exact 2x2 low-view structure in continued-training forward
and encoder pullback. It must preserve shared dense base training and its exact
bytes, the input/RNG stream and all objectives; explicitly test floating-point
reordering and actual variable-step work before any new source freeze. It is
not implemented or credited as a saving in this run.

The retained-cost audit in COST_DECOMPOSITION.md closes the failed contrast:
NC/full content minus NDU/full -0.003729004304, same-weight continuation benefit
+0.001311078897, complete CPU-price contribution +0.000323673272. The content
gap dominates this failure. Actual candidate/round receipts confirm unit-limited
admission; reserved future validation is not presented as executed padding.
All three shared dense base files match t8 byte-for-byte.

An external handcrafted RGB request exported/reloaded the selected seed11 affine
bundle, emitted `blue cross right` plus a real PNG, and exactly replayed choices,
PNG and checkpoint without dataset or ground-truth observer access. Its
selection_ready=false remains explicit. The standalone smoke cost 0.695437713
cumulative process-CPU seconds as a separate R&D demonstration, not a credit
against any build or evidence of the frozen batch-throughput qualification.
