# Authentic full-state readback of the N256 multistep archive

The published reader at PR #6753, commit `74fa2098330d738463626bafdf0a34385f321efe`, has now read the authentic sealed archive from #6752. Its Git blob is `608bac0ba20876c4cabb4a5dbd11766bca528e01`.

The result is `REAUDITED_FINITE_MULTISTEP_ARTIFACTS`: all 14 capsules and 18,279,371 coordinates were read; all 14 metric rows match the five corresponding capsule state blocks byte-for-byte. Ordered BDF queries/shapes and the complete final remaining-packet roster pass. All three genuine cold-state comparisons remain byte-identical.

The saved-reference differences are unchanged: warm/coarse 1.3933298959045715e-14, BDF state 2.905716466050645e-12, and coarse/fine BDF 1.1325379262877577e-10. Maximum probability/signed-content balance error is 9.35918009759007e-14.

The original 56,213,960-byte archive has SHA-256 `5f74d36864658fec8c6b2b2c32c3a27cefb959d83bdee58eb8ab76d364381fe8`. Every one of its 66 original files matched its manifest before and after the reader. The old REVIEW.json was preserved.

Full child cost: 3.127940311 wall seconds, 1.236862 user plus 1.113196 system CPU seconds, 192,984 KiB maximum RSS, exit 0. CPU 7, 4 GiB address-space cap and 30 CPU-second limit were applied before exec. The observed wall time is below the declared 60-second budget; this simple read-only launcher had no separate wall watchdog. Archive extraction and manifest checks are separate from the measured reader child.

This closes the pending authentic-artifact execution of the stronger reader. It does not regenerate BDF outputs or reintegrate remaining packet values, and it performs zero propagation/reference-solver/optimizer calls. Original sparse/dense bitwise RED and the continuum/AD/full-domain qualifications are unchanged.
