# N256 symbolic roster result

Status: **PASS_SOURCE_BOUND_SYMBOLIC_ROSTER / HOLD_NO_NUMERICAL_EXECUTION / all_closed=false**.

The one frozen execution `1a1d34ae65f-392-ec` decoded the exact new-export-only N256 bytes from #6256 and independently reconstructed the packet roster without importing the compiler. Both paths agree on 14 capsules, 185 packet tuples, 625 coordinate spans, 18,225,028 FP64 coordinates, a 3,444,164-coordinate largest capsule, and coordinate identity `e289c20d6595cb6d92dd3e2585bc7cb40fb0d5a408725c5edc14a9fb7f328fe2`.

The execution performed 0 spatial operators, 0 dynamic propagations, 0 matrix exponentials, 0 numerical oracle calls, 0 Torch/backward calls, 0 optimizer steps and 0 training steps. It does not recover missing historical N256 bytes, transfer any N128 qualification, or qualify N256 dynamics, serializer/full-state recovery, cross-runtime exactness, N512, finite-domain behavior, fullnetwork training, asynchronous cost, HPCA benefit, or production adoption. Existing negative and UNKNOWN records remain unchanged.
