# Security invariants

1. Secret bytes are never ordinary return values, receipts, journal fields,
   log fields or persisted lease metadata.
2. A final-use grant is independently signed, single-use, exact-binding,
   short-lived and checked before dispatch.
3. Dynamic issuance persists the provider lease observation before secret
   callback entry.
4. A provider operation with ambiguous outcome is never blindly repeated.
5. Reusing an operation ID with changed semantics is rejected.
6. Revocation/epoch state is monotonic; storage corruption fails closed.
7. Local stores are single-active and owner-private; they are not an
   active-active distributed consensus mechanism.
8. Zeroization applies to application-owned buffers. It is not a claim that
   TLS, HTTP, parser, allocator, kernel or crash-dump layers never held plaintext.
9. The trusted callback remains a privileged boundary. A malicious or buggy
   authorized callback can copy data through side effects; caller enrollment
   must therefore be host-controlled.
10. Secret fingerprints are sensitive metadata. Long-term export of raw
    SHA-256 digests requires retention and entropy review; keyed fingerprints
    are preferred where equality checks do not require public digest identity.
