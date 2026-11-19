# Combined zero-age and changing-law qualification

The zero-age candidate is stacked on Draft #6760 at
`b113f0b36fdbda4c40160148c7cba2dc5f9275e0`. The preceding four-case comparison
remains frozen in `../zero-age-20261119`; its source and all negative results
are unchanged. This separate create-only run exercises the **same optimized
kernel** with the independent variable-delay/reset/reward/discount reference.

Actual command: `python -m qualification.hcsn_currentstate.run_timevarying
qualification/hcsn_currentstate/evidence/zero-age-timevarying-20261119-attempt001`.
The existing wrapper fixed logical CPU 6, a 4-GiB address-space limit, 90/95
soft/hard CPU seconds, and a 150-second wall deadline. All source hashes matched
before and after execution. No training or dataset access was requested.

The complete-field DDE error was **3.65853e-13**, probability/content balance
error **7.97140e-14**, twelve-parameter AD versus independent ODE finite
differences **3.31358e-10**, and actual fresh-process continuation error
**1.49991e-13**. The elementary signed-reward/zero-discount/swept-atom case
agreed within **2.22045e-16**. Every declared original tolerance passed.
The actual gradient value is retained without rounding in `RESULT.json`.

Full-child wall/CPU were **10.659435 / 10.585692 seconds**, peak RSS
**256,016 KiB**. CPU timing across separate shared-host attempts is not used
to infer a speedup. All raw outputs, complete cold state and source/request/cost
records are retained.

The existing CPU workflow now runs the zero-age/network checks and the portable
`study_timevarying` entry on the exact PR head, with the same artifact upload.
The local test result does not imply that hosted CI has already completed.
The separate original `t=.61` strict Torch matrix-exponential failure is still
retained as a negative result in the zero-age record; it is being repaired in
a later, independently qualified precision change. No original numerical or
scientific gate is overwritten.
