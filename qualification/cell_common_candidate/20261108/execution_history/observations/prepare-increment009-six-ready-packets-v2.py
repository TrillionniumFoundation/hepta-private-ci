#!/usr/bin/env python3
"""Prepare only an additive six-packet evidence draft; no evidence writes or native execution."""
import ast,copy,difflib,hashlib,io,json,stat,subprocess,tarfile
from datetime import datetime,timezone
from pathlib import Path,PurePosixPath
if not __debug__:raise RuntimeError("Evidence assertions must remain enabled")
R=Path("/home/qian-qi/work/hepta-cell-s0-records-20261108-898e")
W=Path("/home/qian-qi/worktrees/hepta-cell-s0-evidence-20261108-898e")
C=Path("/home/qian-qi/worktrees/hepta-cell-s0-common-20261108-898e")
REL=Path("qualification/cell_common_candidate/20261108/execution_history")
OUT=R/"increment009-six-ready-packet-preparation-v2"
HEAD="8ca3f19c69f2f14a42aa5fbe3ff72af807c65ff2"
TREE="2e734a7f4bf5a24b9876f44b303e96e36a8cd5ec"
INDEX_SHA="e2cf90360430c0db3dde19f3ef1e00466469b363f23b338e1f9db24a114edd7b"
COMMON="bf42d2a5c2c1ed5134f8e7584de306fb015c1a8d"
COMMON_TREE="f7b65a747a1d2f585be38a4665ab2b4f1b07efb6"
CURRENT="c8b2bbb955272dde7679f86a7f0bf6113c46d7d4fbba3496446399c3615e10e4"
SOURCE="6ec5993fec3dcd6a3c569498a1d5b4c277f1c142"
SOURCE_TREE="b0ddbe6b6f83dc42657260b266774f79c9d1ed90"
PARENT_SOURCE="45a50bffd1631d502889069fc3f713b8a5e775d8"
PACKETS=json.loads("[{\"packet_id\":\"core-output-6ec5993-desktop-dependency-strict-history-v1\",\"scope\":\"Completed desktop V8 dependency failure/recovery, exact tool import and nine-stage strict preparation; execution cutoff 09:37:11 UTC; no native cases\",\"file_member_count\":198,\"archive\":{\"bytes\":1305748,\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-desktop-dependency-strict-history-v1/core-output-6ec5993-desktop-dependency-strict-history-v1.tar.xz\",\"sha256\":\"367a522060ce8270a64663b42e523a062adda630628c051597cf9bbadf88239f\"},\"result\":{\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-desktop-dependency-strict-history-v1/RESULT.json\",\"bytes\":1942,\"sha256\":\"fb9316e5b70ec2d107357ce949078f930fda07719986e131a580763ceeb5e1f1\"},\"manifest\":{\"bytes\":44185,\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-desktop-dependency-strict-history-v1/MANIFEST.json\",\"sha256\":\"ac4e3caaad1c1fa9ac83ed3cde52065796c4b7a47855286ce0e1e0a850980d88\"},\"scope_file\":{\"bytes\":10646,\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-desktop-dependency-strict-history-v1/SCOPE.json\",\"sha256\":\"ef91651c1f672ba1fc3a4c0aeabe3312dc7327cb10c9698c70b28e6c5f59868c\"},\"observations\":{\"bytes\":71954,\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-desktop-dependency-strict-history-v1/OBSERVATIONS.json\",\"sha256\":\"1a090e9528e34dcd5651947392f27f00427d91f52080792c5e72b5c164d14a29\"},\"independent\":{\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-desktop-dependency-strict-independent-verification-v1/RESULT.json\",\"bytes\":5913,\"sha256\":\"ebaf19ad7e6261d30cd49a3cd8258cdc0e271dd9cca0997036e526d4cdf758ed\"},\"required_json_members\":[\"metadata/SCOPE.json\",\"originals/core-output-6ec5993-desktop-strict-v1/preparation.json\",\"originals/core-output-6ec5993-desktop-v8-preflight-v1/RESULT.json\",\"originals/core-output-6ec5993-desktop-v8-recovery-v1/RESULT.json\",\"originals/core-output-6ec5993-desktop-strict-admission-v1/RESULT.json\",\"originals/core-output-6ec5993-desktop-strict-outer-v1/EXECUTION.json\",\"originals/core-output-6ec-desktop-tool-readiness-v1/RESULT.json\"]},{\"packet_id\":\"core-output-6ec5993-desktop-core-native-retention-history-v1\",\"scope\":\"Desktop codex-core owning native 3827 PASS plus9 ignored and metadata-only retention; not workspace\",\"file_member_count\":64,\"archive\":{\"bytes\":1860496,\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-desktop-core-native-retention-history-v1/core-output-6ec5993-desktop-core-native-retention-history-v1.tar.xz\",\"sha256\":\"4cf21a3b17a142c293890d4dd106e8b9ca6cb57fd4a79d401dcabccd63973140\"},\"result\":{\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-desktop-core-native-retention-history-v1/RESULT.json\",\"bytes\":2320,\"sha256\":\"518962b61df47a42cc1189b3c414e13949a92e0a6929ffa70d5b47eaf18050a0\"},\"manifest\":{\"bytes\":14353,\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-desktop-core-native-retention-history-v1/MANIFEST.json\",\"sha256\":\"28b7785a3d318a1a5ac2ae1a1709d097efb3d429ceb311ca25950dc2d3cf0a62\"},\"scope_file\":{\"bytes\":9041,\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-desktop-core-native-retention-history-v1/SCOPE.json\",\"sha256\":\"87f7f6e110f9c0663f16227f545ac3abc5ff93b1272b728cc219aab610d5603e\"},\"observations\":{\"bytes\":21428,\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-desktop-core-native-retention-history-v1/OBSERVATIONS.json\",\"sha256\":\"31c72c3a532518929609dd86372af5a2115f54eb6820c4c3fb9627558555e00d\"},\"independent\":{\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-desktop-core-history-independent-verification-v1/RESULT.json\",\"bytes\":3995,\"sha256\":\"401fc50e6421b81641c0ded4d192e6c551aefbbf6f47fca8fa5cdc088ce287ea\"},\"required_json_members\":[\"metadata/SCOPE.json\",\"originals/core-output-6ec5993-desktop-owning-v1/RESULT.json\",\"originals/core-output-6ec5993-desktop-owning-outer-v1/EXECUTION.json\",\"originals/core-output-6ec5993-desktop-core-retained-binaries-v1/RESULT.json\",\"originals/core-output-6ec5993-desktop-owning-v1/tests.json\"]},{\"packet_id\":\"core-output-6ec5993-desktop-appserver-failed-native-retention-history-v1\",\"scope\":\"Desktop codex-app-server owning native FAIL:1345 PASS+3 exit101,2 ignored; retention does not change failure\",\"file_member_count\":86,\"archive\":{\"bytes\":1941672,\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-desktop-appserver-failed-native-retention-history-v1/core-output-6ec5993-desktop-appserver-failed-native-retention-history-v1.tar.xz\",\"sha256\":\"61b1ed43544123461865e26a9617f094abb5eb6f00c2606a18d8b7fa4fb5d440\"},\"result\":{\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-desktop-appserver-failed-native-retention-history-v1/RESULT.json\",\"bytes\":2614,\"sha256\":\"422d918da853288175f1db11a173062aa24c0952af8364f4d92fadf6144fe46d\"},\"manifest\":{\"bytes\":19791,\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-desktop-appserver-failed-native-retention-history-v1/MANIFEST.json\",\"sha256\":\"773e74a297d08c24940226f332202229553c2859c3ddec8fd0f046d7fca5155a\"},\"scope_file\":{\"bytes\":24973,\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-desktop-appserver-failed-native-retention-history-v1/SCOPE.json\",\"sha256\":\"8a6751bfa45f3384dc0e561123c4d86dba93a264b4f5686631c56add6755c778\"},\"observations\":{\"bytes\":33303,\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-desktop-appserver-failed-native-retention-history-v1/OBSERVATIONS.json\",\"sha256\":\"2ee2558f198a9f538d2d14313fad360546c2de81a5c977d8be0142675e5559e6\"},\"independent\":{\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-desktop-appserver-failed-history-independent-verification-v1/RESULT.json\",\"bytes\":11001,\"sha256\":\"776e58bec33a9d99696931064679bec2194271dda35ff5dd4be4ba0e96a8fc63\"},\"required_json_members\":[\"metadata/SCOPE.json\",\"originals/core-output-6ec5993-desktop-appserver-owning-v1/RESULT.json\",\"originals/core-output-6ec5993-desktop-appserver-owning-outer-v1/EXECUTION.json\",\"originals/core-output-6ec5993-desktop-appserver-retained-binaries-v1/RESULT.json\",\"originals/core-output-6ec5993-desktop-appserver-owning-v1/tests.json\",\"originals/core-output-6ec5993-desktop-appserver-owning-v1/tests-junit.summary.json\"]},{\"packet_id\":\"core-output-6ec5993-desktop-agentd-root-native-retention-history-v1\",\"scope\":\"Desktop agentd default781 PASS/71 ignored and separate Root parent1 PASS; metadata-only29 binary retention, not workspace or ordinary daemon\",\"file_member_count\":100,\"archive\":{\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-desktop-agentd-root-native-retention-history-v1/core-output-6ec5993-desktop-agentd-root-native-retention-history-v1.tar.xz\",\"bytes\":1223632,\"sha256\":\"767da1f5ba1d3f047239a45ea979a61e6d4cd2ad1040cdff0bfdbc01da5a2f76\"},\"result\":{\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-desktop-agentd-root-native-retention-history-v1/RESULT.json\",\"bytes\":2599,\"sha256\":\"9a811c73810fa9740177a5fcced9918fbeb4d48e21c48b6453d116c127a8b5c8\"},\"manifest\":{\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-desktop-agentd-root-native-retention-history-v1/MANIFEST.json\",\"bytes\":23185,\"sha256\":\"ab54fccd68468cb291cd17828d3aa4bec9332abd7935dba8fea9c8db77b4c3db\"},\"scope_file\":{\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-desktop-agentd-root-native-retention-history-v1/SCOPE.json\",\"bytes\":34222,\"sha256\":\"042b9c1c3b3c2824a6bf33cbb7032ea86b9470923cf2cf99fc15c0acdc79bd4a\"},\"observations\":{\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-desktop-agentd-root-native-retention-history-v1/OBSERVATIONS.json\",\"bytes\":78366,\"sha256\":\"53fccce670d4efe18d1b80e2c4bb79941fd952e50e96d1b0c1c748bc5a5df07b\"},\"independent\":{\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-desktop-agentd-root-history-independent-verification-v2/RESULT.json\",\"bytes\":2568,\"sha256\":\"dea8199f05ec4ac23757c74c2ea9c26d43415f988e819a5af83fb1d95e4ad5f6\"},\"required_json_members\":[\"metadata/SCOPE.json\",\"originals/core-output-6ec5993-desktop-agentd-owning-v1/RESULT.json\",\"originals/core-output-6ec5993-desktop-checkpoint-root-v1/RESULT.json\"]},{\"packet_id\":\"core-output-6ec5993-desktop-posthoc-diagnostics-readback-history-v1\",\"scope\":\"Posthoc managed/OAuth diagnostic and independent records-reader history, including observer failures and lossless timestamp correction; zero native execution\",\"file_member_count\":117,\"archive\":{\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-desktop-posthoc-diagnostics-readback-history-v1/core-output-6ec5993-desktop-posthoc-diagnostics-readback-history-v1.tar.xz\",\"bytes\":247008,\"sha256\":\"bc76222d16adcfeaab2d3a745fd8bfeb67164c82b5ef28bf3f8963896c3eed03\"},\"result\":{\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-desktop-posthoc-diagnostics-readback-history-v1/RESULT.json\",\"bytes\":2030,\"sha256\":\"af6baeac4fe2f40ba944054350595f08e124c446c695a04a9cc1eff24c609791\"},\"manifest\":{\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-desktop-posthoc-diagnostics-readback-history-v1/MANIFEST.json\",\"bytes\":28808,\"sha256\":\"d383a4cd6909f553d68e01c19a214273fa082ccdcd72075ab9fa91f24848fff6\"},\"scope_file\":{\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-desktop-posthoc-diagnostics-readback-history-v1/SCOPE.json\",\"bytes\":14358,\"sha256\":\"a3421d5496b84bbaaa59e3dc349b2ce82efcc26b58d0d82acf6117ab8c3a981c\"},\"observations\":{\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-desktop-posthoc-diagnostics-readback-history-v1/OBSERVATIONS.json\",\"bytes\":27509,\"sha256\":\"186828ac5cd7db617ded2c90fc220d4addee393717bb9aa703001ba75437841c\"},\"independent\":{\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-desktop-posthoc-history-independent-verification-v1/RESULT.json\",\"bytes\":1918,\"sha256\":\"c9b2ddfc2aeb133775e18094b06bfe17bb9b51af56c8590ff563bbfd5ca09168\"},\"required_json_members\":[\"metadata/SCOPE.json\",\"originals/desktop-6ec-oauth-serial-bounded-diagnosis-v2.json\",\"originals/core-output-6ec5993-desktop-agentd-root-independent-v1/ROOT_FIXTURE_READBACK.json\"]},{\"packet_id\":\"core-output-6ec5993-quiet-source-publication-history-v1\",\"scope\":\"Completed one normal quiet-source publication of frozen6ec,17 retained validation observations,93 commands and Actions0 readback; source reviewability only\",\"file_member_count\":439,\"archive\":{\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-quiet-source-publication-history-v1/core-output-6ec5993-quiet-source-publication-history-v1.tar.xz\",\"bytes\":1547100,\"sha256\":\"e11d190b31472cbc00582a4728a6073dfeda4d5a235b39527d6524df7c23699d\"},\"result\":{\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-quiet-source-publication-history-v1/RESULT.json\",\"bytes\":2053,\"sha256\":\"337d1938f4986f9a124490d361a6b107b12036b8710d521132734bc0d962638b\"},\"manifest\":{\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-quiet-source-publication-history-v1/MANIFEST.json\",\"bytes\":104676,\"sha256\":\"fa3a2860546ef175a4b9e3ec1b42ea49b200ca6ffc9dd69f5dc7f46fb3d67fdd\"},\"scope_file\":{\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-quiet-source-publication-history-v1/SCOPE.json\",\"bytes\":4119,\"sha256\":\"13efa1e922e11c18f503016e89b441e3dc0f15ad385a78c77ca54387388d80c9\"},\"observations\":{\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-quiet-source-publication-history-v1/OBSERVATIONS.json\",\"bytes\":27733,\"sha256\":\"48e22a1fe710faa77492ecbca68105c6cf97a94a81dfe6405e10ce65ac556813\"},\"independent\":{\"path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-source-publication-history-independent-verification-v2/RESULT.json\",\"bytes\":1946,\"sha256\":\"0f24ddaf16e47d3ce4dc44ad720da1a43d7d8d383fecf1ae725801d912b6332c\"},\"required_json_members\":[\"metadata/SCOPE.json\",\"metadata/OBSERVATIONS.json\"]}]")
EXTRA_METADATA=json.loads("[{\"relative_path\":\"evidence-increment008-publication-v1/RESULT.json\",\"bytes\":23048,\"sha256\":\"4a81a52fd8e105bd28ed668cc30dafae3852149496faa93ae225335b14906e3a\"},{\"relative_path\":\"evidence-increment008-publication-v1/commands.json\",\"bytes\":57080,\"sha256\":\"f7ab0e9777ffcee5e2d3d6f99a25be492dedc64cda1fe7cfacb403796cc49a4b\"},{\"relative_path\":\"evidence-increment008-independent-readback-v1/RESULT.json\",\"bytes\":3139,\"sha256\":\"83e8d642a25e64b0d21acf94e4a1a76fd976176e71c74489e3829d10dc92f3fb\"},{\"relative_path\":\"evidence-increment008-independent-readback-v1/commands.json\",\"bytes\":130728,\"sha256\":\"41d5910eca439bcbb9e40f76b68920e5ee287c7d1189acaa385570e773a628be\"},{\"relative_path\":\"pr5397-status009-v6-publication-observation-v1.json\",\"bytes\":87275,\"sha256\":\"3c31fbcb0493488deac4916bf880bd8811384cdce485eb5f9afd25e2e36d2f06\"},{\"relative_path\":\"core-output-6ec5993-source-publication-history-independent-verification-v1/RESULT.json\"},{\"relative_path\":\"core-output-6ec5993-source-publication-history-independent-verification-v1/H_PTY_READ_ORIGINAL.json\"},{\"relative_path\":\"core-output-6ec5993-source-publication-history-independent-verification-v1/v1-to-v2.patch\",\"bytes\":1779,\"sha256\":\"0e9d209edde22a404c2999ecdb6ac1249791d030e6da930a231d1474a251eca7\"},{\"relative_path\":\"verify-desktop-6ec-source-publication-history-v1.py\",\"bytes\":7606,\"sha256\":\"d445ec705132ae2b26cdf15dccd4ce76b4ecce0b995bbe8cc7ee6ba486bd5483\"},{\"relative_path\":\"verify-desktop-6ec-source-publication-history-v2.py\",\"bytes\":7603,\"sha256\":\"625993a9081d5ec78e127b385a2996d104e7846ee35c1c1f4c6fe77c4a9edb4d\"},{\"relative_path\":\"desktop-6ec-source-publication-history-seal-launch-v1/RESULT.json\"},{\"relative_path\":\"desktop-6ec-source-publication-history-seal-launch-v1/stdout\",\"bytes\":1937,\"sha256\":\"a6c37602f2ef72e8f085f34ff8c63d4e81f506db0dcf7db5fd0706412f015c52\"},{\"relative_path\":\"desktop-6ec-source-publication-history-seal-launch-v1/stderr\",\"bytes\":0,\"sha256\":\"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855\"}]")
README_ADDITION="# Increment 009 — completed desktop owner records and quiet-source publication\n\nThis increment preserves six completed evidence packages for frozen source **6ec5993fec3dcd6a3c569498a1d5b4c277f1c142**, tree **b0ddbe6b6f83dc42657260b266774f79c9d1ed90**, parent **45a50bffd1631d502889069fc3f713b8a5e775d8**. It extends the published 008 checkpoint at **8ca3f19c69f2f14a42aa5fbe3ff72af807c65ff2** from **87 to 93 packets**, retaining all original packet entries and bytes. The resulting **11,108 archive-member entries** include repeated provenance, receipts and readbacks. They are not unique tests or source files.\n\nThe common PR head remains **bf42d2a5c2c1ed5134f8e7584de306fb015c1a8d**, tree **f7b65a747a1d2f585be38a4665ab2b4f1b07efb6**. Its complete repository CI remains failed. The formal CURRENT remains **c8b2bbb955272dde7679f86a7f0bf6113c46d7d4fbba3496446399c3615e10e4**. S0–S5 remain **HOLD**; physical and complete-history costs remain **null**.\n\nSix packages add **1,004 member entries** and **8,125,656 compressed archive bytes**. These are storage quantities with overlap, not transfer measurements or full execution cost. Git file counts are established by the actual staged-index and committed-blob closure, not by adding archive member counts.\n\n## Completed scopes and preserved outcomes\n\n| Retained scope | Actual outcome | Boundary |\n|---|---|---|\n| Desktop dependency and strict preparation | Nine original preparation/strict steps returned 0; original 15,010-file source inventory unchanged. | Execution cutoff **09:37:11 UTC**; zero native cases in this package. Earlier desktop artifact HTTP504 and incomplete/superseded transfer observations remain. |\n| Core owning package | **3,827 unique PASS**,9 original ignored,0 retries/leaks/explicit early-return markers. Four required regression cases are a subset. | Completed **09:58:20 UTC**. Does not establish workspace success or the historical bf42 race mechanism. |\n| App Server owning package | **1,345 PASS +3 exit101 FAIL =1,348 selected**,2 original ignored,0 retries/observed leaks. | Native driver/just-test/collector remain **1/100/1**. Five required cases passed individually; the original overall gate remains false. |\n| Agentd default owning package | **781 unique PASS**,71 original ignored,0 retries/leaks/explicit early-return markers. Thirteen checkpoint components are a subset. | Completed **10:39:34 UTC**. One SLOW progress classification and later output repetition do not add executions. |\n| Separate Root checkpoint fixture | **One original ignored parent case executed and passed**, four phases, real Root service and the same registered non-Root consumer. | Completed **10:47:17 UTC**. Two libtest summaries count as one acceptance parent; this is not an ordinary-daemon learning loop. |\n| Posthoc diagnostics/readbacks | Bounded original records captured/compared; observer failures and narrow corrections preserved. | Zero new native executions. Existing Core, Agentd and Root counts are not added again. |\n| Frozen source publication | One normal push of existing 6ec to its independent review branch, followed by Git/API source/tree/parent readback. | Completed **11:23:34 UTC**. Actions query returned 0 runs at that observation, neither CI success nor a future-absence claim. |\n\nHost-only retention sets are **14 Core copies  / 3,037,089,672 bytes**, **16 App Server copies  / 2,874,949,592 bytes**, and **29 Agentd copies  / 3,760,364,392 bytes**. Only metadata and original receipts are included. Executable bytes were not read or rehashed by this increment's preparation. Helper copies overlap between sets and are not unique compiled-program counts.\n\n## Exact package inventory\n\n| Packet | Members | Compressed bytes | Original-record boundary |\n|---|---:|---:|---|\n| core-output-6ec5993-desktop-dependency-strict-history-v1 |198|1,305,748|184 terminal originals plus 14 capture/generated metadata members.|\n| core-output-6ec5993-desktop-core-native-retention-history-v1 |64|1,860,496|46 originals plus 12 capture records and 6 generated metadata members.|\n| core-output-6ec5993-desktop-appserver-failed-native-retention-history-v1 |86|1,941,672|Failed-owner records, 15 extracted failure payload files and retention metadata.|\n| core-output-6ec5993-desktop-agentd-root-native-retention-history-v1 |100|1,223,632|81 originals plus 13 preparation/capture records and 6 generated metadata members.|\n| core-output-6ec5993-desktop-posthoc-diagnostics-readback-history-v1 |117|247,008|112 explicit originals plus 5 generated metadata members.|\n| core-output-6ec5993-quiet-source-publication-history-v1 |439|1,547,100|433 explicit terminal originals plus 6 generated metadata members.|\n\nEvery archive has a whole-file SHA256 pin, exact member roster, size/hash/mode checks and independent member readback. Full original JSON bindings use recursive type equality; numeric zero is not silently interchangeable with false. Compact input serialization preserves complete typed objects while meeting the publication-file bound. Original member bytes and JSON formatting remain in the archives.\n\n## Failure and observation history\n\nApp Server retains three actual failures: the OAuth localhost:1455 connection failure and two managed automatic-review cases whose expected wiremock counts were unmet. Bounded posthoc comparisons do not prove one shared environmental cause and do not relabel the run. The diagnostic packet includes original managed-review captures, the OAuth collector's first cardinality-assumption failure, corrected capture and both summary versions. The original JavaScript-derived timestamp rounding remains historical; the Python lossless successor preserves original nanoseconds **1794219243183664456**.\n\nPosthoc Core evidence includes the actual independent reader RESULT and execution receipt, not that reader's entire preparation/raw prefix. Agentd/Root audit records and preparation files are explicitly listed. The first archive reader's rejection of an original Summary containing \"(1 slow)\" remains beside its corrected readback; native cases were not rerun.\n\nThe Root driver's 53 bound input references are not a claim that all 53 external files were copied into this package. Its 81-original whitelist and member roster identify retained bytes. No active /run directory, executable, whole PTY or shared target was read by sealing.\n\nSource-publication history preserves the first admission controller's integer-zero schema rejection and successor, exact final admission, all 93 command records and their stdout/stderr, 17 copied validation observations, and seven Root H/GitHub captures. It retains **13 NUL-delimited Git stdout files** only where archived commands.json supplies the same Git -z argv, size and SHA256. The discovery guard's first rejection of those valid original bytes is retained. A later independent reader initially tested a literal backslash-zero instead of a NUL byte; that observer failure, exact correction and successful successor are separate supplementary records. Neither correction executed native code or changed the archive.\n\n## Quiet source is published; common is unchanged\n\nThe independent source ref is **refs/heads/codex/cell-s0-core-output-20261109-898e**, pointing to frozen **6ec5993fec3dcd6a3c569498a1d5b4c277f1c142** with the exact tree and parent above. Publication created no source commit, used one normal push and preserved source inventory/index, common head and formal CURRENT. Admission contains App Server FAIL and the first workspace controller's pre-native FAIL. That controller attempted no Cargo command or native case. Workspace-v2 outcome was not read or inferred by admission, publisher, sealers or this increment.\n\nSeparate source diffs affect 19, 6 and 1 paths; the last path overlaps an earlier change. Their union relative to common is **25 paths**, not 26. Publication makes the repair directly reviewable without promoting it into common or transferring passes across source revisions.\n\nPR5397 status009-v6 is a separate metadata observation: one body PATCH, exact 9,876-byte body SHA256 **9fd94488525dfc61aecbf8fd7b0cc94d461107d7d2a413ec95232ee15698d5d0**, and before/after API captures. The PR remains open/draft at common bf42. Its **11:23:34 UTC** narrative cutoff is preserved; later metadata capture is not presented as earlier execution.\n\n## Additive evidence and exclusions\n\nNineteen supplementary originals retain six independent packet readbacks; prior 008 publication/readback RESULT/commands pairs; the PR body observation; and source-publication sealer/reader failure-and-correction records. Prior 008 RESULT/commands links are retained, not the entire stdout/stderr directories. Hash references identify omitted raw files without claiming their bytes were copied here. Every new observation requires exact staged-index and committed-blob verification at publication, including original log/diff paths ignored by generic Git defaults.\n\nThis increment excludes still-running workspace-v2 results, an unexecuted d274 negative-control result, new Windows/Bazel execution and unprovided production learning registration/owner inputs. It does not read active targets, execute archives, repeat native cases or change assertions, budgets, retry settings, authorities or production refusals. Earlier bf42,45a and 6ec attempts remain under immutable packet entries. The original 008 README follows byte-for-byte as historical context.\n\n---\n\n"
ALLOWED={Path(d[k]["path"]) for d in PACKETS for k in ("archive","result","manifest","scope_file","observations","independent")}
ALLOWED.update(R/x["relative_path"] for x in EXTRA_METADATA)
seen={};commands=[];created=False
def now():return datetime.now(timezone.utc).isoformat()
def digest(data):return hashlib.sha256(data).hexdigest()
def state(p,data=None):
    assert p.is_absolute() and p.resolve()==p
    s=p.lstat();assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and not stat.S_IMODE(s.st_mode)&0o111,str(p)
    if data is None:data=p.read_bytes()
    e=p.lstat()
    assert (s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns)==(e.st_dev,e.st_ino,e.st_mode,e.st_size,e.st_mtime_ns,e.st_ctime_ns),str(p)
    assert len(data)==s.st_size
    return {"path":str(p),"bytes":len(data),"sha256":digest(data),"mode":stat.S_IMODE(s.st_mode),
      "device":s.st_dev,"inode":s.st_ino,"mtime_ns":s.st_mtime_ns,"ctime_ns":s.st_ctime_ns}
