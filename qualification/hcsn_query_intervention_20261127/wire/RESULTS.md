# Actual process-to-process traffic and cost for continuous replies from live spike data

Two OS processes transmitted and received every application byte over Unix stream sockets and TCP on 127.0.0.1, three repetitions per configuration, 120 runs. The 10,170 archived EPFL slots have two primary probability requests, at 4 and 12 ms. All outcomes below use the actual repeated trials. Byte counts are exact in both transports. They include the stated application framing and exclude TCP/IP/link headers, external clock distribution and experiment instrumentation. Calls and operating-system packets need not correspond one-for-one.

| Protocol | Total two-way application bytes | Source sends | Mean absolute probability error | Increase in measured NLL |
|---|---:|---:|---:|---:|
|Dense 2 FP32 per slot|81,360|10,170|0|0|
|Dense 5 FP32 per slot|203,400|10,170|0|0|
|Indexed updates, tolerance .001|81,912|6,826|.000118|.000081|
|Indexed updates, .005|65,844|5,487|.000646|.000692|
|Indexed updates, .01|52,368|4,364|.002230|.001664|
|Indexed updates, .05|17,088|1,424|.012877|.009106|
|16-slot bitmap, .001|55,880|636|.000118|.000081|
|16-slot bitmap, .005|45,168|636|.000646|.000692|
|16-slot bitmap, .01|36,184|636|.002230|.001664|
|16-slot bitmap, .05|12,664|636|.012877|.009106|

Sending fewer updates can cost more bytes: at .001 tolerance, the absolute slot ID consumes the savings. Bitmap updates at .01 reduced traffic by 55.5% compared to the dense pair, with maximum probability error .0099994, positive NLL change .001664 and Brier change +.0000442. The bitmap accumulates up to 16 slots, a possible 30-ms lag at the source's original 2-ms bin spacing. Index-based silence needs a common time reference for online reconstruction.

| Selected demand | Queries | 5-byte request + 4-byte reply, known forcing | Same protocol with future FP32 forcing transmitted |
|---|---:|---:|---:|
|10%|1,004|9,036 B|25,148 B|
|50%|5,139|46,251 B|129,027 B|
|100%|10,170|91,530 B|255,146 B|

One requested horizon per selected slot is compared to publishing two horizons per slot. The traffic crossover with shared input is 8/9 of all slots, since dense publication costs 8 bytes per slot and an indexed query/answer costs 9. At every slot, query-only transfer used more bytes than the dense pair. If future inputs are not shared, the actual extra payload was 4 bytes per future bin. The end-to-end sender recomputed first-hit mass from the stored causal source population. A boundary LUT reproduced the frozen FP32 answers exactly; direct equation (12) with round-tripped FP32 input differed by at most 7.75e−7 in this panel.

With full demand, median TCP source CPU was .077 s for table lookup, 2.530 s for newly computed killed transitions via the boundary LUT, and 3.934 s for carrying the actual future forcing and evaluating the native boundary anew. End-to-end median wall times were .557 s, 12.140 s and 12.720 s respectively. For the LUT at full demand, median per-request RTT over the three TCP runs was 224 µs, while the median run's p95 summary was 6.05 ms. Shared-host jitter is material (full-demand LUT TCP run range 9.389–13.742 s). Unix times, all raw repetitions and CPU by process are archived. The benchmark replays historical 2-ms slots as fast as the processes run; it does not certify meeting a 2-ms real-time deadline.

Computing the causal states, input drives and frozen reference packets at startup took 2.917 process CPU seconds and 15.202 wall seconds here. Excluding that common state construction, a separate vectorized live generation of every dense published pair took median .135 CPU seconds over five runs and bitwise reproduced the archive; the source propagated 61,020 projected active transitions. Sparse triggering still needs to evaluate or otherwise bound its suppressed values. The archive-replay transport timing alone therefore understates an online sender's end-to-end cost. Live vectorization may be faster than serial on-demand solving even when the latter sends fewer bytes.

For separate context, streaming actual observed spikes as uint32 event times over 29 preidentified trial lanes used 7,276 B, including 29 uint32 lane terminators and 1,790 observed spikes. This product carries retrospective binary events. The probability protocols answer prospective horizon queries, so the two numerical wire sizes do not compare task-matched prediction accuracy or hardware energy.
