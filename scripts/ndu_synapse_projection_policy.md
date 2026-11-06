# Native Synapse diagnostic view

The ARM qualification retains its full original artifact and additionally exports
a bounded view for inspecting command output and qualification receipts. The view
does not determine whether the business qualification passed. It cannot restore
the entire original artifact.

## Selection

The view applies the existing collector's recursive suffix rule: `.json`,
`.jsonl`, `.stdout`, `.stderr`, `.log`, `.xml`, and `.txt`. It excludes these four
explicit directory prefixes relative to the original qualification directory:

| Prefix                              | Reason for exclusion from this additional view |
| ----------------------------------- | ---------------------------------------------- |
| `preparation/prefetch/cargo-home/`  | Original dependency inputs and Cargo cache     |
| `qualification/build/cargo-home/`   | Copied dependency inputs and Cargo cache       |
| `qualification/build/cold-test/`    | Cargo test build output and cache              |
| `qualification/build/cold-product/` | Cargo product build output and cache           |

The prefixes also contain compiler metadata and may contain diagnostic output.
Excluding them narrows the view. It does not declare those files irrelevant or
claim that every diagnostic from the original artifact is present. New command
paths outside these prefixes are selected by suffix without a name whitelist.

The original full artifact upload, retention settings and failure logs remain
unchanged. The upload is attempted after this export even when the view fails;
its actual success and artifact identity require separate verification.
The view records the workflow run, attempt and expected full artifact name.
Its later artifact ID, ZIP size and official digest must be retrieved from the
artifact API; they are not invented before the upload exists.

## Bounds and custody

`ndu_synapse_projection.py` checks the original collector's fixed SHA256 and calls
that implementation unchanged. The view retains its limits of 5,000 selected
files, 1,024 bytes per relative path and eight parts of at most 128 MiB each.
Tar headers count toward the part limit. Exceeding any limit is a failure.

`SOURCE_DIRECTORY.json` lists every observed file or other non-directory entry
using its relative path, file type and mode, size and selection category. It
records excluded entries without following file links or reading their content.
Directory links are rejected. This separate metadata catalogue has an additional
limit of 200,000 entries and 64 MiB of serialized JSON. The catalogue bounds do
not replace or increase the collector's limits. A traversal error is a failure;
an unreadable subtree cannot silently disappear from the catalogue.

Each selected entry must be a regular file. The wrapper opens it through directory
descriptors without following links, checks its identity before and after reading,
and records its original SHA256, size and CRC32. It copies the selected bytes to
a temporary view outside the original directory, calls the unchanged collector,
then checks the original bytes and full directory inventory again. It does not
change the original source files. The collector writes tar member mode `0600`;
an independent reader may restore inert evidence with mode `0644` and must disclose
that representation difference.

CRC32 values in `PROJECTION.json` describe the selected original file bytes.
They are not CRC verification of a future ZIP or of the excluded members. For
an independently downloaded artifact, verify its actual ZIP identity and member
CRCs separately before making claims about that archive.

## Interpreting success and failure

A complete view requires both `PROJECTION.json.complete_projection` and
`DIAGNOSTICS.json.complete` to be true. Check the projection's identities for
`SOURCE_DIRECTORY.json` and `DIAGNOSTICS.json`, every ordered part size and SHA256,
the concatenated tar SHA256, and the exact member set and member identities.
The selected members in both receipts must agree. A true collector flag alone
does not override a failed wrapper check after packing.

The wrapper requires a matching source commit in every available `CI_STARTED.json`
and `CI_RESULT.json`, and at least one of those receipts. This binds the view to
the expected producer source. The producer's existing full source and lock
verification remains a separate requirement.

On failure, the wrapper leaves `complete_projection` false. Existing partial
collector output remains available for diagnosis. Uploading such output does not
turn it into a complete view. Neither receipt grants qualification or promotion,
and neither substitutes for successful native business tests.

The original collector has no credential scanner. This same-repository export
uses its existing private artifact destination; it adds no scanner exemption and
makes no claim that the output was scanned. Unknown wrapper exceptions record
their type without copying external exception text into the new receipt.
