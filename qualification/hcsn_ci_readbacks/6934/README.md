# #6934 authentic detached-cursor readback

This evidence-only directory archives the exact original Actions artifact from
the one admitted source execution on Draft PR #6934.

- source head: `7937875d6fcb38ac97c74a9ca5feef882c16c10f`
- source tree: `4aec24eaea1b606d8e7227d21f19d9a34e150699`
- run/job: `44983286104 / 137088272720`
- artifact: `14739225051`
- original ZIP: 287,707 bytes, SHA-256
  `5d745460761940b86add99436bcbf953a8c0111d4d97c49ba9d18db7c2b52444`
- 12 members, 858,591 uncompressed bytes, CRC clean
- 10 canonical detached cursor payloads at `included_index=2`
- payload range: 83,968–85,821 bytes
- exact total payload reduction relative to the archived source cursors:
  900,489 bytes (1,752,317 to 851,828 bytes)
- source execution: 20 exact row-action relation recomputations, zero
  recurrence advancement row actions, tail checks, or provider outputs
- independent readback: zero row actions, tail checks, numerical kernels,
  provider outputs, Torch calls, or optimizer steps

`HOST.json` records PR merge SHA
`8ad3b1d9c48fd99351c5bf84c53ee494756f9bfa`; the workflow API independently
binds the immutable run to source head
`7937875d6fcb38ac97c74a9ca5feef882c16c10f`. These identities are preserved,
not conflated.

The verifier reconstructs the exact #6931 source ZIP from the three immutable
#6932 raw parts. It checks every source and detached envelope, body digest,
parent digest, state field, byte count, and recorded cost without importing or
executing the numerical source.

This readback does not advance the recurrence, establish arbitrary histories,
complete the provider, qualify N256, close the resource gate, authorize C2
full replay or HPCA adoption, or change global HOLD / `all_closed=false`.
