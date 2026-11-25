# Original paired Root registration

This component opens existing paired enrollment and effect records in the
original Root Registry. It creates no registration, lease, grant, material
reader or dispatch route. Trusted Root composition may explicitly install it
with `HostAuthorityService::with_registered_paired`; the default is absent.
Installation also requires the original writer, Registry and matching human
registration. No wire request can install it.

The effect identity depends only on the original delivery. The enrollment
identity depends on the study and principal. Full bindings retain the exact
purpose, enrollment commitment, operation, materials, policy generation and
original human route/revision/expiry. Existing records must match; changed
metadata cannot renew or replace an original record.

The new four-record boundary checks the original issuer, writer, effect and
independently revocable enrollment under one Registry mutex. All four identities
are distinct; three opaque tokens must belong to the same actual owner. Each
complete record, revision, epoch, revocation and deadline is checked at entry.
The contract checks distinct record IDs and the caller's exact expected
bindings; this Root owner supplies the enrollment and paired-effect classes.
The existing three-record boundary remains unchanged. The callback cannot
reenter the Registry or defer material access into asynchronous work.

Only a non-authorizing observation leaves this component. Actual held-UI
liveness at first material read, material custody and a real consumer-entry
protocol remain unimplemented. The existing Device/Notes lanes and Python
`owner_intake` refusals remain unchanged. A preparation response cannot be used
as a queued receipt or permission.

Nine scoped native engineering controls use synthetic identities and real
temporary registries/issuer stores. They cover the four-record enrollment fence,
foreign tokens and role aliases, actual-entry revocation and expiry, open-only
recovery, changed metadata, independent enrollment withdrawal, conflicting CAS,
equal foreign registries and missing/expired records. The workflow requires
nine actual executed controls; no skipped or prior result qualifies this source.
They exercise the private open-only component below the actual Root launcher
check. They do not qualify `from_registered` service installation, register a
real participant or spend frozen E1–E6 budgets.

The actual service also rejects this paired FinalUse destination before the
generic issuer, even when its original policy is already configured. A separate
ignored Root-only negative control uses the real protected clock, registry,
issuer and original framed service, peer credentials and held pidfd to assert
no response prefix, grant or counter/frontier change. It
requires an explicitly selected isolated temporary Root test parent. Until that
exact control is launched by an approved Root engineering gate, it remains
unexecuted and is not included in the ordinary minimum of nine.

The source-head architecture lane contains that separate engineering gate. It
first binds the clean source/tree, Rust 1.96 compiler, Cargo package metadata
and the one original libtest binary as the ordinary runner user. A new
create-only `/run/hepta-paired-root-ci-<run>-<attempt>` directory has Root owner
and mode 0700; the Root phase accepts no caller-selected command or state path.
It copies only the pinned binary, runs the exact ignored test once, and requires
the original named success and a terminal result with zero ignored tests.
The ordinary nine, eight gate rejection controls and this Root one have separate
execution records. An ignored test in the ordinary run is not this Root result.
The four handoff file hashes only guard the preparation-to-Root handoff. Full
source identity comes from the clean Git commit/tree before and after the build
and execution plus the fixed binary hash; this is not a full dependency closure
attestation.
The workflow enters the Root owner directly through its fixed `sudo` command;
no non-Root command owner tries to signal the Root process group. A subsequent
non-Root collector verifies the original Root result, stdout hash, binary and
Git identities and cleanup. Collection executes zero tests and never echoes
the original PASS lines into another test counter.
The Root phase holds the original evidence directory descriptor. Inputs are
opened without following links and authenticated on that same descriptor before
one bounded read supplies both the hash and parser. Test stdout first stays in
the private Root directory. Public evidence uses exclusive creation relative to
the held directory, with permissions set only through its newly created file
descriptor. A caller's path replacement cannot redirect Root permission changes.
Read-only inputs are opened nonblocking before their regular-file check, so a
FIFO replacement is rejected without waiting for a writer.

Build and execution share one 300-second monotonic deadline on the same boot.
Compilation is charged separately. Root entry narrows the existing deadline to
at most 35 further seconds; the test is capped at 20 seconds and reserves cleanup
time. Cancellation is retained as failure while the original owner finishes its
bounded child wait and cleanup. The existing CI owner retains the direct test leader
through the last group signal, then reaps it once. Successful completion also
requires removal of the original private state directory. Uncertain child
ownership or cleanup refusal fails and retains state rather than claiming
cleanup. OS spawn and filesystem operations are not hard real-time guarantees.
The job uses `contents: read`; the Root invocation receives no token, secret,
historical authority directory, real participant or real material. Nothing is
run as Root on an H host. These controls remain unexecuted until this exact
candidate's normal CI provides its original records.
