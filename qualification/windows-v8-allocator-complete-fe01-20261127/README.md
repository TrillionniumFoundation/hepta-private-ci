# Complete original Windows V8 gates after the shared allocator repair

The exact fe01 source ran all three original targets without cached test results.
v8-poc, code-mode-runtime and code-mode-host each passed. The original strict
result guard confirms retries=0 and flaky=0. Full raw job output and the complete
artifact are preserved and independently checked by size, digest, ZIP CRC and
every member digest.

The source repair initializes the existing process-wide default array-buffer
allocator under the existing one-time V8 initialization guard. It leaves later
isolates concurrent. Original test functions and assertions, V8 version,
prebuilt archive, sandbox configuration and dependency locks are unchanged.
The original fatal allocator initialization failure remains in the parent
evidence. This closes these three original targets; the complete platform
matrix is an independent gate and is not claimed as passed.
