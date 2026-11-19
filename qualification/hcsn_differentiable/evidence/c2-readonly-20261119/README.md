# Original C2 read-only reconciliation

The six original fits were read on `desktop` on 2026-11-19 without modifying
their files or starting another training attempt. Native job
`1a1c74f3308-be2a-75` still reports `finalizing`/`unknown`: its supervisor
disappeared without a confirmed terminal receipt. The controller result is
absent. This observation does not create a terminal record for the old job.

`original-c2-journals-and-results.zip` preserves 55 original files (12,608,862
uncompressed bytes), including all six complete available event journals,
four fit results, admissions, and receipts. Its SHA256 is
`7f2001bcc178e78c5f8de120007110e93534ba5a19e490fff307065e5466d2c3`.
The incomplete final line in each of the two interrupted journals is preserved.
`audit.py` verifies every archived member, recounts valid journal events, and
recomputes development accuracy and macro-F1 from the original confusion
matrices. It performs no model or training replay.

| Original fit | New completed optimizer calls | Producer cumulative epochs | Recomputed development macro-F1 |
| --- | ---: | ---: | ---: |
| s101, lr 0.001 | 840 | 116 | 0.3440169978 |
| s101, lr 0.003 | 348 | 76 | 0.3878342597 |
| s211, lr 0.001 | 970 | no terminal result | unavailable |
| s211, lr 0.003 | 36 | 50 | 0.3910932361 |
| s307, lr 0.001 | 983 | no terminal result | unavailable |
| s307, lr 0.003 | 312 | 72 | 0.3498305889 |

The 3,489 completed calls are a lower bound from surviving C2 journals.
They do not close controller lifetime accounting. The four terminal fit
results are producer records. Their development metrics agree with the
confusion-matrix arithmetic to at most 1.11e-16 over 31,952 development events
each; this neither establishes an independent held-out benefit nor replaces
complete training replay, which remains 0/6.

```sh
python3 qualification/hcsn_differentiable/evidence/c2-readonly-20261119/audit.py
```

`originals/FILES.json.gz` preserves the first live inventory, including its
initial event parser's incorrect field choice. Those `UNKNOWN`/`update_count`
summary fields are explicitly unused. The corrected `kind` counts in
`originals/JOURNAL.json.gz` are checked against every archived original journal.
