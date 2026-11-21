# Authentic N256 boundary builders v2

**Status: SOURCE_ONLY REPAIR / HOLD / no execution key / not qualified.**

Attempt001 on Draft #6868 passed its exact runtime/resource gate and then rejected the dense-oracle `initial` array before writing either container: NumPy concatenation preserved a non-C-contiguous layout, while the canonical container contract requires `<f8` C-order bytes.

This independent v2 freeze changes both builders symmetrically: immediately after constructing the `(5, 257)` initial array, each calls `np.ascontiguousarray(initial, dtype="<f8")`. No value, shape, geometry, phase, ordering, selector, generator, tolerance, or downstream computation changes. Applying the repair only to one side is forbidden.

This stage performs zero authentic reads, NPZ decodes, numerical imports, builds, comparisons, dynamics, exponentials, Torch calls, or optimizer steps. It adds no workflow and no execution key. Attempt001 remains RED/INCOMPLETE with zero output containers; #6823 and every earlier RED/OOM/cancelled/UNKNOWN record remain unchanged.

A future attempt002 requires a separately frozen identity and new key. Exact boundary assembly still cannot qualify propagation, sparse kernels, N512, later cycles, arbitrary histories, full prior/migration/network training, task benefit, asynchronous cost, C2 full replay, HPCA external custody, production, or adoption.
