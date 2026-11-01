# Posthoc R18 scoped allocation diagnostic

The final V4b source `43bed3e4821bfe967e7f9e830e4559b62436daa0` was measured on already-opened `confirmation_02` index0 worlds. This diagnostic adds memory evidence; it does not alter the frozen quality/cost acceptance or add independent quality samples. No source, model or policy was changed.

There were 96 allocation groups: eight fits × three laws × two memory representations × two policies. Each method received its own fresh law and optional cache, then executed one IID and one OOD episode. The diagnostic made **192 paired comparisons / 384 executions on 16 owner worlds**, with **zero failures**. Complete semantic output—including every query checkpoint hash and logical belief-evaluation count—matched exactly after excluding only the three inherited timing fields. Query2 disk snapshot dictionaries also matched exactly.

## Allocation window

All imports, owner world construction and raw frozen model loading occurred before tracing. Each tracing window began before law/cache construction and covered two complete executions, including planning, actual observations, checkpoint fsync/readback/restore and retention of both output records and query2 JSON snapshots. End memory metrics were traversed after tracing stopped, so their own bookkeeping was excluded.

`tracemalloc` reports supported Python and NumPy allocations. It does not capture every native/BLAS allocator and is not a complete process-memory or GPU measure. Current bytes include the retained law/cache and two outputs/snapshots; peak bytes additionally include temporary allocations. Method order alternated across fit/model/representation/policy.

## Results

The cached planner uses more memory in this finite profile. For value-policy groups, mean cached/baseline scoped peak ratios range from **1.215730 to 1.234647**. Per-group individual peak increases range from **91,991 to 150,828 bytes**. The fixed read-refresh control has mean peak ratios **1.046954 to 1.059102** and individual increases **18,799 to 32,267 bytes**.

| Law | Representation | Policy | Baseline scoped peak range, bytes | Cached scoped peak range, bytes | Mean peak ratio |
|---|---|---|---:|---:|---:|
|hx|full|value|437,270–488,028|535,479–583,658|1.215730|
|hx|full|fixed|354,419–415,431|374,347–439,704|1.058518|
|hx|anchored|value|583,827–703,519|727,631–854,056|1.233337|
|hx|anchored|fixed|562,637–668,345|588,253–692,880|1.047022|
|free|full|value|434,582–477,025|535,014–583,418|1.224208|
|free|full|fixed|354,977–414,355|374,229–440,155|1.058856|
|free|anchored|value|583,560–703,593|727,737–854,340|1.234647|
|free|anchored|fixed|562,586–667,740|587,782–693,790|1.046954|
|hmm_same_matrix|full|value|434,232–476,311|534,573–583,228|1.225301|
|hmm_same_matrix|full|fixed|354,696–413,680|373,987–439,770|1.059102|
|hmm_same_matrix|anchored|value|582,978–703,525|727,451–853,737|1.234333|
|hmm_same_matrix|anchored|fixed|561,714–666,687|587,122–691,691|1.047035|

Across all traced groups, baseline current allocations were **254,541–556,470 bytes**, and peak allocations **354,419–703,593 bytes**. Cached current allocations were **284,783–588,043 bytes**, and peaks **373,987–854,340 bytes**. These ranges combine different laws, representations and policies; they do not describe one simultaneous process total.

The deduplicated end-of-window law/cache ndarray inventory increased by **25,600–30,720 bytes** for every paired group. The wrapper cache held **5–6 entries** under its 64-entry capacity. Ordinary law transition-cache entry counts were identical between baseline and cached modes for each pair: **13–16** for full memory and **25–36** for anchored memory in the measured policies. The ordinary transition cache still has no global arbitrary-time bound, so this finite inventory does not establish production memory bounds.

## CPU and RSS scope

The complete instrumented child consumed **16.957105 CPU seconds**, including imports, all preparation/attempts, tracing and output writing. Its wall time was **17.655404 seconds**. Its shared aggregate maximum RSS was **77,472 KiB**. One process hosted both methods, so this RSS cannot be assigned separately to baseline or cached execution.

Tracing changes runtime cost. Its CPU does not replace the uninstrumented confirmation CPU ratios and is a separate posthoc diagnostic cost. Nested per-arm timing must not be added to this outer child receipt.

Raw outputs, per-arm current/peak allocations, cache/law inventories, source identities, protocol, diagnostic source, stdout/stderr and the complete child receipt are retained. The measured CPU gain therefore has an explicit finite memory tradeoff; there is no memory-saving or full-process per-method RSS claim.
