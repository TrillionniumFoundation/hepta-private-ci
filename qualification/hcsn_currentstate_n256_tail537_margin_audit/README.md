# N256 index537 tail-margin read-only audit

This evidence-only stage consumes the immutable complete originals from #6959 and
does not execute the HCSN recurrence or another candidate tail check.

It verifies that every one of the 2,585 recorded binary64 intervals from #6957
straddles zero, while every exact `partial` and `iterate` coordinate in the ten
index537 checkpoints is nonzero. It then advances only the already-recorded
positive scalar growth-tail bound with integer arithmetic. The fixed question is
the first included index at which that scalar bound would be below one quarter of
the current index537 minimum absolute partial in each lane.

The largest tail-only threshold is index1159, or 622 bound updates after index537.
This is not a termination result: the signed recurrence, partial vector,
exponential sum, checkpoint bytes, resource cost and binary64 intervals at that
index have not been evaluated. In particular, it neither authorizes an index1159
run nor transfers N256 qualification. A separately frozen resource profile and
candidate run are still required.

Historical RED and UNKNOWN states are retained in `AUDIT.json`. Global state
remains HOLD / NoUpdate / `all_closed=false`.

Run the independent evidence verifier first, then the audit in normal and
optimized modes:

```console
python3 qualification/hcsn_ci_readbacks/6957/verify.py
python3 qualification/hcsn_currentstate_n256_tail537_margin_audit/audit.py \
  --verify-expected qualification/hcsn_currentstate_n256_tail537_margin_audit/AUDIT.json
python3 -O qualification/hcsn_currentstate_n256_tail537_margin_audit/audit.py \
  --verify-expected qualification/hcsn_currentstate_n256_tail537_margin_audit/AUDIT.json
```
