# Boundary x content mechanism pilot

This fresh executable study isolates a task-trained static boundary from content
writing. It uses the existing symbolic overwrite-retrieval, delayed-copy and
pair-composition generator. These are non-diffusion synthetic tasks. Generator
seeds begin at 30,261,112, outside the old suite's seed ranges. These are new
examples, not independently acquired real sources.
The historical C2 job, its checkpoints and subject E are not inputs.

| Arm | Content writes | Static boundary |
| --- | --- | --- |
| c0_b0 | Frozen | Frozen |
| c0_b1 | Frozen | Learned |
| c1_b0 | Learned | Frozen |
| c1_b1 | Learned | Learned |

Only write_gate, content_proposal and state_embedding belong to the content
factor. The likelihood, 21-to-4 frontend, network readout, drift, diffusion,
absolute reset, discount, deterministic refractory and grid remain fixed.
There is exactly one layer: content cannot feed a later frozen likelihood.
A behavioral test intervenes on content parameters and requires every
posterior to stay unchanged at a fixed boundary.

The boundary factor is the single raw_log_boundary parameter. The physical
log boundary is 0.12*tanh(raw). This is a task-trained static threshold,
not a DP/QVI optimal free boundary or an input-dependent boundary policy.
Absolute initial and reset locations stay fixed, so their distances relative
to the boundary change when it learns. A new episode state is constructed on
every forward, including every finite-difference perturbation.

All four arms have identical complete initial tensor bytes per model seed.
The fixed readout is intentional for this mechanism pilot. Its four content dimensions plus five physical readouts and fixed random
weights can restrict achievable output confidence. A negative
result here does not establish failure with a trained readout. The c0_b0
development metrics also provide the paired seed's untrained-model reference.

## Execute

Use CPU PyTorch and the repository's existing numerical dependencies:

~~~sh
python -m unittest qualification.hcsn_boundary_factorial.test_run -v
python -m qualification.hcsn_boundary_factorial.run \
  --output /absolute/new/smoke --seeds 11 --updates 1 \
  --train-per-task 1 --development-per-task 1 --wall-seconds 240
python -m qualification.hcsn_boundary_factorial.run \
  --output /absolute/new/probe --seeds 11 23 37 --updates 32 \
  --train-per-task 4 --development-per-task 8 --wall-seconds 1200
~~~

The ordinary default is eight steps per arm; the final command explicitly
uses 32. The per-study wall ceiling includes imports after the initial timing
statement, source/data preparation, model construction, all training forwards,
backpropagation, full trace writes, development evaluation, checkpoint saves
and new-model checkpoint replay. The external process's startup/queue/CI setup
cost needs its own outer receipt. Per-arm timing excludes only writing its
final result; whole-study timing includes those arm results but excludes the
final SUMMARY write. Resource costs are observed, not guaranteed equal.

Equal training-forward opportunities do not mean equal FLOPs. The fully fixed
arm performs all declared training forwards, creates no optimizer, and records
zero Adam updates. The other arms actually backpropagate and update Adam.
Every training forward's actual probability/content states are retained without
a prefix cap. No frozen-table cache is used. Budget/failure paths keep a model
and optimizer checkpoint and receive no successful-arm credit. Checkpoints do
not promise exact training restart or preserve interrupted autograd state.
New-model readback checks final development predictions; it is not an
independent full optimization replay.

The grid has 16 active cells, one returning tail, eight refractory phase
cells, endpoint 4.8, refractory 0.2 and quadrature order 16. At content width
four its probability/content tensor payload is 1,000 bytes per sample.
This excludes parameter snapshots, clocks, table storage, temporary tensors
and autograd; the report also retains process peak RSS. This coarse profile
has no train-visited continuum numerical qualification.

Per-seed effects use Q = negative query-position cross entropy. Boundary
effects are Q01-Q00 and Q11-Q10; interaction is Q11-Q10-Q01+Q00.
Missing arms remain in expected denominators. No p-value, confirmation claim,
energy claim, trained-baseline ranking or product adoption follows from this
pilot. Reset/no-reset and refractory alternatives are not tested, and reset
does not automatically erase content in the underlying network. Mathematical
gradient tests compare implementation AD with independently perturbed forwards;
they do not establish continuum gradient accuracy.

The implementation was prepared while the local execution environment was
unavailable. Test and experiment outcomes must be obtained from the exact
submitted source's actual CI artifacts, not inferred from this document.
