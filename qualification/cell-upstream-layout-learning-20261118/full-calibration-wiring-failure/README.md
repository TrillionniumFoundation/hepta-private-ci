# Retained full-gate wiring failure

Source 96990368541053f982bec074fda36e5d0ae2f1d7, actual durable job 1a1f04f4906-ffbe-77c: failed/exit1/no timeout. This attempted full-length gate completed one original eager forward and began a backward, then failed allocating 588 MiB with 5.03 GiB already allocated under the unchanged 70% cap. The calibrate entry had omitted configure_training_attention, although the train entry included it. No TRAINING_ENGINE receipt was emitted. This execution did not test full-length inner checkpointing; the precise source omission is retained and corrected in a new isolated root.

Actual owner wall 34.96282131399494 s and child CPU 35.068361 s are additional costs, with zero optimizer updates/generations. The archive includes original FAILED, model load, partial COMPUTE, allocator, owner wait/stdout/stderr and RAPL records. No old source/output was overwritten and the short-A numerical pass remains confined to its actual tested engine. Old SDPA rejection and NoUpdate outcomes remain unchanged.

The new entry installer checks the actual Qwen2 registry function object, frozen function/module SHA, original mask object, all 28 layer configurations and actual forward class. Both calibrate and train invoke it before any forward, and every CUDA chunk repeats the real dispatch check. This source commit is preparation, not a new full-gate pass.
