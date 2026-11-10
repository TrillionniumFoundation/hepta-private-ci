# Original cargo-deny diagnostic evidence

The exact original ZIP was downloaded from artifact `13745581832` after native
Windows capture run `42779904306`, job `129707151554`, source
`139e27d2fbff70a0f5bb808aa506c09e9924f611`. It contains the original failed job
`129677997786` in run `42770804390`, whose metadata head is
`38069398cef4372c8e189545970f9fe2e6c24ae2`.

`original-cargo-deny-129677997786.zip` is exactly 1,738,610 bytes, SHA256
`f34aa002b006c36131417fc5baf5d0bdd4355ca56b605bb9520a22650dfba956`.
Its `original-job.log` member is exactly 19,821,541 bytes, SHA256
`b1f3d61e67000b7dfedc0dcb0a2cb93e7989447e2a0be09ecd782b6f0f49ea73`.
All recorded member sizes and hashes were independently verified. The ZIP retains
the original job/run JSON, capture RESULT and STARTED marker. The separate
`capture-result.json` is an exact byte copy of the original ZIP RESULT member.

`error-index.json` is a derived index: ANSI colour sequences are removed for
readability, line numbers refer to the decoded original log, and each prefix is
bounded to 1,600 characters. The full unchanged original remains inside the ZIP.
Exactly six fatal error blocks occur in this original log:

| Dependency | Reported advisory |
| --- | --- |
| libsqlite3-sys 0.37.0 | RUSTSEC-2026-0459 |
| pin-utils 0.1.1 | RUSTSEC-2026-0441, unmaintained |
| rmcp 3.1.3 | RUSTSEC-2026-0457, RUSTSEC-2026-0461, RUSTSEC-2026-0462 |
| vodozemac 0.10.0 | RUSTSEC-2026-0451 |

Only diagnostic acquisition is CLOSED. Dependency remediation and same-source
cargo-deny acceptance remain OPEN. This evidence changes no dependency, advisory
ignore, gate, image or production authority. Scientific admission HOLD; authority
NONE. MANIFEST.json binds all delivered files except itself.
