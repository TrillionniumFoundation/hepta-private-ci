## Retention fitting screen: completed negative development result

The preregistered nine-trial screen completed without an execution or integrity
failure. Neither proposed intervention improved the baseline. The frozen rule
selected the original completion-CE arm at learning rate 0.001, and **no arm
passed the development quality gate**. The larger retention stream remains
unexecuted. These results do not support promoting the new margin objective or
the higher learning rate.

The complete raw audit passed **753/753 checks**. It independently reconstructed
training token charges, hashed actual adapter tensors, decoded saved token IDs,
recomputed every quality score and the selection rule, joined real source-store
withdrawals, and verified the retained artifact inventory. The audit used the
fixed tokenizer and saved records; it performed no decoder or model execution.

### Why this experiment was needed

`training_backend.train_candidate` constructs a fresh `SourceMemoryCell`, resets
it, and trains on current live facts for each clean publication. The previous
six-round service experiment did not continue the previous adapter. Its final
retention deficits therefore did not, by themselves, identify incremental
catastrophic forgetting. With 256 single-example updates over 32–40 training
examples, incomplete fitting, source/value binding and wording transfer were
distinct development hypotheses.

The new `source_value_margin_v2` objective allows unequal-length negative values:

`CE(positive value + EOS) + relu(1 + mean_logp(negative value) - mean_logp(positive value))`.

The positive forward supplies both CE and the positive value score. EOS is
included in positive CE and excluded from both margin scores. Each positive
source cycles over distinct tokenized values from current live facts; all used
negative source roots enter ancestry. Existing CE and equal-length
`source_margin` behavior remain unchanged. The original baseline's exact
reproduction is additional evidence that the new branch did not alter CE here.

### Frozen design and complete results

Each seed used fresh rank-8 parameters from the same pinned
SmolLM2-135M-Instruct base. CE at either learning rate used 256 updates and
256 actual forwards. Margin at 0.01 used 128 updates and 256 actual forwards.
Arm order rotated across seeds. All nine source histories, requests, panels,
source hashes and the selection rule were frozen before the first trial.

| Seed | Arm | Training queries exact | All four training wordings | Current, both heldout wordings | Unchanged retention |
| --- | --- | ---: | ---: | ---: | ---: |
| 24019 | CE 0.001 | 24/40 | 6/10 | 5/10 | 3/8 |
| 24019 | CE 0.01 | 0/40 | 0/10 | 0/10 | 0/8 |
| 24019 | Margin 0.01 | 0/40 | 0/10 | 0/10 | 0/8 |
| 24023 | CE 0.001 | 32/40 | 8/10 | 8/10 | 6/8 |
| 24023 | CE 0.01 | 0/40 | 0/10 | 0/10 | 0/8 |
| 24023 | Margin 0.01 | 0/40 | 0/10 | 0/10 | 0/8 |
| 24029 | CE 0.001 | 9/40 | 2/10 | 2/10 | 1/8 |
| 24029 | CE 0.01 | 4/40 | 1/10 | 1/10 | 1/8 |
| 24029 | Margin 0.01 | 0/40 | 0/10 | 0/10 | 0/8 |

Every disabled-adapter and shuffled-adapter control scored **0/10** current
sources under the same two-wording rule. CE 0.001 answered the final corrected
source exactly at every seed, 1/1 each; both candidate arms scored 0/1. The other
newly eligible source in the final round came from conflict resolution, rather
than a second correction. With eight retained sources, the frozen retention
threshold of 0.9 requires 8/8; together with the one correction this requires at
least 9/10 current sources. No threshold or denominator was changed afterward.

The baseline exactly reproduced the prior terminal current counts
5/10, 8/10 and 2/10 and retention counts 3/8, 6/8 and 1/8. Its training-query
accuracies were 60%, 80% and 22.5%, compared with heldout-query accuracies of
55%, 80% and 20%. Fourteen of its thirty source/seed observations failed both
the training-all-four and heldout-both tests; only one source passed all training
wordings and then failed the heldout pair. The dominant observed deficit is
already present on training wordings. Wording transfer alone cannot explain it.

The high-rate arms produced constant labels, truncated values, empty output or
repeated token fragments. For example, the low-rate seed 24029 answered every
heldout question with `silver`, while its high-rate CE counterpart answered
every question with `white`. The margin arm at seed 24019 repeated `sil` until
the generation limit. All parameter updates were finite; successful numerical
execution did not imply useful learning. These observations support a fitting
or binding failure but do not uniquely establish its optimization mechanism.

