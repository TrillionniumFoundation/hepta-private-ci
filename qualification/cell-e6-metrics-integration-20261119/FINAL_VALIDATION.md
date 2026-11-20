# Exact #6709 integration and validation

The joint candidate now contains the original #6709 production and regression-test blobs. A terminal experiment decision must have verified selected-model C use and a consistent cold-process replay. Engineering decision status does not grant native adoption or settlement qualification.

| Binding | Exact identity |
| --- | --- |
| Previous joint candidate | `325218ec2e5f085637e78e192bf188842e51fad5` |
| Original fix source | `773f25e53504790c74364aa3b1606ed51853df32` |
| Integrated source | `0bdf65445f9bbefba2c45dc3e611dd36386a1456` |
| Original integration evidence | `e4b4eb5028578be87d5cad0829103632f2bff3a3` |
| Production blob | `04c556c5831ba2a01341404f15882020a68ff956` |
| Regression-test blob | `3bd61299f923e1f3ce2f80d92780991dfab4434e` |

## Actual original controls

The old production source with the new original test reproduces the missing-C accounting bug: seven tests, one expected failure. The integrated original control set passes **114 tests across 18 modules**, with zero failures, errors or skips and unchanged source bytes. The earlier missing-original-fixture setup error remains in its own unmodified result and logs. Restoring the exact frozen fixture resolved that setup issue without changing the production source, tests or acceptance conditions.

The final original test result SHA256 is `b7ac2606a68c48eee6cde87746cd89260307fa829297249abbcf3656f8a78125`. These are engineering controls, with zero research model calls, training updates or original native E6 executions.

## Actual repository formatting

On a new isolated worktree at exact `e4b4eb5028578be87d5cad0829103632f2bff3a3`, both original commands completed successfully:

```text
just fmt --base 325218ec2e5f085637e78e192bf188842e51fad5
just fmt --base 325218ec2e5f085637e78e192bf188842e51fad5 --check
```

Their exit codes are 0 and 0; times are 68.96339422400342 and 0.26507815899094567 seconds. The final diff is zero bytes. The exact source and test hashes are unchanged. Ruff remains the lockfile-pinned 0.15.13; the isolated uv tool is 0.13.9.

The missing-uv failure, timed-out dependency download and two offline-cache failures are retained along with the final pass. `formatter-20261120/` includes all 38 original records. Reconstruct `format-attempts.tar.xz` by concatenating the two paths in `PARTS.json` order after checking their declared lengths and SHA256 values. The combined archive is 755,576 bytes with SHA256 `dc485e277ec40f143f623e06eaa4529f6d50d6b34a1e924e043ef0883b425418`; every original member was independently checked against `MANIFEST.json`. The final formatter result SHA256 is `632fae957aaddab50d0b30f41668bbfb50d6af018f0419d69699ef78491f1519`.

## CI remains a separate result

The engineering-integrity GitHub job passed 216 tests on **prospective merge** `fa730773d40130a59acb68fd08443717ba95ec04`, which merged e4b into `061334747ce9d87690c40df48eeedf239156b57d`. That is not an exact-head native E6 run. The original complete engineering, spelling and contract logs are retained in `ci-readback-20261120/original-ci-logs.tar.xz` with their original hashes and merge identity.

Whole CI has not passed. The original spelling failure referred to the derived CURRENT narrative, now corrected with the earlier exact CURRENT retained in its own compressed archive and original Git history. The contract scan also rejects exact workflow-name strings copied from original Trillionnium-Chain API evidence; those raw inputs and the failing gate have not been rewritten or relaxed. Other blocking CI failures remain separate and cannot be converted into a pass by these focused controls.

The historical joint execution source is unchanged. All ten joint qualification flags remain false. No native original-owner adoption, complete native NoUpdate, cold new D, FinalUse, settlement or production activation is claimed by this integration.
