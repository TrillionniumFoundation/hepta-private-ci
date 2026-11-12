# Native 624-generation development result — HOLD_NO_GO

The precommitted source #6145 (`5fe8da68b1c6488957e49b8d874946b2d6b6604f`)
ran the frozen SmolLM2-135M base and all eight original V2 adapters on ai395.
No retraining, task replacement, label inversion or decision-threshold fitting
occurred. Data/protocol were previously published in #6132.

## Actual result

| Condition | Context correct /32 | Retention correct /32 | Valid primary /64 |
| --- | ---: | ---: | ---: |
| Base | 16 | 18 | 64 |
| Seeds11,17,29: each interleaved and bursty | 16 | 17 | 64 |
| Seed23: interleaved and bursty | 15 | 18 | 64 |

Only the separate16-question base calibration selected the preregistered
explicit-binary chat wrapper:16/16 leading-label valid,10/16 correct, versus
5/16 valid and2/16 correct for original chat. The separate base development
panel was8/16 correct. All four paired bursty-minus-interleaved correct-count
differences are zero on both primary panels. These are descriptive negative
results, not statistical equivalence or evidence of a scheduling advantage.

The chosen parser accepts a leading standalone YES/NO. It does not enforce an
entire completion consisting of only that word. Descriptive exact-label-only
counts are9/16 calibration and375/576 primary outputs, ignoring case/outer
whitespace. These additional counts do not replace the frozen primary metric.
Base answers YES to all32 context questions; adapters answer YES30–32 times.
Thus parseability improved while strong answer bias and poor task performance
remain. The base retention score18/32 fails the predeclared24-correct competency
gate. A qualified old-capability retention claim is not established.

## Original execution and bytes

- Durable native job `1a1ce7469c5-2564-1687`, idempotency key
  `hpca-c06d-native624-source-5fe8da68-v2`: terminal success, exit0, no timeout or
  output truncation. Exactly624 generations and1249 journal events completed.
- Source/script SHA256 `a3a5940df54e060eab4bc3c9050df7253aefd78c4ea47c47a7883fbc88971a61`.
  All seven executing source/input blobs were read back from the published
  GitHub commit before launch and rechecked before/after model execution.
- Original RESULT:394505 bytes, SHA256
  `fac237f080f52843f3d92ca7d90b1361c1ba78dd6141174b310de1a47d0ae944`.
- Original ZIP:121529 bytes, SHA256
  `583a41faee2ea035aa93b89d6ffc774d1b01ef293c761e304552e265b3dc836a`.
  `NATIVE624-v2.zip` contains17 untouched files plus its manifest: raw RESULT,
  PREEXECUTION,1249-event journal, config, wrapper selection, publication/source
  files, process logs, resource report and exit record. Every member hash/size
  and both version-bound transfer chunks were verified locally.
- GNU time:118.26s wall,425.19s user CPU,1.07s system CPU, peak1175144KiB RSS.
  The systemd command enforced CPUQuota400% and MemoryMax4GiB. Full control,
  source transfer, queue/setup, acquisition and energy costs are not measured
  by this process timing; no efficiency claim is made.

`review_raw.py` independently recounts the stored bytes without importing Torch
or the experiment runner; `RAW_REVIEW.json` records its full consistency result.
This is a second arithmetic implementation, not another forward experiment or
external scientist/Owner attestation. Run `python review_raw.py NATIVE624-v2.zip`.

## Attempts, CI and boundary

The first launch request exceeded the tool's64KiB shell limit and was explicitly
rejected before process creation: zero model generations. Its compressed v2
request is the sole accepted model job. Source-only preparation and a runtime
version read had delayed/missing acknowledgements and never invoked a model;
they were not relabeled as successful experiments. Original inference was not
restarted after an uncertain acknowledgement.

Source-head preflight Actions43168132597, inherited runtime43168132634,
microqualification43168132646 and v8-canary43168132635 succeeded. Blocking-ci
and architecture remained queued at observation. These checks and the new
evidence-head checks are separate from the actual native model evidence.

The96 questions are visible operator development tasks, including eight
correlated fictional worlds. They are not an independently held future cohort.
External curator/Owner custody remains MISSING, model utility is adverse, and
the retained-capability gate failed. All scientific/production selection stays
HOLD_NO_GO; no owner permission, model adoption or deployment is authorized by
this result. Original B2/exposed24 negatives remain intact.
