# Original report reconstruction

The original `citation_stream_parser.json` and `proposed_plan_parser.json` reports exceed the repository's 512,000-byte blob limit. Their complete original bytes are retained in UTF-8 parts, split at line boundaries. `large-reports-parts.json` binds each original logical filename, full length, SHA256, Git blob, source path and every ordered part. `checkpoint.json` retains the original report identities and adds their storage mapping.

Reconstruct both reports into a new independent directory:

```sh
python3 reconstruct_reports.py --output-directory /absolute/new/location/native38-reports
```

The command verifies every part and each complete report and refuses an existing output directory. The original reports and the failed blob-size check remain in parent commit history. The spelling checker still checks all JSON fragments and text files.
