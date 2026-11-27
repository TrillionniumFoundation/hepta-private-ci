# Windows ACL setup error provenance

The actual Windows job on `804ac018433ff08dfd195e93eed936394baf5053`
rejected ACL setup before spawning the marker process. Its root cause was the
native I/O error `ERROR_ACCESS_DENIED` (5). The assertion still expected the
removed pathname setter's hand-written error text; the retained-handle installer
now needs `WRITE_DAC` while opening the target. That assertion then poisoned
the process-test mutex and prevented five following cases from reaching their
behavior assertions.

The fixture now requires the exact root error type, `PermissionDenied` kind,
and native code 5, together with the unchanged outer path context and absent
process marker. The native denial preconditions, cleanup guard, actual spawn
API, and mutex behavior remain unchanged. No error is accepted merely because
its message contains a word, and no test is skipped.

Rust formatting succeeded locally. A later full-range whitespace check
identified the original log's CRLF line endings; `original-native-excerpt.zip`
now preserves those exact bytes and the recorded excerpt hash. Windows
execution is pending the new native source head. This fixture correction does not repair
the separate outside-root deletion failure. The raw excerpt and the original
full decoded log hash are recorded in `receipt.json`.

[Original native job](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45458387224/job/138713957842)
