# Runtime-v3 mismatch localization (HOLD)

This separately frozen diagnostic reads only the immutable bytes preserved by
#6891 and the already committed dense oracle.  It decodes the canonical
full-state containers with the Python standard library, compares the same
69,728 FP64 coordinate bytes used by #6890, and publishes every one of the 665
mismatch rows plus exact field, tensor, ULP, sign, and magnitude summaries.

It executes no model, boundary builder, dynamic step, exponential, oracle,
Torch operation, or optimizer.  It cannot repair or relabel #6890 and grants
no qualification.  The strict zero-mismatch gate is unchanged.

Historical RED/OOM/cancelled/UNKNOWN records remain preserved.  C2 remains
0/6, HPCA remains NoUpdate, and global status remains HOLD with
`all_closed=false`.
