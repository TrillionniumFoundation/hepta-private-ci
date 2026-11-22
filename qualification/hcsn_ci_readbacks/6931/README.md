# #6931 authentic second-step cursor readback

This evidence-only directory archives the exact original Actions artifact from
the one admitted source execution on Draft PR #6931.

- source head: `7ea84d07b761b0a4b1281afae9fc496a4bffede7`
- source tree: `dd210a1db9174689241ab60bafae7eb33cfd9b42`
- run/job: `44970488761 / 137048976645`
- artifact: `14733074498`
- original ZIP: 591,261 bytes, SHA-256
  `41f938e49dbebd6cdd4580285bed1cff9752b17633eb55a154f01ec34372e8ae`
- lossless publication: three ordered raw parts of 256,000, 256,000, and
  79,261 bytes; the verifier checks every part before concatenation and opens
  the reconstructed original bytes in memory
- 12 members, 1,757,404 uncompressed bytes, CRC clean
- 10 canonical second-step cursor payloads, each embedding the exact canonical
  parent payload and each at `included_index=2`
- original execution: 10 new tail checks and 10 new recurrence row actions
- independent readback: zero tail checks, row actions, numerical kernels,
  provider outputs, Torch calls, or optimizer steps

`HOST.json` records PR merge SHA
`37d8ee40383f7b835e74996a802847f3698c28ad`; the workflow API independently
binds the immutable run to source head
`7ea84d07b761b0a4b1281afae9fc496a4bffede7`. These identities are preserved,
not conflated.

The source PR's generic blocking workflow inherits failures already present on
the exact #6925/#6928 lineage; those failures remain failures. This readback
does not qualify provider completion, arbitrary histories, N256 production use,
C2 full replay, HPCA adoption, or global closure. Status remains HOLD /
`all_closed=false`.

The first evidence commit retained the 591,261-byte ZIP as one Git blob and its
blob-size gate failed against the unchanged 512,000-byte limit. That RED is
preserved. The repair neither allowlists the blob nor changes the limit; it
replaces only the publication representation with the ordered parts above.
