# Restricted-token deletion diagnosis: mandatory integrity and parent rights

This successor changes only the already-added diagnostic method. Production
token construction, production ACL grants and all original sandbox methods and
refusal assertions are unchanged. The original two failed refusal tests remain
required and may still fail while this diagnostic runs.

The original v1 eight observations and complete raw output remain in the parent.
The v2 diagnostic keeps those exact two token modes and four routes, adds an
unrelated capability root, and measures two independent Low-integrity controls:
Low alone and Low plus a directory-only parent FILE_DELETE_CHILD deny on each
explicit Low grant. There are 20 observations. The token integrity SID and actual
object label SDDL are read back; no requested label is reported as an observed
label. Every changed descriptor belongs to this test's private temporary tree.

This isolates whether the native mandatory-integrity check closes the parent
delete route outside granted roots while capability intersection still protects
another Low-labeled root. It does not itself implement or qualify a production
grant lifecycle, inheritance policy, label restoration, child startup, hard-link
boundary, or complete matrix. No deadline, work factor, original assertion, test
filter, or original skip is changed.

Primary design references:

- https://learn.microsoft.com/en-us/windows/win32/secauthz/mandatory-integrity-control
- https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-deletefilea
- https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-createrestrictedtoken
- https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/sandbox/sandbox-windows-acl/README.md

The official MIC model separates integrity checks from DACL checks. The
independent project's own report identifies the same parent-delete route and
the need for both Low integrity and parent-deny isolation. These are hypotheses
for our exact APIs until the unique real Windows run supplies observations.
