# Official same-source daemon qualification after the fixed-format repair

The normal daemon workflow ran on source fe38676fae170002fcdce90b36dc949fac3ff671 (tree 7afec5e8ba43a101b4a4c1cf4f76a7a9af5384bf). Its single direct parent was c12ee03f3185d5a13949faca54f066dfd634e509. The original GitHub Actions workflow, blob f50a7cf7b0464dbe1803da6b95ad04162843d6cc, was dispatched once; both independent jobs in run 45150994913 passed. Native job 137612046057 emitted artifact 14810439720. Caller-proof job 137612044942 emitted artifact 14808596113. These results cover this frozen source and its official owner-scoped daemon pipeline.

| Original receipt | Bytes | SHA256 |
| --- | ---: | --- |
| Native ZIP | 26921252 | 73631172619db67a2cf31c86130aad2b46e4fb5e14a2b897b7ac297a1d56dee3 |
| Caller-proof ZIP | 62439 | 92279fbd0ea5e4649697ddfb481931b068306d7b43a403fc5f0f55d50908b351 |

The 2,849 ordinary and 68 root native tests all passed, without skips, errors or failures. The named JUnit identifiers match both the immediate-parent c12 and preceding e327 runs exactly. The harness recorded UID 0 for the Root fixture and verified the entire 202-case original owner requirement in the ordinary results. The native source closure ran 1,223 controls. Original helper build and verification, ordinary/root executions, maintenance fix, formatting from fixed base b8e8c6e82abc1479c573f61a5e17d28d581e6cad, locked offline binary checks over the original six named packages, and both unmounts recorded zero exits. Six separately enumerated physical source inventories reconstructed the original commit tree. Maintenance produced zero changed paths and empty patch and postimage files.

The caller-proof job directly ran its self-test and full verifier. The source was clean before and after. The original receipt reports 1,652 boundaries, 1,652 inventory entries, 826 protected files and 9,141 Rust files, and reports no granted authority. Passing the workflow does not resolve the separate strict Rust diagnostic gate.

The direct parent c12 had passed the same 2,849+68 and covered 202 original owner cases, then failed the same fixed-base formatter with exit 2. Its native job was 137571844611 in run 45138928116. The parent native ZIP was ddf16083372d026c657405349f7738c3dbb59cf0261159ebc3c2cc1adcb4ffb4 and the separate passing caller-proof ZIP was 79aee5e189fcb34c671ed22aeac82fb412a7616618110cb2b7bc3d0dcd3e3cd9. c12-direct-parent-negative.json reconstructs that result from both raw artifacts. historical-negative.json retains the earlier e327 qualification. The adjacent direct-c12 folder records the independently measured 4,219-name formatter check/write, immutable evidence dispatch and prior negative controls.

## Reproduce

From this directory on Python 3.10+:

```sh
python bundle_archives.py restore parts /tmp/hepta-fixed-format-daemon
python verify_official.py /tmp/hepta-fixed-format-daemon/native.zip --caller /tmp/hepta-fixed-format-daemon/caller.zip --expect-all-green > /tmp/hepta-fixed-format-daemon/replayed.json
cmp actual-result.json /tmp/hepta-fixed-format-daemon/replayed.json
```

parts/manifest.json binds each bounded raw XZ fragment, each complete XZ byte stream and each restored ZIP. The recovery tool validates all lengths and digests before atomically making either ZIP available. The stored original artifacts were restored, byte-compared and re-verified. previous-cases.json.gz contains the previous genuine native test identifiers, and the verifier also checks the native JUnit and log hashes, physical inventories and exact original stage commands. All data in this directory are qualification evidence. No deployment or permission is changed by it.
