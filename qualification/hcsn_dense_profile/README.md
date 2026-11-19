# HCSN v3 recovery record — HOLD

This branch preserves observed scalar metadata after loss of an unpushed scratch experiment. It contains no executed v3 source, original NPZ, or full raw receipt. `ORIGINAL_BYTES_LOST.json` supersedes the earlier pending-recovery status: the replaced executor no longer has the originals.

The complete published parent is #6207, `fa25828fc4faee625c10db1f70add43f0074ff41`. Its actual-source v2 finite arrays remain intact. The new near-dense v3 profiles are not qualified by this record. Any reconstruction or reproduction must use a new source and attempt identity.

The observed near800 profile remained above 1% at the retained rare case. The observed near960 profile reduced that exposed case to about 0.985%, with worse right-tail continuation error. These are post-failure observations, not new scientific admission. The original source/raw needed to review those numerical runs is lost; their scalars remain only as transparent recovery metadata.

The earlier interpretation that DDE time integration caused the spectral/JF gap was corrected before loss: the positive-series observation agreed with the tight DDE. Neither explanation is elevated to a new source-bound result here.

No new model, kernel, optimizer or numerical experiment was run to produce this recovery record. `all_closed=false`.
