# C2 prospective recording addendum v2

The v1 design and policy remain unchanged. Their no-grad windows are supplemental checkpoint visits, not visits collected during optimization. The recovered original v8 trace contains only update_index=0, so it supplies no retained post-update training-state coverage.

This addendum predeclares an additional sparse record of actual main-gradient work: the first microbatch after restoration and the first microbatch of the first effective batch in absolute epochs 50, 75, 100, 125, 150, 175 and 200. The exact original TrainingDomainRecorder is attached inside the actual backward_effective_batch call with gradients enabled. No surrogate replay, extra optimizer update, numeric-core change or altered gradient is introduced.

Each slot is exclusive, 32 MiB and 256 rows maximum. It preserves the ordered eight actual sample identities, validity-mask hash, complete effective-batch identity, full model digest, checkpoint bytes, actual dt, source identity, logical completed-update index and a separate historical work counter that includes discarded parent updates. The trace is closed and its footer, source and coverage checked before the optimizer step. Truncation or missing capture is HOLD and stops further optimization; all forward/backward and failed recording costs remain charged. A separate immutable completion receipt records whether the associated optimizer step actually completed.

The eight optimization slots add at most 256 MiB per fit to the v1 supplemental cap of 240 MiB, for a maximum 496 MiB per fit and 2,976 MiB across six fits. All I/O and capture cost consumes the cumulative 12-hour active budget. If a resume epoch coincides with a fixed slot, one trace carries both labels and is not counted twice. Unreached slots remain absent without substituting a favorable checkpoint.

These are actual optimization-time visits at the selected microbatches. They still do not establish whole-training-domain coverage or numerical qualification. No real C2 optimizer step is authorized or executed by this preparation artifact.
