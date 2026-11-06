# Architecture source-head checkpoint

This packet retains the complete original source-head job log, its complete GitHub artifact ZIP, API snapshots and the independent artifact audit for PR #5083. The exact source is `8c9fdbb144cf1719a0ffa148e463a024b1cb6043`, tree `9bb1dffb70213d288a670b6e7b3598745384f121`. Run `42248854689`, job `127998199908`, succeeded on `ubuntu-24.04-arm`.

All 65 ZIP members were checked for CRC, SHA-256 and complete inventory. Each of the 31 command records also appears unchanged in the original console, with matching raw-log identities and clean before/after source. The 26 native Rust commands report 495 passing framework executions. Four Python groups report 130 passing executions; the derived-view check has no test count. These are execution counts across commands, not a unique-case total. Original ignored and filtered cases remain visible per command; internal early-return behavior was not separately audited. The bounded inference history test was actually run by its explicit ignored-test command.

The base-merge lane skipped native execution and is not counted a second time. Architecture required job `128048016137` was still queued at the 2026-11-06 17:44:52 UTC snapshot. This packet does not qualify the latest product composition, Windows, the vodozemac update or the separate port migration.

Run `python restore.py /absolute/path/to/new-empty-directory` to restore the listed original evidence. The previously reviewed bounded reader differs only by its fixed INDEX hash. It verifies the index, independent gzip members, complete compressed archive and every regular file before writing; it refuses an existing destination. Restored files are inert 0644 evidence. It does not execute archived code or install anything. Each published compressed blob is at most 450000 bytes.

The original artifact ID is `13524644917`, ZIP SHA-256 `1311a413e5f82eef4287991b891929f7ccaeec5bc24a882630fe0f93e79950d4`. The advisory candidate transport observation remains unknown; its HTTP status does not establish a write-denial or administration guarantee.
