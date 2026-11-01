# Independent review and retained corrections

## Controller and time semantics

The execution-cost reviewer identified that the first planner deducted the
number of reads in a complete plan even when an earlier timeout/failure could
prevent later reads from being issued. `ServiceEstimate` now carries the
expected issued-request count; planning uses that expectation and actual
execution uses the observed count. The preceding implementation remains in
`validation/source002/`; the regression passed in `validation/tests003/`.

The root reviewer required explicit model-time accounting across modalities.
Receipt schema v2 separates each modality's new prefix interval from the
increase in global maximum accepted source time. The core receives the latter.
The opposite-order two-modality regression passed. This versioned convention
does not retroactively establish the missing v6 model's time semantics.

The real subprocess adapter is a controlled small-output fixture. Its final
stdout-size check is after `communicate`; it is not a generic streaming bound
against an arbitrary encoder that emits unbounded output.

## Historical real-content review

The independent frontend reviewer compared every one of the 48 logical output
vectors and all eight real output vectors to the separately retained frontend
replay probabilities at the reconstructed accepted source prefixes. All
vectors were exactly equal. The review also confirmed:

- Every live episode has six accepted requests and a 0.12 observation fee.
- Completion chronology is valid and all live outputs were below four seconds.
- The selected live emotion outcomes are 0/4 and binding outcomes are 3/4.
- The overall historical integration uses 12 unique recordings; the live-only
  subset uses six, not 12.
- No future payload reaches the examined head/forecast interface.
- Calibration and model-selection reuse are development-only.

The independent cost reviewer checked all 13 requested receipt conditions,
including eight unique valid post-flush markers, complete waited-task CPU
coverage, unchanged meter and candidate sources, and 12 restored source Git
blob identities. The enclosing 16.068374 CPU seconds include the inner
11.137156 task CPU seconds. Those amounts must not be added together. The
81.925233439-second wall envelope covers fitting, logical replay, real replay
and artifact writing, so dividing it by eight would not estimate inference
latency. Family RSS and attributable energy remain null.

## Additional cohort and comparator limitations

A subsequent deterministic source-ID audit found that the four selected
binding pairs retain equal audio marginals but unequal video marginals across
labels. The original protocol and results remain untouched. See
`validation/historical001/POSTHOC_SUBSET_MARGINAL_AUDIT.json`. The 3/4 subset
score is an execution integration diagnostic, not a balanced binding quality
test. The full historical set has 24 pairs and equal single-modality marginals;
an additive replay uses all of it with the same fitted tables, without
retraining or claiming new confirmation.

The historical binding process ends at 1.5 source seconds. Prefixes 2 and 3
therefore contain the same final features. The common-full six-read schedule
is a complete-read reference, not the strongest inexpensive fixed schedule:
audio prefix 2 plus video prefix 2 can preserve its final content in four
reads. No qualified value-control or economic superiority follows from
comparing the cache table only with the six-read schedule. The missing v6
strong-audio reference remains unavailable and is never replaced by renaming
the shared joint head's audio-only ablation.
