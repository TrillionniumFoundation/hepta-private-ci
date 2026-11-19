# Actual expandable-allocator calibration failure

Source: `d5f52660f37d3fc46b2cdb17560691cca4ab332d`. Durable desktop job `1a1f0231869-ffbe-712` and original owner terminal status: failed, exit 1, no timeout. Full 3584 positions, 256 selected head positions, eager attention, unchanged 70% CUDA allocation cap, actual expandable segments.

The cold parent load and identity checks completed. The trace records one completed forward and an attempted backward which ran out of memory: 5.03 GiB already allocated, 35.79 MiB reserved but unused, next requested allocation 588 MiB. Thus allocator fragmentation is no longer the sufficient explanation; this actual eager backward exceeds the frozen cap. Zero optimizer updates and zero generations do not mean zero computation. Partial backward work, cold loading and failed allocation are retained costs.

Original owner wall time was 33.84653760999208 s and observed child CPU time 34.108754 s. Model load was 29.905068485008087 s. The three RAPL samples are whole-host CPU package observations including concurrent system activity, not model-only energy. GPU energy, monetary cost, network cost and kernel FLOPs remain unknown. No candidate weights were produced; no B3 task was released or read; all previous NoUpdate decisions remain unchanged.

All JSON, stderr and JSONL below are copied byte for byte. A subsequent SDPA calibration, if run, is a new prospectively frozen engineering candidate and does not relabel this failure or claim identical eager kernel work.
