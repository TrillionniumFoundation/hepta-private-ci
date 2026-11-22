# #6936 authentic N256 checkpoint-profile readback

This evidence-only directory preserves the exact original Actions artifact from
the sole admitted execution on Draft #6936.  The 7,773,162-byte ZIP is split
into 31 ordered Git blobs solely to remain below the repository blob gate.
Concatenating `ORIGINAL.zip.part000` through `part030` reproduces SHA-256
`e1775ee832acc431282bcca9b7b5f0e21b38ac5a0f3ac46c2228f787c0e8a0a8`.

- source head: `607cb0f8b9dab6229f0ddc7ec982e8e67f0b52f2`
- source tree: `befea4f0ba8205d3d62a550f25cddba921977a04`
- run/job: `44984290966 / 137091352623`
- artifact: `14738898424`
- 42 members, 17,714,084 uncompressed bytes, CRC clean
- 40 canonical checkpoint payloads: ten each at indices 4, 8, 16, and 32
- 17,701,673 total cursor bytes
- source work: 50 index-two relation recomputations, 300 warm and 520 cold
  replay row actions; 870 total
- source cost: 14.471160832 wall seconds, 14.468973798 CPU seconds, and
  32,676 KiB maximum RSS
- zero tail checks, provider outputs, dynamic steps, exponential actions,
  Torch calls, or optimizer steps

The independent verifier performs zero numerical work.  It reconstructs and
checks the exact ZIP and every split part, checks every checkpoint's canonical
envelope/body digest and archived source/parent binding, and replays no row
action or tail test.

`HOST.json` records pull-request merge SHA
`231515abc90265dfefa40f0d3c707ab5b899a014`; the workflow API separately binds
the immutable run to source head `607cb0f8b9dab6229f0ddc7ec982e8e67f0b52f2`.
These identities are preserved rather than conflated.

This closes only the bounded authentic index-32 checkpoint/profile original.
It is not a tail/unique-rounding result, provider completion,
arbitrary-history proof, resource admission, N256 qualification, C2 full
replay, HPCA adoption, or production adoption.  Historical RED/UNKNOWN remain
unchanged and global status remains HOLD / `all_closed=false`.
