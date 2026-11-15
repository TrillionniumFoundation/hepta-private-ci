# P4 controls outside the diffusion assumption

This independent synthetic suite complements the real UCI sensor study. Its
signals and labels are symbolic; no Brownian, first-passage, renewal, HCSN
kernel, learned model or UCI normalization is used by the generator.
Generating or correctly interpreting these data earns no model-training credit.

## Three tasks

| Task | Required information | Scored output |
| --- | --- | --- |
| Overwrite retrieval | Remember the latest value for each of eight keys through distractors | Value of a subsequently queried key |
| Delayed copy | Remember an ordered eight-symbol payload and maintain a read position | Next symbol on each identical copy-read request |
| Pair composition | Retain two latest associations and combine them | Sum of the two values modulo eight |

Each episode resets all retained state. Training has 16 intervening distractors,
development has 32 and the fresh-seed probe has 128. The longer probe changes
retention distance while keeping the dictionary and output alphabet fixed.
It is an extrapolation probe, not blinded confirmation: the generator and
symbolic validator necessarily access its labels.

## Inputs, clocks and leakage controls

The common 21-dimensional input is four event-type indicators, eight key
indicators, eight observed-value indicators, and `log1p(dt)`. A query contains
its key(s), with every value indicator zero. A copy-read token carries neither
key nor value; there is no query index that reveals the answer. Only query/read
positions have a label; other positions use `-1` and must be masked in the loss.

Clock and symbol RNG streams are separate. Intervals are drawn from a discrete
irregular set between 0.001 and 0.16 in the declared physical time unit.
Changing clocks leaves symbolic answers unchanged. Some irrelevant distractors
omit their value channel; indispensable writes remain observed so the task has
a well-defined exact target. Clock, distractor and observed-mask robustness
must be reported separately from remembering the payload.

Counterfactual tests change earlier writes while holding query inputs fixed;
the targets must change. A separate exact interpreter checks overwrite, ordered
copy and two-key composition against hand-specified examples. An absent key is
an error, not an invented target or a default class.

## Fair experiment after numerical admission

Use a common frozen frontend and output head, with a separately disclosed
joint-training variant, and replace only the temporal core. Admit GRU, CfC,
tuned surrogate SNN, an event-gradient method, SSM, causal attention and HCSN
under the same seed/episode/order/resource protocol. Reusing the UCI frontend
or reporting its 11-class scores would be a different experiment.

To reuse a 25-dimensional common-input framework, append four zeros to each
21-dimensional vector: `x25 = x21 + [0, 0, 0, 0]`. This adapter preserves every
symbolic input and adds no information. Train all candidates afresh with the
same newly initialized 25-input frontend and an eight-class output head; freeze
those common weights in the primary regime. UCI normalization, its 11-class
head and trained weights do not carry over. Failure of UCI-trained weights in
a zero-shot probe is not evidence against the HCSN mechanism.

The current localization-v3 driver binds an official UCI preparation manifest
and assumes 11 labels. A separate synthetic task driver is required; do not
relabel this suite as an official UCI preparation. Supply episode-length valid
masks explicitly. In particular, the UCI-specific `x[..., 12:24].any(-1)` mask
heuristic does not describe this symbolic encoding and must not be reused.

The primary metric is accuracy on masked query/read positions, accompanied by
per-task cross entropy, sequence-exact copy success and accuracy versus actual
write-to-query delay. The declared chance reference is 1/8. Include memoryless,
last-symbol, exact dictionary/queue and HCSN content-only/no-reset controls.
The exact symbolic interpreter is an attainable oracle, not a learned baseline.

Freeze training, tuning and failure-retry budgets before fitting. Report both
equal-resource quality and time/peak memory/energy to the same quality target.
Count attempted updates, padding, dense probability cells, content width,
kernel construction, tracing and audit overhead; unavailable energy stays null.
Stop rules and memorization diagnostics must be fixed before interpreting
failures. A batch containing different episode lengths needs explicit valid
masks; zero elapsed time alone does not make a repeated observation padding.

The default maximum gap fits the current 0.2 delay envelope. A later long-gap
probe must either use a separately qualified propagation strategy or record
HCSN rejection as an unsupported case; silently clipping or subdividing gaps
changes the candidate. A task gain here is still synthetic. P4's real async
multimodal/sensor benefit and P5 hardware adoption remain separate gates.

```sh
python -m unittest qualification.hcsn_memory_controls.test_controls -v
python -m qualification.hcsn_memory_controls.generate --output /tmp/new-memory-suite
```

The generator refuses an existing output directory and writes all nine data
files with byte counts, SHA256 values, source hashes and zero training-run credit.
