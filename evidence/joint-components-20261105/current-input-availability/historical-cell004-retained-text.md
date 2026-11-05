# Cell004 transfer and actual downloaded-model readback

This is a new bounded batch following the three retained unsuccessful Cell
batches. It uses provider source `57fbdfeead5cfa1436eeef0d1691ee9933246d4d`
and its evidence-only successor `86a3ff97b5caf7af7a2406cf9079049ae11927ef`.
The fixed release binary SHA256 is
`e9b71c605cb15f37dc6522a19fffc428f455381122b76ba051c4e7d3ba3b2bb1`.
Driver, binary, original family and worker pins were checked immediately before
and after execution. The original Chain runtime remains `c96022b8`; the inspected
Hepta source remains `e1537d7d`. No original failed batch is overwritten.

## Actual transfer result

The new empty consumer acquired all eleven members and 269 chunks, totalling
272,189,870 payload bytes. Aggregate network acquisition, cache-only member
materialization and final consumer hashes completed in **25.906427551 seconds**,
within the original **35-second** limit. All eleven final destination hashes
match their pinned payloads. The aggregate fetch reports zero cached chunks,
269 downloaded chunks, 280 connections and 272,204,670 response bytes, within
the unchanged shared budgets. Materialization then spent zero network bytes
and zero connections for every member.

The finite provider retained its original 45-second lifetime and two-worker
limit. It reported 280 completed connections, zero overloaded connections and
two peak active workers. It exited zero and was reaped without forced cleanup.
Its stdout, stderr, terminal status and actual final counters are retained.
The controller took 69.813834943 seconds including packing and provider drain;
the enclosing observed invocation took 70.002815486 seconds. These durations
are different scopes and must not be substituted for the aggregate deadline.

This is one-host loopback transport between controlled processes, not independent
operators or a WAN throughput result. The old release batch003 connection reset
still has an undetermined cause. The independently reproduced worker-reclamation
window and the new successful batch do not retrospectively establish its cause.

## Actual next backend read

After the provider exited, the original `llm_inherited_runtime.py infer` loaded
only the consumer's downloaded base files and candidate adapter. The prompt was
fixed before training: `Answer with only yes or no. Is 103 greater than 102?`
The actual loaded parent and artifact both equal
`d3b3e79ee9432f467881b9b7fd5eef1c6d2908da6fce73de9fd786f541094dc6`.
The worker executed real forwards and generated eight tokens, decoded as `yes`.
The original supervisor reports success, exit zero, 29.929171552 seconds wall
time, 33.798063 CPU seconds and 1,147,097,088 bytes wait4 peak RSS. The enclosing
caller took 30.822501251 seconds. Sampled RSS and wait4 high-water retain their
original, distinct scopes; neither is aggregate process-tree memory.

## Authority and remaining gates

The **overall original handoff is still failed/exit1** at its explicit native
consumer/owner-receipt boundary. Transfer completion and the direct backend read
grant no selected CURRENT, ordinary Agentd task, FinalUse or installation receipt.
The candidate's prior all-yes 2/4 calibration and 2/4 evaluation result remains;
one correct fixed next answer is not model improvement or matched-control benefit.
Full runtime closure, ordinary I10, beneficial three-round acceptance and WAN
qualification remain open. No active model route was changed.

Hepta does contain a separate ordinary `hepta-neural-agentd` entry and the original
qualified neural bootstrap. That path requires actual product qualification,
independent selection/CURRENT and the original resource/FinalUse owners. The
controlled transfer driver's unavailable boundary is not evidence that every
native ordinary entry is absent. The current downloaded candidate does not
supply those required qualifications, and the initial-only selected-parent
callback does not authorize an ordinary task.

[observations.json](observations.json) records exact source, destination, cost
and qualification facts. [archive.json](archive.json) binds the
[76-file raw archive](raw-evidence.tar.gz), including unchanged batch003 logs,
new batch004 provider evidence, the actual downloaded adapter, original readback
receipts, requests and reproducible callers. Its internal inventory hashes every
retained file. Reproducible public base weights, wheels and cache databases are
excluded; all eleven consumer byte identities are recorded. No private signing
keys were generated and the limited credential-pattern scan found zero matches.
