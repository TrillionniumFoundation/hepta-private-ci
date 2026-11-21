# #6927 authentic first-step cursor readback

This evidence-only directory archives the exact original Actions artifact from
the one admitted source execution on Draft PR #6927.

- source head: `f84746057e63e20f4650d6048f4739d047442d62`
- source tree: `2ded9eb8177f7521cbdce541757db4babb61f818`
- run/job: `44963287745 / 137026614929`
- artifact: `14730452595`
- original ZIP: 304,400 bytes, SHA-256
  `c82b34925f80ceb724bc9bf45d2097f07bc4a2a1b05ee0cb374421984082dc61`
- 12 members, 859,801 uncompressed bytes, CRC clean
- 10 canonical cursor payloads, all body digests valid and all at
  `included_index=1`
- original execution: 10 tail checks and 10 recurrence row actions
- independent readback: zero tail checks, row actions, numerical kernels,
  provider outputs, Torch calls, or optimizer steps

`HOST.json` records PR merge SHA
`d85826827b0e45c533b7a0b9b50c62e824033765`; the workflow API independently
binds the immutable run to source head
`f84746057e63e20f4650d6048f4739d047442d62`. These identities are preserved,
not conflated.

The unrelated historical push workflow run `44963269068` ended failure with
zero jobs; its cause remains UNKNOWN and it is not counted as this candidate's
success. #6901, #6908, #6913, and #6924 negative/UNKNOWN records remain intact.

This readback does not qualify provider completion, arbitrary mid-recurrence
resume, N256 production use, C2 full replay, HPCA adoption, or global closure.
Status remains HOLD / `all_closed=false`.
