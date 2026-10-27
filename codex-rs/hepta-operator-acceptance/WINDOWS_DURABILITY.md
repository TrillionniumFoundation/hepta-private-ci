# Operator Windows artifact development and technical contract

The `durable` module selects `durable_windows_artifacts` on Windows and the
existing Unix implementation elsewhere. Windows delegates every artifact
read/hash, private write/replace, directory check and sidecar lock to the single
`codex-utils-path` retained private-artifact backend. `durable_windows` keeps the
original immutable-handle mutation regressions using that same complete identity
predicate. It does not supply a second privacy check or a 64-bit identity.

The caller must bootstrap a genuinely new private root, or provide an existing
root that passes the backend unchanged. Test fixtures use the production
exclusive private-root constructor; no existing ACL is repaired. A normal
public temporary root is not silently admitted. The lock is a retained private
file with native sharing exclusion; a read-only verification requires its
existing file and never creates one.

Run the original declared Operator Windows 26-case scope through the repository
`just test` entrypoint. Keep its identities, limits and assertions unchanged.
Shared backend native controls are a separate scope; they cannot convert a
failed original functional case into a pass. Cross compilation only checks the
platform-specific types. The original inherited-SSHSIG failure remains separate:
this filesystem work does not grant inherited signer/body ownership or remove
the required strict-plus-OpenSSH double verification.

See [canonical API, callers and evidence](../utils/path-utils/PRIVATE_ARTIFACTS_WINDOWS.md)
and [SSHSIG contract](SSHSIG_NATIVE.md). Receipt formats, identity, signer policy,
nonce/replay and acknowledged-history rules are unchanged; a failed partial
write cannot be silently replayed or acknowledged as successful.

The separate `hepta-windows-signature-trace` diagnostic runs two ignored
collectors using the unchanged original trust/G5 fixture generation and original
production verification calls. It records same-held-object full 128-bit file ID,
owner/DACL, effective token user/owner, canonical admission errors, and the actual
OpenSSH fixture executable. It never reads private-key contents or changes an
existing ACL. Original functional cases and their criteria remain unchanged.
`COLLECTED_DIAGNOSTIC_ONLY` means both observations are complete and source/tool
identities stayed fixed; an observed private-identity or SSHSIG refusal remains
a functional failure. This trace does not qualify Windows inherited input or
the original 26-case scope. Keep the original 91-case driver and scope bytes.
