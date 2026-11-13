# ACT-1 plain HTTP host boundary

The ordinary Agentd HTTP effect host now rejects recognized action skill
invocations before an authorization claim or provider contact. The existing
goal-checked driver remains a separately provisioned path; this change registers
no observer and activates no production skill.

## Exact source and execution

| Identity | Value |
| --- | --- |
| Implementation base | 95617b64dfdb035780f18c20df5f344ace1fc34a (ACT-1 PR #5354 snapshot) |
| Code commit | 97f8643b958a7637c16a718ec181faa3e3e8eb07 |
| Formatted code tree | 879288375ebb76c27c1e7128d90a2aff16e1ea69 |
| Executed green tree | 37c8cd3e59803413dfec95ab2ae6e9c6080f46c1 |
| Native selected host tests | 3 passed, 0 failed; 748 tests not selected |
| Official formatter | just fmt, exit 0 |
| Production activation / observer registration | false / false |

The native host tests use the real AutomationStore, FinalUse authority, signed
provider configuration, and HTTP adapter, with a local Wiremock destination.
They call AgentdAutomationEffectHost directly; they do not start the daemon's
control socket or contact a deployed provider. These results are engineering
regressions, not a scientific benefit or a rerun of the earlier 150-test ACT-1
qualification or its 30-row synthetic matrix.

## Behavior and compatibility boundary

The production control route first checks readiness and decodes the wire bytes.
The host validates payload size, subject, destination, scope, and exact payload
digest. The new envelope check then runs before revocation refresh, durable
dispatch admission, FinalUse claim, and HTTP contact.

Valid envelopes are recognized through the existing ActionSkillInvocationV1.
V1 has no independent type tag, so the ordinary host also reserves the decoded
top-level pair contract_digest and destination_id. That pair is rejected when
another field has a wrong type, a required field is missing, a version differs,
fields repeat, unknown fields appear, or JSON breaks after the identity pair.
The fallback uses Serde structural parsing, not raw substring matching.

This deliberately changes compatibility for any formerly opaque top-level object
using both reserved names: it is now rejected. One name alone, nested occurrences,
and ordinary opaque bytes retain their existing transport behavior. Arbitrary
broken bytes without a recognizable identity pair cannot be unambiguously
classified as a skill; they are not authenticated or qualified as ACT-1.
This boundary is not a replacement for a future explicit tagged entry point.

Rejected cases leave the complete FinalUse capacity/frontier and TaskFlow run
unchanged, create no dispatch attempt or terminal receipt, and issue zero HTTP
requests. Reopening the same authority preserves the unchanged state. The positive
controls still send exact original bytes once and return the same settled receipt
on replay.

## Retained regression history

| Native attempt | Result |
| --- | --- |
| red, job 1a1bc27c5e0-138b0-8c | Compile exit 101: the new test used Display for Sha256Digest. Corrected to as_str; no behavioral result claimed. |
| red-r2, job 1a1bc2de718-138b0-b6 | Exit 100: 2 selected tests passed, 1 failed. The unmodified host returned Succeeded for the typed skill envelope based on Completed alone. |
| green, job 1a1bc30ca40-138b0-c2 | Exit 0: all 3 selected tests passed. |
| format, job 1a1bc323a49-138b0-ca | Official just fmt exited 0; only test layout/trailing commas changed. |

The local nextest profile retried the failing red test once; both attempts
returned the same unsupported success. This is one regression case, not two
independent trials. The green rejection test covers 11 input variants; the
ordinary-payload test covers four positive variants, alongside the original
ordinary dispatch/replay test.

The first start-call response timed out after launch. Recovery read the same
native job and retained output; it did not repeat that invocation. Original
compile failure, behavioral failure, successful execution, and formatting
receipts remain separate.

## Evidence capsule

[CODE_SOURCE.json](CODE_SOURCE.json) separates the executed tree and formatted
code commit. Production host code before the test module, the classifier, and
module registration are byte-identical before and after formatting. Tests were
not rerun after the final formatter, following repository guidance.

[native-evidence.tar.gz](native-evidence.tar.gz) retains complete native logs,
runner commands, process terminal records, the actual tested source overlays,
and the post-test formatting patch. Its manifest hashes every retained member
except the manifest itself. [VALIDATION.json](VALIDATION.json) binds archive size,
SHA256, member count, source identities, and the limits above.

Archive SHA256: 423d1a8e689bb86df73f43f8c4ba2ef1ef17a891dfa9208b220e73feef3bef94.
Archive bytes: 53966; members: 37.

Unpack into a fresh temporary directory, verify the manifest, and apply the
source overlay to the exact base before reproducing a historical test tree.
Retained runner scripts are originals with create-only paths; they should not
overwrite any historical evidence. No scientific acceptance, actual goal checker,
or production adoption is inferred from these host regression results.
