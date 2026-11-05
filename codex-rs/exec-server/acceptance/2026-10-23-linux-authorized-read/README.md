# Linux authorized-read complete chain

Source f3ee06d59275582cdcccfdec44bab96e57db6a49 first added the verified Linux
handle path and fixed original remote error mapping; its original owner510/510
passed. Review then found read-open before authority/regular-file validation.
Source44b4820a43ee9a34d4c0fddb7762e94fed59a9b1 replaced the initial path open
with O_PATH; its focused25/owner511 passed independently. Final source
`a47dcc783fdb6c7deae6bc23bb83354a0052f5e6` also uses O_PATH with strict openat2
flags for the physical path. Only that internally held, already-proved regular
file descriptor is converted to readable via its kernel proc link and verified
again. The caller's path is never read-opened as a fallback. The original pin
remains alive through final admission, preventing inode ABA.

Final complete-chain original tests: focused26/26 and owner512/512, zero retries,
three original skipped cases, 56.272s execution on Linux7.0/Rust1.95. Original
permission, path replacement, hardlink/deletion, error redaction and RPC assertions
remain. Original permission wire code stays -32600; only bounded-read overflow
uses the fixed method-specific -32012. Capability probing directly verifies both
kernel link flags, physical identity and an actual private regular-file read.

Scoped fix and fmt passed. The final posttest change is formatting of one test
tuple; its exact diff is retained and no tests ran after the style phase. Earlier
semantic failures and intermediate source qualifications remain in the
[original receipt/log/source-diff manifest](publication.json).
This is no Darwin atomic equivalence, actual namespace-switch, native Asterinas
or final composed Rust1.96 full workspace qualification. Missing primitives
still advertise false and return Unsupported.
