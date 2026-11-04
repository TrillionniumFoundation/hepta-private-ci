# Retained Hepta original normal evidence

This archive retains the exact official artifacts and audit records of two completed failed workflows on source H `103e4bcb3a6fbce57943a0c7c339d1d48808ce69`, actual prospective M `68c36639d609033334785b347273899f5abab500`, source tree `73d6f50dd52b5e30b536758335dbc82385f63ab3`.

| Original run | Source-specific result |
|---|---|
| [41746794500](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41746794500) | 132 actual native passes, zero native failures, eight Exec entries blocked before native by the metadata reader; workflow failure. |
| [41752326136](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41752326136) | Four metadata prechecks passed, eight selected entries blocked by ctor compilation failure, zero native executions; all four jobs failed. |

Each package is stored losslessly as ordered JSON/base64 chunks. INDEX.json pins every chunk, complete package, package member and all twelve original official ZIPs. It also pins a deterministic digest of every original ZIP member's size and SHA-256. The separately published ctor source A6 and its new run are not results of either retained package.

`python3 verify_payloads.py` reads these files as data only. It validates complete byte identities, official artifact metadata, ZIP CRCs and every nested member. It does not extract members, execute payload scripts or native binaries, or request the network. Its integrity PASS retains the original workflow failures. Original Python audit sources and workflows inside the packages are archived data.

No independently downloaded ELF bytes are claimed. Recorded ELF identities remain CI observations. No whole-system, PQ security, platform-wide, stress or production qualification is granted. Source branches and default branches remain unchanged by this evidence-only archive. The frozen Library completeness denominator is unchanged.
