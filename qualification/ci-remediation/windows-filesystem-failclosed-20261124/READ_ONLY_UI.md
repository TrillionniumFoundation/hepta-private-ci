# Read-only permission warning follow-up

## Observed failure and retained boundary

The normal Windows run for source `62527854d589f814144008579c6f5ecc0fe44d18`
executed `profile_permissions_selection_emits_named_profile_event_only` and
failed its original event assertion. The existing warning helper called the
ACL-installing preparation API. That API now refuses managed execution before
side effects; the UI mapped its error to a failed-scan confirmation. This call
chain explains the changed UI path. The raw assertion did not print the actual
event payload, so that payload is not claimed as an observed value.

The actual native checkout was merge `b75e768f1835b7bbe61701e0c6e2631f20700ad8`,
with ordered parents `b9afe1f469ad12c5cd520af0ecef4c8e22f295ed` and the source
head above. Its complete tree differs from the source head. The four refusal
cases and six pure planning cases passed, and the 13 related source blobs match.
The four refusal cases each assert their completed call count (8, 16, 10, 6),
after the unchanged error and no-mutation assertions: 40 checked entry calls,
not 40 separate Rust tests. The complete Windows matrix still failed.

## Change and warning semantics

`inspect_world_writable_paths` calls the existing bounded audit with
`logs_base_dir = None`. It reads filesystem/security information and returns
found paths. It does not create capability state, install an ACL, provision an
account, launch a process or write an audit log. Existing time/item bounds and
unreadable-ACL handling remain. An empty result is not a complete isolation
proof.

The UI retains its existing notice preference and managed-permission validation.
An empty successful scan returns no warning; found paths produce up to three
samples plus the remaining count; a scan error still produces a failed-scan
warning. `Unsupported` is not converted into an empty successful result.

There is an intentional conservative difference: the old mutating helper could
install denies and then return success without a warning. The read-only helper
cannot repair those paths. World-writable paths that remain present now produce
a warning. This behavior must not be hidden by changing the notice preference,
discarding positive findings or weakening the original UI event assertion.

Actual ACL preparation retains its first-statement availability guard. All four
refusal case bodies and their 40 entry calls remain unchanged. A fifth, separate
synthetic test explicitly grants World write only to its owned fixture child,
checks that the read-only scan reports that child, then compares the complete
fixture bytes, namespace and native security descriptors and checks that neither
a child marker nor the absent Codex home was created.

## Candidate qualification

The source passed independent review, repository formatting and diff checks.
The new read-only case and the original positive UI case have **not** yet run on
this candidate in Windows CI. The previous four-case success does not qualify
the new scan, and the new scan cannot qualify managed process execution.
