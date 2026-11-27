# N256 terminal publication intent — HOLD

The #6384 receipt constructor accepts caller-supplied completion facts, but
those facts are not themselves bound to an immutable supervisor terminal
original. This source-only successor closes that interface gap. It requires a
self-hashed terminal observation that cross-binds the exact execution key,
capture session, host, execution request, result manifest, stdout, stderr,
timestamps, exit code, timeout state, and completion state. It then places the
terminal-observation SHA-256 and the validated receipt SHA-256 in one canonical
publication record.

The consolidation audit found that the original persisted-record validator
checked both records independently but did not compare their execution facts.
Rehashing an observation with exit code 7, or changing either record's execution
window and then rehashing the publication, could therefore pass validation
beside a success receipt. The builder's correct copying did not protect the
separate persisted-record validation entry point.

The repaired validator requires identical start time, completion time, exit
code, and completion state before accepting the paired records. The two new
adversarial tests retain valid canonical hashes and exercise both a changed
observation and a substituted receipt. Their four attack cases failed against
the original implementation before the repair.

The original source, request, source freeze, verifier, tests, and workflow from
commit `d40c166e4d8a1f051473afe9ef78981b2a7c3183` are preserved byte for byte in
`qualification/hcsn_terminal_original_d40c166/`. Its `ORIGINAL_FILES.json`
records every original path, Git blob, and SHA-256. The current request and
source freeze identify this repair separately. The historical seven-test CI
artifacts remain unchanged and do not qualify the repaired source.

The bridge does not launch or observe a process, write a receipt, allocate an
execution key, invoke the provider, or perform N256 numerical work. The
checked-in request contains no external original, terminal fact, execution
key, or output. Synthetic fixtures validate only the fail-closed interface.

This stage does not make a future supervisor record authoritative by itself,
grant large-grid qualification, or adopt production. C2 full replay remains
0/6. HPCA remains NoUpdate with external sealed/retention custody and
same-budget benefit open.

Status: **HOLD / NoUpdate / all_closed=false**.