def read(p,expected=None):
    p=Path(p);assert p in ALLOWED
    assert "/helpers/bin/" not in str(p) and "target-ci-test" not in str(p)
    before=p.lstat()
    raw=p.read_bytes();row=state(p,raw)
    assert (before.st_dev,before.st_ino,before.st_mode,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(row["device"],row["inode"],stat.S_IFREG|row["mode"],row["bytes"],row["mtime_ns"],row["ctime_ns"]),str(p)
    if expected:
        assert row["bytes"]==expected["bytes"] and row["sha256"]==expected["sha256"],str(p)
    if p in seen:assert row==seen[p]
    else:seen[p]=row
    return raw
def text_json(pin):
    raw=read(pin["path"],pin);return raw,json.loads(raw)
def write_bytes(rel,data):
    p=OUT/rel;assert p.is_relative_to(OUT) and ".." not in PurePosixPath(rel).parts
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open("xb") as f:f.write(data)
    p.chmod(0o600)
    return {"path":str(p),"bytes":len(data),"sha256":digest(data)}
def write_json(rel,value):
    return write_bytes(rel,(json.dumps(value,indent=2,ensure_ascii=False)+"\n").encode())
def same_typed(a,b):
    if type(a) is not type(b):return False
    if isinstance(a,dict):return a.keys()==b.keys() and all(same_typed(a[k],b[k]) for k in a)
    if isinstance(a,list):return len(a)==len(b) and all(same_typed(x,y) for x,y in zip(a,b))
    return a==b
def git(work,*args):
    assert work in (W,C) and args[0] in {"rev-parse","status","branch","show","ls-tree"}
    p=subprocess.run(["git","-C",str(work),*args],stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
    commands.append({"argv":["git","-C",str(work),*args],"exit_code":p.returncode,
       "stdout_bytes":len(p.stdout),"stdout_sha256":digest(p.stdout),"stderr_bytes":len(p.stderr),"stderr_sha256":digest(p.stderr)})
    assert p.returncode==0
    return p.stdout
def identities():
    evidence={"head":git(W,"rev-parse","HEAD").decode().strip(),"tree":git(W,"rev-parse","HEAD^{tree}").decode().strip(),
      "branch":git(W,"branch","--show-current").decode().strip(),
      "status":git(W,"status","--porcelain=v1","--untracked-files=all").decode()}
    assert evidence=={"head":HEAD,"tree":TREE,"branch":"codex/cell-s0-evidence-20261108-898e","status":""}
    current=C/"qualification/cell-research-stages-20261108/CURRENT_RESULT.json"
    current_bytes=current.read_bytes();assert digest(current_bytes)==CURRENT
    common={"head":git(C,"rev-parse","HEAD").decode().strip(),"tree":git(C,"rev-parse","HEAD^{tree}").decode().strip(),
       "branch":git(C,"branch","--show-current").decode().strip(),
       "status":git(C,"status","--porcelain=v1","--untracked-files=all").decode(),"formal_current_sha256":digest(current_bytes)}
    assert common=={"head":COMMON,"tree":COMMON_TREE,"branch":"codex/cell-s0-common-20261108-898e","status":"","formal_current_sha256":CURRENT}
    roster_bytes=git(W,"ls-tree","-r","-z",HEAD,"--",REL.as_posix())
    roster=[]
    for line in roster_bytes.split(b"\0"):
        if not line:continue
        left,path=line.split(b"\t",1);mode,kind,blob=left.decode().split()
        assert kind=="blob" and mode in ("100644","100755")
        roster.append({"path":path.decode(),"mode":mode,"blob":blob})
    assert len(roster)==1348 and len({x["path"] for x in roster})==1348
    return {"evidence":evidence,"common":common,"git_blob_roster":roster}

def verify_ready_metadata(pos,d,result,manifest,scope,observations,verification):
    pid=d["packet_id"]
    assert result["packet_id"]==manifest["packet_id"]==scope["packet_id"]==pid
    if pos==3:assert "packet_id" not in verification
    else:assert verification["packet_id"]==pid
    assert result["source_sha"]==scope["source_sha"]==verification["source_sha"]==SOURCE
    assert result["source_tree"]==scope["source_tree"]==verification["source_tree"]==SOURCE_TREE
    if pos==4:assert "source_parent" not in scope
    else:assert scope["source_parent"]==PARENT_SOURCE
    for key,descriptor_key in (("archive","archive"),("manifest","manifest"),("scope","scope_file"),("observations","observations")):
        assert same_typed(result[key],d[descriptor_key])
    if pos==3:
        vp=verification["archive"]
        assert R/vp["path"]==Path(d["archive"]["path"])
        assert vp["bytes"]==d["archive"]["bytes"] and vp["sha256"]==d["archive"]["sha256"]
    else:assert same_typed(verification["archive"],d["archive"])
    assert scope["physical_cost"] is scope["full_history_cost"] is verification["full_history_cost"] is None
    assert scope["scientific_acceptance"] is verification["scientific_acceptance"] is False
    assert scope["stages"]=={f"S{i}":"HOLD" for i in range(6)}
    if pos<4:
        assert result["status"]=="sealed_all_originals_and_archive_members_verified"
        assert result["all_members_verified"] is True and result["originals_unchanged"] is True
    else:
        assert result["status"]==("SEALED_POSTHOC_RECORDS_ALL_MEMBERS_VERIFIED" if pos==4 else "SEALED_SOURCE_PUBLICATION_HISTORY_ALL_ORIGINALS_AND_MEMBERS_VERIFIED")
        assert result["returncode"]==0 and result["all_archive_members_verified"] is True
        assert result["original_records_before_after_unchanged"] is True and result["native_tests"]==0
    if pos==0:
        assert verification["status"]=="independent_closed_records_and_all_archive_members_verified"
        assert "returncode" not in verification and verification["member_count"]==d["file_member_count"]
        assert verification["members_and_original_records_mode_size_sha_verified"] is True
        assert verification["originals_unchanged_across_reader"] is True and verification["new_native_tests_executed"]==0
    elif pos in (1,2):
        assert verification["status"]=="INDEPENDENT_ARCHIVE_AND_ORIGINAL_RECORDS_VERIFIED"
        assert type(verification["returncode"]) is int and verification["returncode"]==0
        assert verification["all_archive_bytes_mode_sha_verified"] is True
        assert verification["original_and_capture_and_generated_records_unchanged"] is True
        assert verification["file_members"]==d["file_member_count"] and verification["new_native_tests_executed"]==0
    elif pos==3:
        assert verification["status"]=="INDEPENDENT_ALL_MEMBERS_AND_ORIGINAL_RECORDS_VERIFIED"
        assert verification["returncode"]==0 and verification["file_member_count"]==100
        assert verification["all_archive_members_bytes_modes_SHA_verified"] is True
        assert verification["all_original_bytes_modes_and_states_stable"] is True and verification["new_native_tests"]==0
        assert verification["agentd_selected_passed_unique"]==781 and verification["Root_parent_passed"]==1
    else:
        expected_status="INDEPENDENT_POSTHOC_ARCHIVE_AND_ORIGINAL_RECORDS_VERIFIED" if pos==4 else "INDEPENDENT_SOURCE_PUBLICATION_ARCHIVE_AND_ORIGINAL_RECORDS_VERIFIED"
        assert verification["status"]==expected_status and verification["returncode"]==0
        assert verification["all_archive_bytes_mode_sha_verified"] is True
        assert verification["original_and_generated_records_unchanged"] is True
        assert verification["file_members"]==d["file_member_count"] and verification["new_native_tests_executed"]==0

def main():
    global created
    OUT.mkdir(exist_ok=False);created=True;started=now()
    builder_bytes=Path(__file__).read_bytes();ast.parse(builder_bytes)
    builder_pin=write_bytes("builder.py",builder_bytes)
    before=identities()
    prior_bytes=git(W,"show",HEAD+":"+str(REL/"manifest.json"))
    assert digest(prior_bytes)==INDEX_SHA and prior_bytes==(W/REL/"manifest.json").read_bytes()
    prior=json.loads(prior_bytes)
    assert len(prior["packets"])==87 and sum(p["file_member_count"] for p in prior["packets"])==10104
    assert prior["latest_reviewed_common_source_sha"]==COMMON and prior["latest_reviewed_common_source_tree"]==COMMON_TREE
    assert prior["common_full_repository_ci_green"] is False
    assert prior["stages"]=={f"S{i}":"HOLD" for i in range(6)} and prior["stage_advancement_claimed"] is False
    assert prior["full_history_cost"] is None and prior["physical_cost"] is None
    readme=git(W,"show",HEAD+":"+str(REL/"README.md"))
    assert readme==(W/REL/"README.md").read_bytes()
    write_bytes("PARENT_MANIFEST.json",prior_bytes);write_bytes("PARENT_README.md",readme)
    write_json("PARENT_GIT_BLOB_ROSTER.json",before["git_blob_roster"])
    write_json("PARENT_PACKET_ENTRIES.json",prior["packets"])
    write_json("PARENT_COMMON_VALIDATION.json",prior["current_common_validation"])
    objects={};new_packets=[];json_pins=[];independent=[];budget_rows=[];chunks_preview=[]
    all_member_entries=[]
    for descriptor in PACKETS:
        pid=descriptor["packet_id"];assert pid not in {x["packet_id"] for x in prior["packets"]}
        archive=read(descriptor["archive"]["path"],descriptor["archive"])
        rb,result=text_json(descriptor["result"])
        mb,manifest=text_json(descriptor["manifest"])
        sb,scope=text_json(descriptor["scope_file"])
        ob,observations=text_json(descriptor["observations"])
        ib,verification=text_json(descriptor["independent"])
        verify_ready_metadata(PACKETS.index(descriptor),descriptor,result,manifest,scope,observations,verification)
        count=descriptor["file_member_count"]
        assert result["file_member_count"]==manifest["file_member_count"]==len(manifest["files"])==count
        assert manifest["manifest_is_external_to_archive"] is True
        expected={x["path"]:x for x in manifest["files"]};assert len(expected)==count
        required=set(descriptor["required_json_members"]);assert len(required)==len(descriptor["required_json_members"])
        captured={};bindings=[]
        nul_bindings={}
        if descriptor is PACKETS[5]:
            for item in observations["nul_delimited_original_git_stdout"]:
                name="originals/"+item["path"]
                nul_bindings[name]={"path":name,"bytes":item["bytes"],"sha256":item["sha256"],"producer":item["producer"],
                    "commands_member":"originals/"+str(Path(item["producer"]["commands_path"]).relative_to(R))}
            assert len(nul_bindings)==13
        nul_seen=set();archived_commands={}

        with tarfile.open(fileobj=io.BytesIO(archive),mode="r:xz") as tf:
            members=tf.getmembers();assert len(members)==len({m.name for m in members})==count
            assert {m.name for m in members}==set(expected)
            for member in members:
                q=PurePosixPath(member.name)
                assert not q.is_absolute() and ".." not in q.parts and member.isfile()
                assert not member.issym() and not member.islnk() and not member.mode&0o111
                data=tf.extractfile(member).read();row=expected[member.name]
                assert member.size==len(data)==row["bytes"] and member.mode==row["mode"] and digest(data)==row["sha256"]
                data.decode("utf-8")
                if b"\0" in data:
                    assert member.name in nul_bindings
                    bound=nul_bindings[member.name];producer=bound["producer"]
                    assert bound["bytes"]==len(data) and bound["sha256"]==digest(data)
                    assert producer["argv"][0]=="git" and "-z" in producer["argv"]
                    assert producer["stdout"]=={"bytes":len(data),"sha256":digest(data)}
                    nul_seen.add(member.name)
                if member.name in {x["commands_member"] for x in nul_bindings.values()}:
                    archived_commands[member.name]=json.loads(data)
                all_member_entries.append({"packet_id":pid,**row})
                if member.name in required:
                    value=json.loads(data);captured[member.name]=value
                    binding={"path":member.name,"bytes":len(data),"sha256":digest(data),"equals":[{"path":[],"value":value}]}
                    bindings.append(binding);json_pins.append({"packet_id":pid,"path":member.name,"bytes":len(data),"sha256":digest(data)})
                    write_bytes("required-json/"+pid+"/"+member.name,data)
                if member.name=="metadata/SCOPE.json":assert data==sb
                if member.name=="metadata/OBSERVATIONS.json":assert data==ob
        assert set(captured)==required and nul_seen==set(nul_bindings)
        for item in nul_bindings.values():
            p=item["producer"]
            matches=[c for c in archived_commands[item["commands_member"]] if c["label"]==p["command_label"]]
            assert len(matches)==1 and matches[0]["argv"]==p["argv"] and matches[0]["stdout"]==p["stdout"]
        new_packets.append({"packet_id":pid,"scope":descriptor["scope"],"archive_path":descriptor["archive"]["path"],
            "bytes":len(archive),"sha256":digest(archive),"file_member_count":count,
            "required_json_members":bindings,"nul_delimited_git_stdout":list(nul_bindings.values())})
        objects[pid]={"result":result,"scope":scope,"observations":observations,"verification":verification,"required":captured}
        independent.append({"kind":"original_json_observation","source_path":descriptor["independent"]["path"],
          "relative_path":"observations/"+str(Path(descriptor["independent"]["path"]).relative_to(R)),
          "bytes":len(ib),"sha256":digest(ib),"scope":"Post-seal independent archive/record readback; not new native execution"})
        for k in ("archive","result","manifest","scope_file","observations","independent"):
            p=descriptor[k];budget_rows.append({"packet_id":pid,"role":k,**p})
        parts=[]
        for number,offset in enumerate(range(0,len(archive),490000),1):
            chunk=archive[offset:offset+490000]
            parts.append({"name":f"archive.part{number:03}","bytes":len(chunk),"sha256":digest(chunk)})
        chunks_preview.append({"packet_id":pid,"archive_sha256":digest(archive),"archive_bytes":len(archive),
          "relative_directory":"packets/"+pid,"parts":parts,"packet_manifest_not_written":True})
    assert len(new_packets)==6 and sum(p["file_member_count"] for p in new_packets)==1004
    assert sum(p["bytes"] for p in new_packets)==8125656 and len(json_pins)==26
    strict=objects[PACKETS[0]["packet_id"]];core=objects[PACKETS[1]["packet_id"]];app=objects[PACKETS[2]["packet_id"]]
    strict_preparation=strict["required"]["originals/core-output-6ec5993-desktop-strict-v1/preparation.json"]
    assert strict_preparation["status"]=="prepared_clean" and strict_preparation["returncode"]==0
    assert strict_preparation["source_sha"]==SOURCE and strict_preparation["source_tree"]==SOURCE_TREE
    assert strict_preparation["source_unchanged"] is True and len(strict_preparation["steps"])==9
    assert all(type(s["returncode"]) is int and s["returncode"]==0 for s in strict_preparation["steps"])
    assert strict["scope"]["native_cases"]==0 and strict["scope"]["partial_cross_host_transfer_not_upgraded_to_complete"] is True
    assert strict["scope"]["original_desktop_artifact_HTTP504_preserved"] is True
    core_native=core["required"]["originals/core-output-6ec5993-desktop-owning-v1/RESULT.json"]
    assert core_native["status"]=="PASS" and core_native["returncode"]==core_native["test_returncode"]==core_native["collect_returncode"]==0
    assert core_native["observed_passed_tests"]==3827 and core_native["observed_failed_tests"]==0
    assert core_native["required_output_regression_cases_passed"] is True
    app_native=app["required"]["originals/core-output-6ec5993-desktop-appserver-owning-v1/RESULT.json"]
    assert app_native["status"]=="FAIL" and app_native["returncode"]==app_native["collect_returncode"]==1
    assert app_native["test_returncode"]==100 and app_native["observed_passed_tests"]==1345 and app_native["observed_failed_tests"]==3
    assert app_native["required_five_cases_passed"] is False
    assert app["scope"]["counts"]["required_passed_subset"]==5 and app["scope"]["root_cause_all_failures"] is None
    for native,selected,ignored in ((core_native,3827,9),(app_native,1348,2)):
        assert native["source_sha"]==SOURCE and native["source_tree"]==SOURCE_TREE and native["base_sha"]==PARENT_SOURCE
        assert native["discovered_counts"]=={"selected_count":selected,"ignored_count":ignored,"unselected_count":0}
        assert native["exact_fresh_unique_executed_set"] is True and native["source_unchanged"] is True and native["retries"]==0
        assert native["explicit_skip_markers"]==native["leak_markers"]==[]
        assert native["full_workspace_executed"] is False and native["scientific_acceptance"] is False
    base_observation={"source_sha":SOURCE,"source_tree":SOURCE_TREE,"source_parent":PARENT_SOURCE,
       "host":"desktop","source_publication_claimed_by_this_observation":False,"common_source_advanced":False,
       "full_workspace_qualified":False,"scientific_acceptance":False,"physical_cost":None,"full_history_cost":None}
    added={
      "desktop_6ec_dependency_strict_history":{**copy.deepcopy(base_observation),
        "packet_id":PACKETS[0]["packet_id"],"execution_cutoff":strict["result"]["original_execution_cutoff"],
        "strict_preparation_status":"prepared_clean","strict_phase_count":9,"all_original_phase_returncodes":[s["returncode"] for s in strict_preparation["steps"]],
        "native_cases_in_this_packet":0,"initial_desktop_artifact_HTTP504_preserved":True,
        "partial_or_unknown_transport_not_upgraded":True,"exact_tool_import_record_retained":True,
        "later_owner_executions_in_separate_packets":True},
      "desktop_6ec_core_owning_history":{**copy.deepcopy(base_observation),
        "packet_id":PACKETS[1]["packet_id"],"execution_finished_at":core_native["finished_at"],
        "status":"PASS","driver_returncode":0,"test_returncode":0,"collect_returncode":0,
        "counts":{"selected_executed_unique":3827,"passed":3827,"failed":0,"original_ignored":9,"retries":0,"leaks":0,"required_passed_subset":4},
        "host_only_binary_count":14,"host_only_binary_bytes":3037089672,"binary_bytes_archived":False,
        "named_ignored_source":"Actual discovery and original Summary count; no per-case SKIP raw lines",
        "original_45a_failure_preserved":True},
      "desktop_6ec_appserver_failed_owning_history":{**copy.deepcopy(base_observation),
        "packet_id":PACKETS[2]["packet_id"],"execution_finished_at":app_native["finished_at"],
        "status":"FAIL","driver_returncode":1,"test_returncode":100,"collect_returncode":1,"junit_collection_status":"retained-failed",
        "counts":{"selected_executed_unique":1348,"passed":1345,"failed_exit101":3,"original_ignored":2,"retries":0,"leaks":0,"required_passed_subset":5},
        "original_required_five_overall_passed_field":False,"five_actual_passes_do_not_rescue_whole_run":True,
        "host_only_binary_count":16,"host_only_binary_bytes":2874949592,"binary_bytes_archived":False,
        "retention_success_does_not_change_native_failure":True,"failed_case_payload_files":15,
        "root_cause_all_failures":None,"all_failures_classified_as_environment":False}
    }
    agent=objects[PACKETS[3]["packet_id"]];posthoc=objects[PACKETS[4]["packet_id"]];publication=objects[PACKETS[5]["packet_id"]]
    agent_native=agent["required"]["originals/core-output-6ec5993-desktop-agentd-owning-v1/RESULT.json"]
    root_native=agent["required"]["originals/core-output-6ec5993-desktop-checkpoint-root-v1/RESULT.json"]
    assert agent_native["status"]=="PASS" and agent_native["returncode"]==agent_native["test_returncode"]==agent_native["collect_returncode"]==0
    assert agent_native["observed_passed_tests"]==781 and agent_native["observed_failed_tests"]==0
    assert root_native["status"]=="PASS" and root_native["returncode"]==root_native["wrapper_exit"]==0
    assert root_native["parent_case_pass_count"]==root_native["observed_original_parent_case_pass_count"]==1
    assert root_native["fixture_child_is_additional_acceptance_case"] is False
    assert agent["result"]["host_only_executable_count"]==29 and agent["result"]["host_only_executable_bytes"]==3760364392
    assert posthoc["scope"]["original_appserver_native_status_remains_FAIL"] is True
    assert posthoc["scope"]["managed_root_cause_proven"] is False
    assert posthoc["scope"]["all_appserver_failures_assigned_one_environment_cause"] is False
    assert publication["scope"]["source_publication_is_reviewability_only"] is True
    assert publication["scope"]["original_appserver_FAIL_and_workspace_v1_pre_native_controller_FAIL_preserved"] is True
    added.update({
        "desktop_6ec_agentd_root_owning_history":{**copy.deepcopy(base_observation),"packet_id":PACKETS[3]["packet_id"],
            "agentd_status":"PASS","agentd_execution_finished_at":agent["result"]["agentd_execution_finished_at"],
            "agentd_counts":{"selected_executed_unique":781,"passed":781,"failed":0,"original_ignored":71,"retries":0,"leaks":0,"required_checkpoint_passed_subset":13},
            "Root_status":"PASS","Root_execution_finished_at":agent["result"]["root_execution_finished_at"],
            "Root_counts":{"separate_ignored_parent_executed":1,"parent_passed":1,"child_summaries_additional_acceptance":False},
            "host_only_binary_count":29,"host_only_binary_bytes":3760364392,"binary_bytes_archived":False,
            "original_reference53_not_claimed_as53_copied_records":True,
            "ordinary_daemon_learning_bootstrap_qualified":False},
        "desktop_6ec_posthoc_diagnostics_history":{**copy.deepcopy(base_observation),"packet_id":PACKETS[4]["packet_id"],
            "posthoc_seal_finished_at":posthoc["result"]["finished_at"],"original_file_count":112,
            "new_native_tests":0,"additional_native_passes_claimed":0,"appserver_original_status":"FAIL",
            "all_appserver_failures_assigned_one_environment_cause":False,
            "OAuth_original_cardinality_capture_failure_retained":True,
            "OAuth_rounded_derived_v1_retained_as_history_not_typed_admission":True,
            "OAuth_lossless_v2_original_timestamp_ns":1794219243183664456,
            "independent_readback_does_not_add_Core_or_agentd_or_Root_cases":True,
            "agentd_archive_reader_original_slow_summary_rejection_retained":True},
        "quiet_6ec_source_publication_history":{**copy.deepcopy(base_observation),"packet_id":PACKETS[5]["packet_id"],
            "source_publication_claimed_by_this_observation":True,
            "status":publication["observations"]["actual_source_publication_status"],
            "target_ref":publication["scope"]["target_ref"],
            "execution_finished_at":publication["scope"]["actual_publication_finished_at"],
            "actual_normal_push_count":1,"new_source_commits_created":0,"new_native_tests":0,
            "actual_command_count":93,"retained_validation_observation_count":17,
            "actions_count_at_original_observation":0,"actions_zero_is_not_CI_success":True,
            "workspace_v2_result_not_read_or_inferred":True,
            "same_source_appserver_FAIL_and_workspace_v1_controller_FAIL_preserved":True,
            "original_records_count":433,"exact_Git_z_NUL_stdout_count":13,
            "unique_changed_paths_relative_to_common":25,"separate_diff_path_counts_not_summed":[19,6,1]}
    })
    current=copy.deepcopy(prior["current_common_validation"])
    for key,value in added.items():assert key not in current["separate_source_observations"];current["separate_source_observations"][key]=value
    retained=copy.deepcopy(current)
    for key in added:del retained["separate_source_observations"][key]
    assert same_typed(retained,prior["current_common_validation"])
    assert current["source_sha"]==COMMON and current["source_tree"]==COMMON_TREE
    assert current["full_repository_ci"]["green"] is False
    supplemental_objects={}
    for extra in EXTRA_METADATA:
        p=R/extra["relative_path"];raw=read(p,extra if "bytes" in extra else None)
        raw.decode("utf-8");assert b"\0" not in raw
        kind="original_json_observation" if p.suffix==".json" else "original_text_observation"
        if kind=="original_json_observation":supplemental_objects[extra["relative_path"]]=json.loads(raw)
        independent.append({"kind":kind,"source_path":str(p),"relative_path":"observations/"+extra["relative_path"],
            "bytes":len(raw),"sha256":digest(raw),"scope":"Explicit original publication/readback/PR/observer history; not native execution"})
    assert len(independent)==19 and len({x["relative_path"] for x in independent})==19
    pub=supplemental_objects["evidence-increment008-publication-v1/RESULT.json"]
    rb=supplemental_objects["evidence-increment008-independent-readback-v1/RESULT.json"]
    assert pub["commit"]==rb["commit"]==HEAD and pub["tree"]==rb["tree"]==TREE
    assert pub["packet_count"]==rb["packet_count"]==87
    assert pub["published_file_count"]==rb["published_actual_committed_files"]==1348
    assert pub["manifest_sha256"]==rb["manifest_sha256"]==INDEX_SHA
    pins={x["relative_path"]:x for x in independent}
    assert pub["commands_receipt_sha256"]==pins["observations/evidence-increment008-publication-v1/commands.json"]["sha256"]
    assert rb["commands_sha256"]==pins["observations/evidence-increment008-independent-readback-v1/commands.json"]["sha256"]
    assert rb["publication_receipt_sha256"]==pins["observations/evidence-increment008-publication-v1/RESULT.json"]["sha256"]
    assert rb["publication_commands_sha256"]==pub["commands_receipt_sha256"]
    for key in ("evidence-increment008-publication-v1/commands.json","evidence-increment008-independent-readback-v1/commands.json"):
        assert all(type(c["exit_code"]) is int and c["exit_code"]==0 for c in supplemental_objects[key])
    pr=supplemental_objects["pr5397-status009-v6-publication-observation-v1.json"]
    assert pr["body_bytes"]==9876 and pr["body_sha256"]=="9fd94488525dfc61aecbf8fd7b0cc94d461107d7d2a413ec95232ee15698d5d0"
    assert pr["body_exactly_equal"] is pr["draft"] is pr["head_unchanged"] is True
    supplement_scope={"source_commit":HEAD,"source_tree":TREE,"files_included":"Six independent archive RESULTs, prior008 publication/readback RESULT+commands pairs, PRv6 actual observation, exact source-publication sealer and reader failure/correction records.",
        "complete_stdout_stderr_prefixes_archived_here":False,
        "prior008_full_stdout_stderr_prefixes_included":False,
        "source_publication_original433_records_are_in_separate_packet":True,
        "exact19_supplementary_files":True,"hash_references_not_claimed_as_archived_raw":True,
        "no_new_native_execution":True,"costs_are_not_complete":True}
    inputs={
      "schema_version":1,"phase":"increment-009a","transaction_status":"draft_preparation_only_not_appended",
      "expected_evidence_head":HEAD,"expected_evidence_tree":TREE,"expected_index_sha256":INDEX_SHA,
      "expected_prior_packet_count":87,"expected_final_packet_count":93,
      "expected_common_source_sha":COMMON,"expected_common_source_tree":COMMON_TREE,"formal_current_sha256":CURRENT,
      "current_common_validation":current,"packets":new_packets,
      "supplementary_observations":independent,
      "supplementary_observation_scope":supplement_scope,
      "all_old_common_validation_fields_retained_typed":True,
      "only_new_current_validation_paths":[["separate_source_observations",key] for key in added],
      "agentd_Root_terminal_execution_included":True,"workspace_v2_execution_included":False,"posthoc_terminal_packet_included":True,
      "complete_execution_history":False,"physical_cost":None,"full_history_cost":None,
      "stage_advancement_claimed":False,"stages":{f"S{i}":"HOLD" for i in range(6)},
      "appender_execution_authorized_by_this_file":False,"publisher_prepared_or_executed":False}
    input_bytes=(json.dumps(inputs,separators=(",",":"),ensure_ascii=False)+"\n").encode()
    assert len(input_bytes)<=490000,("draft inputs exceed chunk limit",len(input_bytes))
    assert len((README_ADDITION.encode()+readme))<=512000
    assert all(row["bytes"]<=512000 for row in independent)
    proposed_packet_manifest_sizes=[]
    for packet,preview in zip(new_packets,chunks_preview):
        member_rows=[{k:row[k] for k in ("path","bytes","sha256")} for row in all_member_entries if row["packet_id"]==packet["packet_id"]]
        chunks=[];offset=0
        for number,row in enumerate(preview["parts"],1):
            chunks.append({"sequence":number,"path":"packets/"+packet["packet_id"]+"/"+row["name"],
                "offset":offset,"bytes":row["bytes"],"sha256":row["sha256"]})
            offset+=row["bytes"]
        proposed={**packet,"file_members":member_rows,"publication_chunks":chunks,
            "reassembled_original_bytes_verified":True,"all_original_file_members_verified":True,
            "required_json_member_bindings_verified":True}
        size=len((json.dumps(proposed,indent=2)+"\n").encode())
        assert size<=512000,("packet manifest exceeds publication limit",packet["packet_id"],size)
        proposed_packet_manifest_sizes.append({"packet_id":packet["packet_id"],"bytes":size,"limit":512000})
    write_json("PROPOSED_PACKET_MANIFEST_SIZES.json",proposed_packet_manifest_sizes)

    delta={
      "schema_version":1,"status":"reviewable_manifest_delta_only_no_index_written","phase":"increment-009a",
      "parent_commit":HEAD,"parent_tree":TREE,"parent_manifest_sha256":INDEX_SHA,
      "protected_original_git_files":1348,"protected_original_packet_count":87,
      "protected_old_packet_entries":copy.deepcopy(prior["packets"]),
      "old_packet_entry_values_and_old_blob_modes_must_remain_exact":True,
      "new_packet_count":6,"packet_count_after_if_approved":93,
      "old_member_entries_with_overlap":10104,"added_member_entries_with_overlap":1004,
      "member_entries_after_if_approved":11108,"archive_bytes_total":8125656,
      "append_packet_index_rows":[{"packet_id":p["packet_id"],"scope":p["scope"],"archive_bytes":p["bytes"],
          "archive_sha256":p["sha256"],"file_member_count":p["file_member_count"],
          "manifest_path":"packets/"+p["packet_id"]+"/manifest.json","manifest_sha256":None,
          "manifest_sha256_status":"not generated; append remains unexecuted"} for p in new_packets],
      "archive_chunks_preview":chunks_preview,
      "new_typed_separate_source_observations":added,
      "old_current_common_validation_preserved_typed":True,
      "common_full_repository_ci_green":False,
      "new_metadata_staged_index_and_committed_blob_closed_set_required":True,
      "future_committed_file_count":None,"no_append_commit_push":True,
      "full_history_cost":None,"physical_cost":None,"stages":{f"S{i}":"HOLD" for i in range(6)}}
    assert same_typed(delta["protected_old_packet_entries"],prior["packets"])
    parent_header={"commit":HEAD,"tree":TREE,"manifest":{"bytes":len(prior_bytes),"sha256":digest(prior_bytes)},
       "readme":{"bytes":len(readme),"sha256":digest(readme)},"protected_git_file_count":1348,"packet_count":87,
       "member_entries_with_overlap":10104,"common_sha":COMMON,"common_tree":COMMON_TREE,"formal_current_sha256":CURRENT}
    inputs_pin=write_bytes("DRAFT_INPUTS.json",input_bytes)
    delta_pin=write_json("MANIFEST-DELTA-DRAFT.json",delta)
    observations_pin=write_json("NEW_SOURCE_OBSERVATIONS.json",added)
    supplementary_pin=write_json("SUPPLEMENTARY_METADATA_PINS.json",independent)
    write_json("SUPPLEMENTARY_METADATA_SCOPE.json",supplement_scope)
    write_json("REQUIRED_JSON_PINS.json",json_pins)
    write_json("PARENT_IDENTITY.json",parent_header)
    readme_pin=write_bytes("README-ADDITION.md",README_ADDITION.encode())
    candidate_readme=README_ADDITION.encode()+readme
    assert candidate_readme.endswith(readme)
    full_readme_pin=write_bytes("README-CANDIDATE.md",candidate_readme)
    diff="".join(difflib.unified_diff(readme.decode().splitlines(keepends=True),candidate_readme.decode().splitlines(keepends=True),
        fromfile="a/"+str(REL/"README.md"),tofile="b/"+str(REL/"README.md")))
    readme_delta=write_bytes("README-DELTA.patch",diff.encode())
    budget={"archive_input_bytes":8125656,"archive_file_member_entries_with_overlap":1004,
      "archive_original_member_bytes_with_overlap":sum(x["bytes"] for x in all_member_entries),
      "archive_parts_preview_count":sum(len(x["parts"]) for x in chunks_preview),
      "chunk_size_bound":490000,"required_json_full_object_bindings":26,
      "draft_inputs_bytes":len(input_bytes),"draft_inputs_below_chunk_bound":True,
      "packet_external_input_files":budget_rows,
      "packet_metadata_and_readback_bytes":sum(x["bytes"] for x in budget_rows if x["role"]!="archive"),
      "proposed_supplementary_original_files":19,"proposed_supplementary_readback_bytes":sum(x["bytes"] for x in independent),
      "posthoc_diagnostic_packet_members":117,"fulltyped_input_serialization":"compact JSON; original bytes retained in archive",
      "new_metadata_index_commit_blob_verification_pending":True,
      "cost_semantics":"File and archive byte budgets only; not transport bytes or physical/full-history costs",
      "physical_cost":None,"full_history_cost":None}
    budget_pin=write_json("METADATA-BUDGET.json",budget)
    after=identities();assert same_typed(before,after)
    assert prior_bytes==(W/REL/"manifest.json").read_bytes() and readme==(W/REL/"README.md").read_bytes()
    for path,row in seen.items():assert state(path)==row,str(path)
    original_whitelist=[dict(row,role="six_ready_packet_input" if row["path"] in {p[k]["path"] for p in PACKETS for k in ("archive","result","manifest","scope_file","observations","independent")} else "explicit_supplementary_original") for row in seen.values()]
    assert len(original_whitelist)==49
    whitelist_pin=write_json("EXACT_INPUT_WHITELIST.json",original_whitelist)
    write_json("INPUTS_AFTER.json",[state(Path(row["path"])) for row in original_whitelist])
    write_json("READ_ONLY_COMMANDS.json",commands)
    result={"status":"SIX_READY_PACKET_ADDITIVE_TRANSACTION_DRAFT_PREPARED_NOT_APPENDED",
       "started_at":started,"finished_at":now(),"parent":parent_header,
       "planned_packet_count":93,"planned_member_entries_with_overlap":11108,
       "six_archives_bytes":8125656,"new_packet_count":6,"new_file_members_with_overlap":1004,
       "all1004_archive_members_size_mode_SHA_reverified":True,
       "all26_required_JSON_members_exact_bytes_and_whole_typed_objects":True,
       "old87_packet_entries_and_old_current_validation_preserved_typed":True,
       "old1348_Git_path_mode_blob_roster_preserved":True,
       "parent_worktree_clean_before_after":True,"originals_before_after_identical":True,
       "builder":builder_pin,"draft_inputs":inputs_pin,"manifest_delta":delta_pin,"new_source_observations":observations_pin,
       "readme_addition":readme_pin,"readme_candidate":full_readme_pin,"readme_delta":readme_delta,
       "metadata_budget":budget_pin,"exact_input_whitelist":whitelist_pin,"supplementary_metadata":supplementary_pin,
       "posthoc_packet_included_zero_new_native_tests":True,"old_README_exact_byte_suffix":True,
       "agentd_Root_terminal_execution_included":True,"workspace_v2_execution_included":False,
       "appender_executed":False,"commit_push_or_PR_change":False,"native_source_checkout_or_target_or_executable_read":False,
       "new_native_tests_executed":0,"full_history_cost":None,"physical_cost":None,
       "stages":{f"S{i}":"HOLD" for i in range(6)}}
    write_json("RESULT.json",result);print(json.dumps(result),flush=True)
if __name__=="__main__":
    try:main()
    except BaseException as exc:
        if created and not (OUT/"FAILED.json").exists():
            write_json("FAILED.json",{"status":"DRAFT_PREPARATION_FAILED_NOT_APPENDED","error":repr(exc),
             "finished_at":now(),"new_native_tests":0,"evidence_source_unchanged_by_preparer":True})
        raise
