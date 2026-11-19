# N256 streaming full-state static result

Status: **PASS_STREAM_STORAGE_HOLD_DYNAMIC / HOLD_NO_NUMERICAL_EXECUTION / all_closed=false**.

The exact 18,225,028-coordinate denominator is unchanged. A canonical structured
candidate container is 2,716,636 bytes; the largest candidate capsule payload is
415,596 bytes. The independent oracle coordinate stream is 145,800,224 bytes in
279 fixed 524,288-byte frames. Including a 1 MiB evidence reserve, the planned
preserved total is 149,578,828 bytes and the two compare buffers total 1,048,576
bytes. These representation bounds fit the retained 8 MiB per-buffer,
201,326,592-byte cumulative, and 256 MiB archive caps without changing them.

This closes only static storage/comparator arithmetic. No N256 dynamics,
matrix exponential, numerical oracle, serializer/cold-loader execution, Torch,
optimizer, or training occurred. The original #6295
`RED_RESOURCE_CAP_HOLD` remains intact. N256 candidate/oracle implementation,
expm workspace and RSS, durable host and ancestor-cgroup allocation,
concurrency/calendar, and actual warm/cold byte equality remain open.

Attempt001 is retained as a real pre-entry RED: GNU `/usr/bin/time` rejected
the macOS-only `-l` option with exit 125 before Python entry. Attempt002 changed
only the timer flag to `-v` under the separately frozen key.
