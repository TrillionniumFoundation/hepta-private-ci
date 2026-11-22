# #6944 authentic N256 index256 parallel readback

This evidence-only directory preserves the exact combined Actions artifact from
the sole admitted execution on Draft #6944. The 20,395,989-byte ZIP is split
into 41 ordered Git blobs solely to remain below the repository blob gate.
Concatenating `ORIGINAL.zip.part000` through `part040` reproduces SHA-256
`452060c65949e9c1d8ffe74e4303d707e6fe4fe7c2e75e29caacfa3137c37a91`.

- source head: `2ce228cc1ae7719f4d8253e3f40a340e5f7807b5`
- source tree: `62049b4d8ece72addb3960b4599d485984335af6`
- run/collector job: `44993006709 / 137119005804`
- combined artifact: `14743205374`
- 31 members, 62,931,009 uncompressed bytes, CRC clean
- ten canonical index256 checkpoint payloads, one per fixed lane
- 62,877,713 total cursor bytes; 4,231,151 bytes remain below the 64 MiB cap
- every checkpoint is below the 8 MiB per-cursor cap
- source work: 20 relation recomputations, 600 index32 replay rows, 1,920
  index128 replay rows, 1,280 warm extension rows, and 1,280 cold extension
  rows; 5,080 total
- source cost across ten parallel lanes: 1,926.32371919 summed wall seconds,
  1,923.892242355 summed CPU seconds, and 73,392 KiB maximum RSS
- zero tail checks, provider outputs, dynamic steps, exponential actions,
  Torch calls, or optimizer steps

The independent verifier performs zero numerical recurrence. It reconstructs
and checks the exact ZIP and every split part; validates CRC, member and byte
ledgers; validates every canonical checkpoint envelope/body digest, lane
result, source/parent digest shape, progress record, cost and work ledger; and
does not import or call the HCSN model.

The host payload records pull-request merge SHA
`da413c0549eb416677190c9028df9542fc520957`; the workflow API separately binds
the immutable run to source head `2ce228cc1ae7719f4d8253e3f40a340e5f7807b5`.
These identities are preserved rather than conflated.

This closes only the bounded authentic index256 checkpoint resource profile.
It is not a tail or unique-rounding result, provider completion,
arbitrary-history proof, N256 qualification, C2 full replay, HPCA adoption, or
production adoption. #6939 remains RED, #6942 remains RED_TIMEOUT with completed
row actions UNKNOWN, the #6901 cause remains UNKNOWN, and global status remains
HOLD / `all_closed=false`.
