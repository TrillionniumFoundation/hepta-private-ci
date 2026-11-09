# Engineering execution history collector

`collect_execution_history.py` retains completed local engineering attempts with
their exact original receipts and hash-bound logs. It preserves rejected and
failed attempts alongside successes, and keeps differing source identities and
overlapping recorded wall intervals separate. It does not establish S0–S5
qualification or a final-candidate pass.

## Run

Use Python 3.10 or newer on a Unix host. No third-party packages are required.

```sh
python3 -B qualification/cell_common_candidate/tools/collect_execution_history.py \
  --records-root /path/to/original-records \
  --output-dir /path/to/original-records/history-checkpoint/capture-002 \
  --exclude-subtree history-checkpoint \
  --require-receipt baseline-terminal-tests.json \
  --require-receipt terminal-native-v1.json \
  --require-receipt terminal-original-host-cas-v2.json \
  --require-receipt common-core-v1.json
```

The output directory must be new. Repeated captures use a new directory; earlier
receipts, logs and archives are never overwritten. The exact output subtree is
excluded automatically; sibling history is still scanned. Explicitly excluding
a reserved `history-checkpoint` subtree, as above, also excludes prior outputs.
All excluded subtree names are retained in the manifest.

An explicit `--external-pair /other/root/receipt.json /other/root/command.log`
admits only those absolute sibling paths under a separate no-follow reader and
archive namespace. It never allows an ordinary receipt to escape its root. If the
old completed receipt has no recorded log hash, the association remains an
explicitly paired supplement: `receipt_log_hash_verified=false`. The current
observed stable hash is retained without inserting a hash into the original
receipt or claiming that the receipt authenticated it. External pairs are
automatically required; missing or unstable pairs make the capture incomplete.

Outputs are `execution-history.json` and `execution-evidence.tar.gz`. Archive
members use `original/<relative record path>` and retain exact file bytes with
inert normalized archive metadata. The manifest records original file identity,
size and SHA-256, plus the archive SHA-256. Nothing in the archive is executed.

## Admission and exclusions

The collector accepts terminal `hepta_ci_exec` records with their named log and
recorded log SHA-256. A rejected preflight with no dispatched command is retained
without inventing a log or a command exit code. It also understands the completed
workflow container and retained-result comparison records used by this campaign,
and completed legacy records carrying `argv`, `cwd`, `head`, `finished_utc`,
`exit_code` and a hash-bound sibling `.log`.

Every input component is opened with no-follow semantics. Log and comparison
attachments must match their receipt's SHA-256. Two reads, separated by a short
configurable settling interval, must have identical bytes and file identity.
Changing evidence discards its entire dependent event. Running or malformed
receipts, bad hashes, missing files and unsafe paths appear in `excluded`.
Unreferenced logs are listed as completion/binding unknown and are not archived.
In particular, a quiet log is not proof that its Cargo/Bazel process completed.
Unrecognized helper manifests and unbound `.jsonl`/`.log` files are listed, not
silently called complete raw execution evidence. A wrapper log may omit a nested
compiler's separate stdout/stderr; those need their own completed hash bindings.

These are unsigned local records, not independently authenticated evidence.
Terminal state and matching stable bytes are the completion guard; this helper
does not claim a global proof about every process on the machine. Historical
source identities are retained as recorded, not reverified against today's
checkout. Invalid SHA shapes, inconsistent declared/observed identities and
conflicting cleanliness claims retain the event with partial/unknown source
scope. Missing start/end times stay unknown rather than being inferred from
file timestamps or another attempt.

`--require-receipt` makes omissions explicit. Missing required receipts or an
empty capture return exit code 2 while preserving the partial capture for review.
A successful collector exit only means an archive was made with its requested
records. The collector does not assign research stage states; original gate
records remain the source of those states.

## Cost and scope

Individual reported elapsed times are command/wrapper wall times. They may include
compilation, tests, waits or nested commands. Container receipts are labeled so
they are not additional tests. No wall sum is produced, and no CPU, learning,
physical-resource or full historical cost is inferred. `physical_cost` and
`full_history_cost` remain null; `full_history_cost_known`,
`complete_execution_history` and `final_candidate_pass` remain false.

## Helper verification

```sh
python3 -B -m unittest discover \
  -s qualification/cell_common_candidate/tools \
  -p test_collect_execution_history.py -v
```

These regression tests check evidence collection behavior with fixtures. They
are not production learning, recovery, performance or stage qualification tests.
