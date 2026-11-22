# Authentic N256 index-256 parallel resource amendment

This is a separately frozen successor to the terminal `RED_TIMEOUT` in #6942.
It does not rerun that key or refund its roughly 30 minutes of consumed hosted
wall time. Ten fixed lane jobs retain the same exact replay, warm/cold byte
equality, 8 MiB cursor cap, and 64 MiB aggregate cap. Each lane has one admitted
attempt, a 115-minute command limit inside a 120-minute finite job budget, and
an `always()`-uploaded progress journal. The five-minute reserve is solely for
publishing the interruption record; it does not extend computation.

The collector succeeds only with all ten authentic lane originals and unchanged
caps. Any timeout, missing original, digest mismatch, or cap breach remains RED.
Even success is a bounded resource profile before the first possible tail check
at index 537; it is not N256 qualification, provider completion, arbitrary-history
resume, C2 full replay, HPCA custody, or production adoption.