The CE learning-rate contrast holds initialization, schedule and update count
fixed within each seed. The tested increase to 0.01 was harmful. The margin
contrast also changes update count under the equal-forward budget, so it cannot
isolate a universal benefit or failure of margin objectives. Descriptive output
and loss summaries were examined only after completion and did not alter
selection or trigger another trial.

### Actual compute and storage

| Arm, all three seeds | Training forwards | Optimizer updates | Training input tokens | Fit seconds | Maximum training self RSS, KiB |
| --- | ---: | ---: | ---: | ---: | ---: |
| CE 0.001 | 768 | 768 | 56,953 | 445.679 | 1,171,476 |
| CE 0.01 | 768 | 768 | 56,953 | 456.391 | 1,164,412 |
| Margin 0.01 | 768 | 384 | 56,952 | 444.215 | 1,338,208 |

Across all trials, the audit verified **2,304 entered and completed training
forwards, 1,920 optimizer updates, 170,858 training input tokens and 5,150 charged
supervised token positions**. Positive value positions reused by CE and margin
were not double-counted. There were 9 fresh training processes and 27 fresh
reader processes, with 36 distinct child PIDs. The 900 decoder queries consumed
66,330 input tokens and generated 7,237 tokens. No attempt was retried or refunded.

Whole-screen wall time was **2,439.136 seconds** (40.65 minutes). Child wall
times summed to 2,437.776 seconds; training fit time was 1,346.285 seconds and
decoder generation time was 711.744 seconds. Fit and generation are subsets of
child wall time. They must not be added to it as separate elapsed costs.

Each trial had 460,800 active trainable parameters, or 1,843,200 F32 parameter
bytes. The nine checkpoint directories totaled **17,080,674 bytes**. Complete
screen artifacts totaled **22,310,679 bytes**, including raw journals and
process diagnostics. The inventory before final-report creation covers 294
files and 21,972,944 bytes; the final result and inventory file account for the
remaining bytes. No base weights were copied. The preexisting six-file base
occupies 271,170,520 bytes and is outside new screen storage.

These are screen costs. They exclude runtime installation, unit-test compute,
other repository work, parent-level reports, the superseded registration and
the unexecuted stream draft. Unit tests include tiny random-decoder execution,
not the fixed pretrained model. Whole-host CPU, energy and FLOPs were not
measured. Equal training forwards do not establish equal optimizer updates,
supervised tokens, latency or full system cost.

### Source boundaries, execution identity and remaining gates

All nine trials replayed real `MemoryService` source events, claimed actual
training leases, published through the real CAS, and read through live
owner/frontier admission. Reader requests contained questions and checkpoint
metadata, with no facts, retrieval results or answer lexicon. Source-overlay
answers were excluded from parameter scores. After all panels, each trial
performed a real revocation: the revoked key and another live key both refused
use of the stale parameter binding, totaling 18 denials and zero decoder
callbacks. This establishes use denial, not physical parameter erasure.

The runner exited 0. Its final result was written at
2026-10-25 13:17:48.556320 UTC. At 13:18:03.540072 UTC, all 52 pinned source files,
including all 25 shared `memory_cell` files, still matched the frozen inventory
and `memory-cell-stable-002.json`. The final raw audit also independently rehashed
all six base files. The model lane was released to the separate daemon qualification.
This local experiment identifies frozen working-tree bytes, not a clean
committed-source or hosted run. Source tests passed 18/18 and 7/7 before launch.

Canonical protocol SHA-256:
`373ef27c4450a5afb80adad16d12fedfba4d5e3f68ea5692fd2deab3c71c7f3d`.
Canonical 52-file source inventory SHA-256:
`13e3245414c2d71d9d26d05bea831f83edc3a33ca5db67f77ce752d69ef4cbeb`.

The eight-round, three-seed, two-arm draft was only replayed through metadata
and source stores. It has executed zero model calls. It reserves 12,288 training
forwards and 2,568 reader queries, but its prerequisite—a qualified nonbaseline
candidate—is absent. Even a simple projection from this screen's mean child
times is 10,329.599 seconds before larger inputs and coordinator work, close to
the draft's strict three-hour ceiling. It requires a separate registration and
launch decision; it is not an automatic continuation.

All terminal states and templates here were previously exposed development
data. The three seeds share a synthetic task design, and the 900 repeated
questions are correlated observations. This terminal-snapshot screen is not a
multi-round or natural-domain retention qualification. External production
authority/clock qualification, strong-retrieval comparison and independent
future natural-task evaluation remain open. **Production acceptance is false.**
