# Four structures under an update stream: measured result

## Decision

Do not enable automatic Cell splitting on the strength of this experiment.
The dynamic candidate preserved the registered facts, but it did not outperform
the fixed experts or the equal-parameter monolith on held expressions. A
successful split implementation is not evidence that splitting improves the
system.

The experiment executed 24 independent training processes: three original
checkpoint seeds, four structures and two budget regimes. Each process handled
three sequential policy changes, saved every intermediate model, reopened it
and checked its predictions. All training processes exited before the evaluator
opened the held-expression artifact. The source and input hashes are in the
freeze and raw evidence.

## What was held constant

The input is the original `formal-01` artifact from commit
`0f41c4968eea63727c69e2b979491e94a99a9dbb`, with all archive and member SHA-256
digests verified. The frozen MiniLM encoder identity is
`4bff7b22bc544468dca828c404026aaa5d011ce83e305d056c14a24658955faf`.
The parent models are the original semantic checkpoints for seeds 731–733.
No parent was retrained or substituted.

Every arm begins with the same parent function and frozen task head. Typed
outputs must match exactly. Floating logits use a declared float32 tolerance
of `rtol=1e-5, atol=1e-5`, because splitting a batch can select a different BLAS
reduction order; the observed maximum error is retained in each training
receipt. Reopening a checkpoint with the same batch shape must give exactly
the same logits.

| Arm | Structure | Total parameters | Trainable parameters |
| --- | --- | ---: | ---: |
| Dynamic | Two rank-4 adapters, training-gradient partition, routes reconsidered at each update | 10,764 | 6,144 |
| Fixed experts | Two rank-4 adapters, frozen alternating entity partition | 10,764 | 6,144 |
| Monolith | One rank-8 adapter | 10,764 | 6,144 |
| Fixed graph | Two serial rank-4 residual operators, one shared head | 10,764 | 6,144 |

The fixed graph is an actual differentiable serial graph. It is not another
name for the retrieval planner. The second residual operator starts as the
identity, so it does not change the initial parent behavior. Each arm has one
unique frozen head in memory; physically duplicated head serialization is
counted in checkpoint storage.

All arms receive the same prefix facts, replay rows, encoder features and
explicit entity addresses. This isolates structure from language addressing;
it does not replace the separate native addressing experiment. Updates change
two reserve values, one pack value and one limit value in a fixed order.
Earlier updates and untouched original facts are measured after every phase.

Training runs sequentially on one pinned CPU. Arm order rotates across seeds.
The matched-exposure regime uses exactly the same minibatch schedules, with
400 updates of 32 rows in each phase. The CPU-budget regime gives each phase
1.5 seconds of learning CPU, including gradient selection and optimizer setup.
Initialization, checkpoint writing, reopening, diagnostics, process startup and
evaluation are separately measured and reported. **The learning allowance is
not an exact total-lifecycle CPU cap.** The actual lifecycle totals below are
therefore part of the comparison, not an omitted overhead.

## Results

Counts aggregate three seeds and three updates. The 576 held rows are repeated
combinations of eight wording groups, eight entities and three updates; they
are not 576 independent trials. No statistical-significance claim is made.

### Same training exposure

| Arm | Canonical facts | Untouched original facts | Held expressions | Training process CPU, seconds | Stored checkpoints, bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Dynamic | 72/72 | 45/45 | 530/576 | 17.492 | 567,763 |
| Fixed experts | 72/72 | 45/45 | 543/576 | 17.473 | 568,058 |
| Monolith | 72/72 | 45/45 | 542/576 | 15.292 | 387,288 |
| Fixed graph | 72/72 | 45/45 | 530/576 | 16.125 | 567,014 |

Every arm consumed 115,200 training presentations. The one-row difference
between fixed experts and the monolith is descriptive; it does not establish
a reliable generalization advantage. The dynamic candidate had lower held
accuracy and higher measured CPU cost than the monolith.

### Same learning CPU allowance

| Arm | Canonical facts | Untouched original facts | Held expressions | Training process CPU, seconds | Training presentations |
| --- | ---: | ---: | ---: | ---: | ---: |
| Dynamic | 72/72 | 45/45 | 539/576 | 25.789 | 263,200 |
| Fixed experts | 72/72 | 45/45 | 551/576 | 25.309 | 287,904 |
| Monolith | 72/72 | 45/45 | 559/576 | 25.356 | 494,624 |
| Fixed graph | 72/72 | 45/45 | 526/576 | 25.363 | 372,032 |

The monolith processes more training rows under the same allowance. The
dynamic partition and Python expert dispatch have costs that a parameter-count
comparison alone would miss. This is a measured implementation result; it is
not a lower bound on every possible expert implementation.

The tables retain whole training-process CPU. The machine-readable result also
contains coordinator CPU, fresh evaluation CPU, complete process wall time,
20 ms sampled resident-byte integrals, selector cost, sample schedule hashes,
all per-phase predictions, checkpoint digests, reload errors and storage sizes.
For example, the dynamic matched-exposure arm adds 0.349 seconds of coordinator
CPU and 0.082 seconds of evaluation CPU; the monolith adds 0.296 and 0.042
seconds respectively. These additional measured costs do not reverse the
decision.

## Interpretation and limits

The experiment demonstrates adaptation to the specified changes and retention
of the unchanged registered facts. It does not demonstrate a benefit from
dynamic splitting, recursive growth, general planning, new-entity language
understanding, or general intelligence. The dynamic arm has at most two
experts; it is a bounded split candidate, not an open-ended growing network.

The held-expression artifact was published by the earlier study. This run is
an exploratory reuse, not a new blind holdout. The trainer never opens it,
and no held score is used to choose routes or change a threshold during this
run. Independent future tasks are still needed for an out-of-distribution
claim.

The experiment uses the existing Python research TensorCell operator and
cached frozen encoder features. Original parent-training and encoder receipts
are retained as common prior costs; they are not silently reclassified as new
per-arm CPU. The encoder artifact occupies 127,536,988 bytes. These results do
not establish full-agent or distributed-system cost superiority. Native
numeric parity, original-owner lifecycle checks and physical-node transport
are separate evidence levels.

## Reproduction

Restore the existing `formal-01` archive with its original `restore.py`, verify
every digest, and use a Python environment with the recorded NumPy and Torch
versions. The run records the exact interpreter, package versions, CPU affinity
and source hashes; no GPU is required.

```bash
python -m unittest discover -s qualification/cell-meta-network -p '*tests.py'
python qualification/cell-meta-network/structure_study.py \
  --fixture /absolute/path/to/formal-restored \
  --output /absolute/path/to/new-result-directory
```

The output directory must be new. The runner freezes inputs and code before
training, checks identical parameter counts and matched sample schedules,
preserves subprocess logs, reads fresh checkpoints and writes `RESULT.json`.
The experiment's acceptance decision remains negative unless a future,
separately frozen comparison supplies better evidence.
