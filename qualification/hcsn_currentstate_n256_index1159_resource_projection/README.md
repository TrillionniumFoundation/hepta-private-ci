# N256 index1159 resource projection

This evidence-only stage reads the exact immutable index256 originals from #6948
and index537 originals from #6959/#6957. It performs one fixed integer-ceiling
secant projection per lane for compact and raw checkpoint bytes:

`b537 + ceil((b537 - b256) * 622 / 281)`.

The projected aggregate compact footprint is 78,827,589 bytes, or 11,718,725
bytes above the existing 64 MiB aggregate cap. The largest projected compact
cursor is 8,092,113 bytes, 296,495 bytes below the individual 8 MiB cap. The
largest projected raw cursor is 29,581,984 bytes, below the individual 32 MiB
cap. These are diagnostics, not resource bounds: compression and signed
cancellation are nonlinear, and two observed points do not establish
monotonicity or future size.

No index1159 checkpoint, recurrence, tail candidate, provider, model, Torch or
optimizer work is executed. This result does not freeze or grant an allocation,
authorize a run, close tail termination, or qualify N256. A separately frozen
actual checkpoint/cost profile remains required. Historical RED/UNKNOWN states,
HPCA NoUpdate and global HOLD remain unchanged.

Verify the immutable inputs before reproducing the committed diagnostic:

```console
python3 qualification/hcsn_ci_readbacks/6948/verify_readback.py
python3 qualification/hcsn_ci_readbacks/6957/verify.py
python3 qualification/hcsn_currentstate_n256_index1159_resource_projection/audit.py \
  --verify-expected qualification/hcsn_currentstate_n256_index1159_resource_projection/AUDIT.json
python3 -O qualification/hcsn_currentstate_n256_index1159_resource_projection/audit.py \
  --verify-expected qualification/hcsn_currentstate_n256_index1159_resource_projection/AUDIT.json
```
