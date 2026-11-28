# Original-cache binary network: first registered observation

## Result

All nine fixed parents passed at source `1149fa3a5aea9da81030d9c70ab42e9625fa31b8`,
after protocol `93a854807b5883b9bac987498977f81277d9081a` and binary peer #7206.
Every one of the 36 spawned child processes exited 0 without forced cleanup.
Each complete candidate equaled its previously sealed #7200 object. Maximum
error against the original full solution was 6.179154410368426e-12, under the
unchanged rtol=atol=1e-7. The coordinator did not give children reference weights.

| Parent | Charged seconds | Maximum original-full weight error |
| --- | ---: | ---: |
| n8-s17011 | 0.464982 | 1.836878e-12 |
| n8-s27011 | 0.258854 | 1.164513e-12 |
| n8-s37011 | 0.353667 | 1.480926e-12 |
| n32-s17011 | 1.145013 | 3.622880e-12 |
| n32-s27011 | 1.136182 | 4.488798e-12 |
| n32-s37011 | 0.950895 | 4.561851e-12 |
| n64-s17011 | 3.630495 | 5.407216e-12 |
| n64-s27011 | 3.507912 | 6.179154e-12 |
| n64-s37011 | 3.319808 | 6.021905e-12 |

## Actual transport observations

The raw frame/socket meter observed 19,911,408 bytes in completed `sendall`
calls and the same 19,911,408 bytes actually returned by `recv`, including
outer frame headers. There were 108 sent/received offer frames, 323 completed
rounds, and zero unknown deliveries, refusals or failed sends.
Against #7203's earlier 89,544,158 JSON stream bytes, this observation used
77.7635878825% fewer bytes (ratio 0.222364121175). The offer count is unchanged;
inventory polling rounds differ (323 versus 285) with process scheduling.

The runner took 14.774321121 seconds; its outer supervisor observed
15.106265978 seconds, versus the previous JSON observation's 14.800391568.
Observed child user/system CPU was 39.897788/4.387702 seconds. These unpaired
walls do not establish latency or training acceleration. Each parent's charge
remained below 60 seconds and the cumulative new-scope charge below 600 seconds.

## Evidence and boundaries

`DEPENDENCIES.json` pins all unchanged source dependencies and the 63-file
input inventory. The original inputs remain in #7200's published archive,
SHA-256 `f82a4f8d93ee940dff82c2c06a5c9492348bf6f589ae594d538aa40d42f79b28`.
`attempt-1.tar.gz` retains the first raw log, full child/candidate/round records,
all executed source, supervisor, frozen protocol/input inventory, budget,
format record and file inventory. Its 174 files omit only
36 post-run SQLite databases, whose hashes remain inventoried and local bytes
retained. Archive: 584,905 bytes; SHA-256 `3545705b1faf51f17bc35e6b3d2119d87e14a461767dad544b5093f7313d9bef`.
Official `just fmt` and Ruff 0.15.13 completed afterward; the runner's AST is
unchanged. No experiment was repeated after formatting.

This POSIX/Linux research adapter reuses the original worker and coordinator;
it changes neither the old JSON Meter nor the ledger/peer state machine.
The loopback experiment establishes transport compatibility and observed byte
reduction. It does not establish authentic sources, real-user adoption, learned
topology, generalization, native settlement or useful-work credit. No new
scientific training budget, optimizer step, DEV/final data or user trace was used.
