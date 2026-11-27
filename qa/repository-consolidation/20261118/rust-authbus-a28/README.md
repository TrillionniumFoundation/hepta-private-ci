# AuthBus global-capacity fixture history reconciliation

This review joins ordinary branch
`codex/authbus-global-capacity-fixture-20261018` at
`60eb1a36e4e59291698a9652e9d5276d957f6678` into the integration history after
`770179d123b879355b53db1d75f8f9f301280d3e`.

The incoming history contains one outstanding commit and changes one Rust test
file. The actual three-way merge has three conflicts in that file. Every other
path is unchanged. Each conflict was reviewed against the original base, incoming
source, current source, production limits, and original quarantine API. An
independent review confirms that the current fixture already covers all incoming
behavior.

## Conflict decisions

| Incoming behavior                                                                                           | Existing implementation retained                                                                                                          | Reason                                                                                                                                                                                                                                                                   |
| ----------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Spread 4,095 synthetic rows across eight issuers instead of assigning them to the real issuer.              | Bind the original global and issuer limits to the recursive SQL query; assert eight synthetic issuers.                                    | The limits are 4,096 total rows and 512 active rows per issuer. Seven synthetic issuers hold 512 rows each, the eighth holds 511, and the real issuer holds one. Different synthetic name prefixes are used consistently and do not collide with the real issuer.        |
| Require the maximum row count per issuer to be at most 512.                                                 | Require total rows and active rows to both equal 4,096, and maximum active rows per issuer to equal 512.                                  | All rows are active at this point, so both grouping queries count the same set. Exact equality to 512 also satisfies the incoming upper bound. The real issuer remains below its independent quota, so its next authenticated enqueue reaches the global capacity check. |
| Revoke all eight synthetic issuers through the normal quarantine API and require a positive affected count. | Use the same API, matching synthetic names, original key epoch, revoked registrations, and positive-count assertion for all eight groups. | Active rows are retired through the original owner API. The fixture does not delete active rows to create room.                                                                                                                                                          |

The original test also retains its rejected active-row deletion, signed claim
and acknowledgement, terminal-only pruning, replay rejection both before and
after the retention interval, and successful later enqueue.

Resolving only these three reviewed conflict blocks produces the exact current
Rust blob, `a7f28016e98c0b29f5312fcbd4f9b6e5cfba9b46`. The resolved source tree is
therefore identical to the integration parent. This conclusion follows from the
per-conflict source review and complete tree comparison. No merge strategy was
used to discard unresolved incoming changes.

## History and evidence

The merge base is `cc594bbb1494f3dc3f5adff360a58eee958f2054`. The incoming tip adds
only `60eb1a36e4e59291698a9652e9d5276d957f6678` to the current ancestry. Its full
ancestry was checked against all 356 protected HIA branch tips and the protected
roots and anchor; the intersection is empty.

`evidence.tar.gz` preserves the original base, incoming and current sources,
production limits and quarantine implementation, raw automatic merge output,
all three conflict blocks, resolved source, and independent review.
`verification.json` records their sizes and SHA-256 hashes and the local real
merge's tree and two parents. The GitHub commit identifier may differ from the
local identifier because its commit metadata is created by the repository API.

No Rust source bytes change in this reconciliation, and no new native test
result is claimed. The required hosted checks for the eventual combined commit
remain the main-merge gate. The branch itself can be deleted only after its
unchanged tip is verified as an ancestor of main.
