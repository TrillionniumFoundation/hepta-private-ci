# Explicit completion of an original Root frontier initialization

`HostAuthorityFrontierStore` retains the original Root directory checks,
publication lock, record format, owner validation, bounded complete decoding,
file and directory synchronization, and durable readback. Its ordinary
`initialize`, `open`, `load` and compare-and-set methods keep their previous
behavior.

The initialization sibling adds two explicit administration operations. They
are not selected implicitly after an ordinary open error.

## Exact initial value

```rust,ignore
HostAuthorityFrontierStore::resume_initialization(root, owner_id, initial)
```

This method holds the original publication lock throughout the decision and
complete readback. The caller must separately authorize the original bootstrap
value. The method does not turn a failed runtime read into a fresh frontier.

| Actual original publication entries | Action |
| --- | --- |
| Canonical record exists and its complete durably read value equals `initial` | Return the same original store. Preserve any unpublished candidate. |
| Canonical record exists with another value or invalid encoding/metadata | Refuse. Do not replace it with genesis. |
| Canonical record is absent and a complete, correctly owned `.next` equals `initial` | Synchronize the same candidate and its name, publish with `RENAME_NOREPLACE`, synchronize the directory and perform original complete readback. |
| Canonical record is absent but `.next` is partial, malformed, incorrectly owned, or has another value | Refuse and retain the evidence. Never truncate that candidate. |
| Both entries are absent | Perform the original initial publication and complete readback. |

All candidate validation uses the original bounded record decoder. The change
extracts its unchanged body into `read_opened_record` so canonical and candidate
records use the same schema and owner checks. The candidate is opened without
following symlinks and with nonblocking file opening before regular-file
validation. Existing canonical runtime reads keep their original path.

`initial` must be a known original, separately authorized value. A lost clock
record must not be reconstructed using a new clock sample. A later lease state
must use the full-frontier recovery described in
[LEASE_INITIALIZATION_RECOVERY.md](LEASE_INITIALIZATION_RECOVERY.md), rather than
being treated as genesis. The issuer caller uses the exact original unused
state: the retained signer and policies, epoch 1, revision 1, sequence 0 and no
writer authorization.

## Locked observation of absence

```rust,ignore
HostAuthorityFrontierStore::<OriginalRecord>::with_absent_initialization(
    root,
    owner_id,
    || original_owner_operation(),
)
```

The method acquires the original publication lock and checks that neither the
canonical entry nor `.next` exists. Any entry, including a malformed file or a
directory, prevents the callback. After the callback it checks both names
again. It does not publish a value or return a new store.

The callback's result is an inner value. If it returns an error value, the
postcondition still runs. An entry appearing during the callback yields an
outer `Unavailable`; a caller must not report a successful absence observation
after an uncertain external mutation. The callback must not re-enter this
store.

This establishes absence during the locked observation only. It does not prove
that a prior owner never published, that a process has died, that a publisher
has retired, or that a writer may restart. The original issuer sequence,
checkpoint witness, process lifetime and registry lifecycle remain separate
requirements.

## Qualification

Six explicit Root parent tests are defined under
`authority_host_store::initialization::tests`:

| Test | Boundary |
| --- | --- |
| `root_exact_initialization_reads_only_the_same_canonical_genesis` | Exact canonical value retains its inode and bytes; another expected value is refused. |
| `root_exact_initialization_publishes_the_complete_matching_candidate` | A full original candidate is published without changing its inode or encoding. |
| `root_exact_initialization_never_truncates_bad_or_later_candidates` | Different values, malformed records, wrong owners, unknown fields and wrong permissions remain errors with evidence preserved. |
| `root_exact_initialization_keeps_lock_and_durability_failures_visible` | Original lock contention and an actual directory-sync acknowledgement failure remain errors; explicit later exact completion reads the same visible record. |
| `root_absent_initialization_checks_both_names_and_retains_the_original_lock` | Actual empty state permits the callback under the original lock; any existing publication entry prevents it. |
| `root_absent_initialization_rechecks_publication_names_after_callback_errors` | Error-valued callbacks still receive the full absence postcondition. |

These tests use actual protected `/run` files and the original owner. They are
ignored by default and require an explicit Root run with zero retries. Source
conservation and diff checks are not runtime acceptance. Integration records
must retain the actual pinned build and Root results. The new non-replacing
rename also requires actual native-kernel execution; a Linux host test or
static syscall inspection alone is not native qualification.
