# Security invariants

1. Raw secret values are not ordinary API return values, receipts, logs or
   learning/export records.
2. Provider lease identifiers remain opaque host handles; public status uses
   digests.
3. Final-use grants are independently signed, exact-binding, short-lived and
   single-use.
4. A provider effect with ambiguous outcome is never blindly replayed.
5. Known issued handles are durably registered before dynamic secret callback
   entry.
6. Corrupt or missing initialized authority state fails closed.
7. Local stores are not represented as active-active consensus storage.
8. Zeroization covers application-owned buffers; it does not imply TLS, HTTP,
   allocator, kernel or crash-dump layers never held plaintext.
9. The trusted callback is a privileged boundary and must be host-enrolled.
10. Secret/lease fingerprints are sensitive metadata. Long-term export of raw
    SHA-256 digests requires retention and low-entropy enumeration review; use a
    keyed fingerprint when public digest interoperability is unnecessary.
