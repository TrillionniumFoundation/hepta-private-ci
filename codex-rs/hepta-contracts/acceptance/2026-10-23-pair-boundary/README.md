# Original shared registry boundary qualification

Source `6393714e0bf3c619562dd5764273755ec29ddf62`; imported as `52b628420264c35017e4d72ecaaf83f3ae992597`.

Rust 1.96.0, original locked `just test` commands and unchanged deadlines:
23/23 original lease scope passed in 8.542s, then the complete contracts package
227/227 passed in 8.643s with seven existing Root-only ignored tests. This
includes the entry-clock fix; the earlier one-second clock initialization failure
remains in the separate entry-clock qualification. Scoped fix and formatting
passed; no tests were repeated after those steps.

The first pair fixture incorrectly expected global revision 2 after the actual
initial revision 1 and two puts produced revision 3. Its assertion panic prevented
notification of its worker and the original two 60-second timeouts failed. Both
raw attempts are retained. The corrected fixture compares the actual complete
revision and bounds fixture cleanup at two seconds. Production guards and runner
deadlines were unchanged.

The new guards hold the original registry mutex across one bounded local entry.
They require either two live full original records from the same opaque owner or
an exact retired predecessor and a live successor in the same epoch. Callbacks
must not reenter the registry or wait on remote operations. These results provide
no issuer rotation, Root service wire, restart recovery or production authority.

[Manifest and byte hashes](publication.json) covers all eleven original receipt/log
members, including failures. Compressed logs round-trip to their original bytes.
