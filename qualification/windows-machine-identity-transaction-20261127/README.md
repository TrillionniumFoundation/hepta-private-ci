# Machine account credentials shared safely across homes

## Concrete production failure

The original complete Windows core run used fixed local accounts
CodexSandboxOffline and CodexSandboxOnline. Each new home generated replacement
passwords and called NetUserSetInfo, while prior homes retained their own encrypted
copy. The original real failure included CreateProcessWithLogonW error 1326.
A process-local single-flight map cannot prevent sequential or concurrent homes
from invalidating each other's account credentials.

## Proposed transaction

The helper keeps the existing account names, group and SIDs. An application-owned
local LSA record contains a compact, versioned Pending or Ready transaction. Its
chosen passwords and any pre-existing SIDs are saved before account mutation.
After each account completes, the exact SID is persisted. Recovery reconciles
that same intent; it never invents a new password for an interrupted operation.
A Ready transaction is validated against actual account and logon-token SIDs and
reused without resetting passwords. A replaced account, malformed transaction,
changed password or unrelated same-name pending account is refused.

An administrator-protected machine mutex serializes only provisioning and
credential publication. Existing mutex owner and DACL are validated before
waiting. It does not serialize sandbox commands or the original test suite.
New machine passwords draw directly from the existing OS random source.
Only NERR_UserExists allows the existing explicit migration update path;
unrelated NetUserAdd errors do not cause a password reset.

Per-home publication retains the existing DPAPI format. Its directory is opened
without reparse traversal, protected before data exists and held against rename.
An existing unsafe directory is refused without narrowing its permissions:
changing a DACL cannot revoke access granted to a previously opened handle.
Each leaf receives its own protected descriptor at CREATE_NEW. Its actual owner,
DACL and ordinary-file identity are checked before writing credential bytes and
again through the final readback handle. The file is flushed, atomically replaced
and cannot inherit a later parent ACL broadening. The final setup stage validates
this private directory rather than overwriting it with the former generic ACL.
DPAPI is not treated as a substitute for ACL protection.

## Actual controls required

The complete original setup-helper target remains unfiltered. The added parent
control launches two actual independent provisioning processes against different
homes, checks both worker terminal results and verifies that the first credentials
still log on after concurrent and sequential setup. The one ignored worker entry
is explicitly executed by that parent twice; its isolated child result must say
one passed, zero failed and zero ignored.

Additional controls retain a Pending record across an actual account-creation
interruption, reject a same-name/new-SID replacement, reject a broadly accessible
pre-existing mutex before secret/account creation, and exercise publication while
the real directory is held against rename. Three Windows filesystem controls
reject a pre-existing wide directory without rewriting it, reject a late parent
DACL change before any secret write, and verify that a published leaf retains its
own private descriptor when its parent's permissions change.
Original tests, budgets and retries
are unchanged. The complete Windows consumer matrix remains a separate required
gate; a setup-target pass alone cannot qualify the whole platform.

## Authority references

- Microsoft LsaStorePrivateData and LsaRetrievePrivateData:
  https://learn.microsoft.com/en-us/windows/win32/api/ntsecapi/nf-ntsecapi-lsastoreprivatedata
  https://learn.microsoft.com/en-us/windows/win32/api/ntsecapi/nf-ntsecapi-lsaretrieveprivatedata
- Microsoft local secret objects:
  https://learn.microsoft.com/en-us/windows/win32/secmgmt/private-data-object
- Microsoft synchronization object security:
  https://learn.microsoft.com/en-us/windows/win32/sync/synchronization-object-security-and-access-rights

The source uses the already-enabled windows-sys 0.52 API. The LSA wire record is
bounded by its 512-byte secret limit. No dependency edge or lock is changed.
