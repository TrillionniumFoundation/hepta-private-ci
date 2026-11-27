# Corrupt database error path fixture

The actual 97ab macOS Intel and ARM test artifacts each preserve three failures
of `embedded_state_db_corruption_preserves_failed_database_for_cli_recovery`.
The typed corruption error names the database opened through `/private/var/...`;
the test expected its original `/var/...` alias.

The fixture still passes the original configured SQLite alias and writes the
same corrupt bytes. It computes the expected path from that existing test file
before initialization, then uses the same `AbsolutePathBuf` conversion as
StateRuntime so Windows verbatim prefixes follow the same normalization. The
complete typed-error downcast and fatal SQLite-corruption assertion
remain unchanged. Production runtime, path validation and error construction
are unchanged. No deadlines, retries or skips change.

This is separate from the production metadata-association defect under review.
It does not normalize the input fixture to conceal that defect. The patch was
formatted and source-reviewed; native execution is pending.
