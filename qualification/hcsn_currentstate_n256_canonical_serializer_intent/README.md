# N256 canonical serializer source intent

Status: **PASS_SMALL_STDLIB_SOURCE_HOLD_N256 / HOLD / all_closed=false**.

This successor to Draft #6300 freezes a canonical byte format and fail-closed cold loader for full current state: exact source/input bindings, ordered little-endian FP64 blocks, generation-tagged packet metadata, packet alphas/operators, a SHA-256 trailer, strict bounds, no trailing bytes, byte-identical decode/re-encode, and atomic publish with directory fsync.

Four stdlib-only small fixtures exercise byte determinism, full roundtrip, corruption rejection, and pre-read admission rejection. They execute no N256 dynamics, matrix actions, candidate/oracle numerics, N256 serialization, Torch, or optimizer. The proposed 192 MiB packet ceiling is only a value bound into the future admission; Draft #6295's 128 MiB RED remains unchanged and no allocation is implied.

This closes only canonical serializer/cold-loader **source plus small-fixture controls**. Actual N256 packet size, full-state bytes, candidate/oracle agreement, cold restart, resource admission, arbitrary histories, third or later cycles, large-grid qualification, C2 full replay, HPCA custody/benefit, and production adoption remain OPEN.
