# Fixed-grid substep-refinement negative control (2026-11-12)

A fresh heptaruntime desktop native execution on the unmodified source operator (Git blob `4f68cbd2b9b620e48a1aa85a9a6d04ff2313ace3`, SHA-256 `cb3eed1bcfbd3b10cc331a193a5d4b6a3d4309db899e0d8f821477f97b7dbdc1`) checked fixed-total-time compositions `Q(0.02/n)^n` against `Q(0.02)` for n=2,4,8,16,32, with drifts -0.4, 0 and +0.4.

**Negative result:** max row total-variation at n=2 is 0.320000 for each drift, whereas n=32 gives 0.453759 (-0.4), 0.455090 (0), and 0.453767 (+0.4). All compared matrices are nonnegative, finite, and row-stochastic within 1.5e-14. For the zero-drift first split, the max discrepancy is on a refractory-phase source row (index 19) with phase max 0.32 versus active max 0.06013; at 32 substeps the maximum shifts to an active source row. Thus decreasing dt alone need not repair this projected kernel, and preserving mass does not establish temporal consistency.

**Native original logs retained:** RED job `1a1cdce8685-2564-13b5` (exit 1, deliberately false 50%-improvement hypothesis); GREEN job `1a1cdcf113c-2564-13b8` (3/3, 0 skipped, exit 0). `RED.*` and `GREEN.*` are the separate exact stdout/stderr streams. Test source staged independently outside all existing worktrees and pinned to the source SHA-256; no original C2 process restarted, no model checkpoint executed.

This is a **synthetic** fixed-parameter counterexample, not a comparison with the exact continuum semigroup, trained posterior, actual task loss, or full P1 gate. The 14,336/14,336 recorded continuation-value failures of #6073 remain open. Do not treat this GREEN as a numerical repair or as P2–P5 GO. A future solver revision must be independently tested against continuum reference and the unchanged 1% visit-domain gate. The historical sentinel must not be relabelled on a changed source.

Exact parent: #6085 `646a05089432cfcc7b32874fed7aa56263c542f5`; P0–P5 `HOLD_NO_GO`.
