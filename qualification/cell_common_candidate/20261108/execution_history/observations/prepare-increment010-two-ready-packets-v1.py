#!/usr/bin/env python3
"""Prepare only the two terminal timeout/counterfactual packets; no evidence or native mutation."""
import ast,copy,difflib,hashlib,io,json,stat,subprocess,sys,tarfile
from datetime import datetime,timezone
from pathlib import Path,PurePosixPath
if not __debug__:raise RuntimeError("Evidence assertions must remain enabled")
R=Path("/home/qian-qi/work/hepta-cell-s0-records-20261108-898e")
W=Path("/home/qian-qi/worktrees/hepta-cell-s0-evidence-20261108-898e")
C=Path("/home/qian-qi/worktrees/hepta-cell-s0-common-20261108-898e")
REL=Path("qualification/cell_common_candidate/20261108/execution_history")
OUT=R/"increment010-two-ready-packet-preparation-v1"
HEAD="6e162bab21438b857179a22c6207552feda9331b"
TREE="db1528464ed0369f3be4b7a8a7b4d8df6d9abde0"
INDEX_SHA="0cf1005179c11c185da89843f4bd23d41ce61428de620783bf9f87a5642fc2de"
COMMON="bf42d2a5c2c1ed5134f8e7584de306fb015c1a8d"
COMMON_TREE="f7b65a747a1d2f585be38a4665ab2b4f1b07efb6"
CURRENT="c8b2bbb955272dde7679f86a7f0bf6113c46d7d4fbba3496446399c3615e10e4"
SPEC=json.loads('{"schema":1,"phase":"increment-010a","parent_commit":"6e162bab21438b857179a22c6207552feda9331b","parent_tree":"db1528464ed0369f3be4b7a8a7b4d8df6d9abde0","parent_manifest_sha256":"0cf1005179c11c185da89843f4bd23d41ce61428de620783bf9f87a5642fc2de","old_packets":93,"new_packets":2,"final_packets":95,"old_members":11108,"new_members":276,"final_members":11384,"old_git_files":1427,"archive_bytes":3942052,"packets":[{"packet_id":"desktop-6ec-workspace-timeout-and-artifact-availability-history-v1","scope":"Original 6ec workspace timeout with incomplete case closure, bounded partial readback, missing-target forensic-copy failure and later retained-copy availability preflight; no executable payload.","source_sha":"6ec5993fec3dcd6a3c569498a1d5b4c277f1c142","source_tree":"b0ddbe6b6f83dc42657260b266774f79c9d1ed90","file_member_count":146,"original_record_file_count":140,"archive":{"path":"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/desktop-6ec-workspace-timeout-and-availability-history-v1/desktop-6ec-workspace-timeout-and-availability-history.tar.xz","bytes":2599580,"sha256":"b7c25e516550fa01423137c66bef6b6bf5099f1b4aff426d3a941534791e8d95"},"result":{"path":"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/desktop-6ec-workspace-timeout-and-availability-history-v1/RESULT.json","bytes":3811,"sha256":"9ae60f97bce3d7e0a9aa2504122bd1eb6e4c04cb800da8f1ac248003bf13bce4"},"manifest":{"path":"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/desktop-6ec-workspace-timeout-and-availability-history-v1/MANIFEST.json","bytes":115069,"sha256":"e6c9f07efc6c706b9287f84f25f2e588eff1ed10a746f1c48082d3af119c81d3"},"scope_file":{"path":"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/desktop-6ec-workspace-timeout-and-availability-history-v1/SCOPE.json","bytes":42761,"sha256":"e9556d9f84e5e431ece41b36bc0fc283d21bd8d6f53834df4ee5b99178bd9922"},"count_bindings":{"path":"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/desktop-6ec-workspace-timeout-and-availability-history-v1/COUNT_BINDINGS.json","bytes":1485,"sha256":"fc6940643f657ab70bae07b61864792675a06844ed1aaaf3f7879c2a1405e1ad"},"independent":{"path":"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/desktop-6ec-workspace-timeout-history-independent-v1/RESULT.json","bytes":137550,"sha256":"019b4c0e4451fe046df0580f5791fd80325ada50a83b6dafcc26de98290efd4c"},"required_json_members":["metadata/SCOPE.json","metadata/COUNT_BINDINGS.json","originals/core-output-6ec5993-desktop-workspace-v1/RESULT.json","originals/core-output-6ec5993-desktop-workspace-v2/RESULT.json","originals/core-output-6ec5993-desktop-workspace-timeout-readback-v1/RESULT.json","originals/core-output-6ec5993-desktop-workspace-timeout-artifact-retention-v1/RESULT.json"]},{"packet_id":"d274-negative-native-retention-history-v1","scope":"Exact d274 counterfactual HEAD assertion FAIL; one independently retained host-only test binary and 68-input readback; all original FAIL outcomes preserved; one exact small source bundle, no executable payload.","source_sha":"d27431b69195a2a6331a77d19e22ebeb4cf910c7","source_tree":"b1cf50c33f5ec9101217ae3f6a7ff987e3aba973","file_member_count":130,"original_record_file_count":119,"archive":{"path":"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/d274-negative-native-retention-history-v1/d274-negative-native-retention-history.tar.xz","bytes":1342472,"sha256":"bde9c3428f6261268f02c82e3383ca85a1e476498941d655343d7a25ddd90700"},"result":{"path":"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/d274-negative-native-retention-history-v1/RESULT.json","bytes":3566,"sha256":"d48e94bc28aac4d4186db502bf16ef0eb217459522ff771426a0575c4bfb4a1d"},"manifest":{"path":"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/d274-negative-native-retention-history-v1/MANIFEST.json","bytes":89944,"sha256":"f6ed2cff3c7a1799f116e910d88ca404c87a1d196e83982ee91fc6c43eacff11"},"scope_file":{"path":"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/d274-negative-native-retention-history-v1/SCOPE.json","bytes":14199,"sha256":"c908b8e270a1a604b10bfb689b446b8be9bc9f33e72134dcd49fca1e56ca3124"},"count_bindings":{"path":"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/d274-negative-native-retention-history-v1/COUNT_BINDINGS.json","bytes":978,"sha256":"b5a2ed6dc20487d31e754c4309488425e6323f89a234e43631f4b975b4d59346"},"independent":{"path":"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/d274-negative-native-history-independent-v1/RESULT.json","bytes":111190,"sha256":"dd3760e736c70b6209e2cadd04a9ddae695a9ca0f2374b700c3d609256aa4b14"},"required_json_members":["metadata/SCOPE.json","metadata/COUNT_BINDINGS.json","originals/core-output-d27431b-desktop-negative-v1/RESULT.json","originals/core-output-d27431b-desktop-negative-outer-v3/EXECUTION.json","originals/core-output-d27431b-desktop-negative-v1/tests.json","originals/core-output-d27431b-desktop-negative-retained-binary-v1/RESULT.json","originals/core-output-d27431b-desktop-negative-retention-independent-v1/RESULT.json"]}],"supplementary_originals":[{"relative_path":"evidence-increment009-publication-v1/RESULT.json","bytes":28240,"sha256":"dfae641fdc153236cc6ac85d02920f0a3b1ba5d167b56aa96041762452fd6d5a"},{"relative_path":"evidence-increment009-publication-v1/commands.json","bytes":59285,"sha256":"01e2b31594c4a26ff133cbc0157098e3e19ebd30a126694dadf78f9b155c10f3"},{"relative_path":"evidence-increment009-independent-readback-v1/RESULT.json","bytes":3136,"sha256":"09282d4f6aeb9ec28163005bf74f45d781f4bf31730bf38dfd23dba93e05c489"},{"relative_path":"evidence-increment009-independent-readback-v1/commands.json","bytes":153735,"sha256":"d2b4448c1e32cb518934633a4d0a082d6e7c08e0f96fa51ceb23f657b5420d89"},{"relative_path":"desktop-6ec-workspace-timeout-and-availability-history-v1/RESULT.json","bytes":3811,"sha256":"9ae60f97bce3d7e0a9aa2504122bd1eb6e4c04cb800da8f1ac248003bf13bce4"},{"relative_path":"desktop-6ec-workspace-timeout-history-seal-outer-v1/EXECUTION.json","bytes":1289,"sha256":"55e8aaf7d73ee77f2833557c1ee630f7deff4751fbe2cba19269b66dc3b96f22"},{"relative_path":"desktop-6ec-workspace-timeout-history-seal-outer-v1/REQUEST.json","bytes":1203,"sha256":"1b2839330f20ec3ad63870efc2685461c608f6dda37d4f0225d6cdb89243fc94"},{"relative_path":"desktop-6ec-workspace-timeout-history-seal-outer-v1/stdout.log","bytes":637,"sha256":"567c8c2416120dd6c1ba6acc80cc8a66ae11cfb49ca6ca80d0e0832aaf0db6ee"},{"relative_path":"desktop-6ec-workspace-timeout-history-seal-outer-v1/stderr.log","bytes":0,"sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},{"relative_path":"desktop-6ec-workspace-timeout-history-independent-v1/RESULT.json","bytes":137550,"sha256":"019b4c0e4451fe046df0580f5791fd80325ada50a83b6dafcc26de98290efd4c"},{"relative_path":"desktop-6ec-workspace-timeout-history-independent-outer-v1/EXECUTION.json","bytes":1585,"sha256":"594ea7c7f5e1b1fee8283c85617ab1091d1fc81c119fcb5cd1b4403571fb4e71"},{"relative_path":"desktop-6ec-workspace-timeout-history-independent-outer-v1/REQUEST.json","bytes":711,"sha256":"6abcbc66daae156dde82beb5a0606e33ea9a4344e01ce7892ddb6e33ca05509f"},{"relative_path":"desktop-6ec-workspace-timeout-history-independent-outer-v1/stdout.log","bytes":347,"sha256":"0bbaad55311bbf7c77b5102edb14afdc266e08362d6c31d9eac61a0e4ad45c98"},{"relative_path":"desktop-6ec-workspace-timeout-history-independent-outer-v1/stderr.log","bytes":0,"sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},{"relative_path":"verify-desktop-6ec-workspace-timeout-sealed-packet-v1.py","bytes":12220,"sha256":"7b0ee2f5b1254d384793a394f6f7d25e69b343ba5d3eb736a4e1139fcb31e2ac"},{"relative_path":"d274-negative-native-retention-history-v1/RESULT.json","bytes":3566,"sha256":"d48e94bc28aac4d4186db502bf16ef0eb217459522ff771426a0575c4bfb4a1d"},{"relative_path":"d274-negative-native-history-seal-outer-v1/EXECUTION.json","bytes":1520,"sha256":"cc68349f0a4828ee57625e673513353fbc57fc9fbd02367cee59fda90ec51825"},{"relative_path":"d274-negative-native-history-seal-outer-v1/REQUEST.json","bytes":699,"sha256":"9520d636c4e01eac61e687a9e9e3dc9fae9d0d59fe02db8a1696d9fe7f942efe"},{"relative_path":"d274-negative-native-history-seal-outer-v1/stdout.log","bytes":595,"sha256":"0448221c89055b86a4399626e18c8ebbfd8614a0c2344cb23d30e16fc2ae733c"},{"relative_path":"d274-negative-native-history-seal-outer-v1/stderr.log","bytes":0,"sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},{"relative_path":"d274-negative-native-history-independent-v1/RESULT.json","bytes":111190,"sha256":"dd3760e736c70b6209e2cadd04a9ddae695a9ca0f2374b700c3d609256aa4b14"},{"relative_path":"d274-negative-native-history-independent-outer-v1/EXECUTION.json","bytes":1534,"sha256":"fe19e897692266064adcc1621037ccaf6b7eead2cc63698d24f48e4a4c05c9ff"},{"relative_path":"d274-negative-native-history-independent-outer-v1/REQUEST.json","bytes":679,"sha256":"d498404bdab015befaa5440f3cc1b49e1f07a57cf4108644a1a673e3398d5236"},{"relative_path":"d274-negative-native-history-independent-outer-v1/stdout.log","bytes":339,"sha256":"60ebac0099f7dc37993e77d8c455dbcc79d47a411f2435904a72a25001d79799"},{"relative_path":"d274-negative-native-history-independent-outer-v1/stderr.log","bytes":0,"sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},{"relative_path":"verify-d274-negative-sealed-history-v1.py","bytes":17183,"sha256":"1b67dbcbc9e05eee044d50e794ea19657d18534fe3fd15f003ceb26899512031"}],"sole_nontext_original":{"packet_id":"d274-negative-native-retention-history-v1","path":"originals/core-output-d27431b-desktop-negative-v1/source-increment-original.bundle","bytes":1800,"sha256":"0e753e10409b9619c7ddff22cd36f00bcfb74f248f5bbb09dadbc989222a6f5e"},"required_json_count":13,"prepared_only":true,"native_execution":false,"evidence_tree_written":false}')
PACKETS=SPEC["packets"]
EXTRA_METADATA=SPEC["supplementary_originals"]
README_ADDITION="# Increment 010 — original workspace timeout and counterfactual failure\n\nThis increment preserves two completed history packages and their subsequent seal/readback receipts. It extends evidence commit **6e162bab21438b857179a22c6207552feda9331b**, tree **db1528464ed0369f3be4b7a8a7b4d8df6d9abde0**, from **93 to 95 packets**. All previous packet entries and bytes remain intact. The resulting **11,384 archive-member entries** include repeated provenance and observations; they are not independent tests or unique source files.\n\nThe common PR source remains **bf42d2a5c2c1ed5134f8e7584de306fb015c1a8d**, tree **f7b65a747a1d2f585be38a4665ab2b4f1b07efb6**. Its full repository CI remains failed. The formal CURRENT SHA256 remains **c8b2bbb955272dde7679f86a7f0bf6113c46d7d4fbba3496446399c3615e10e4**. All S0–S5 stages remain **HOLD**. Physical and complete-history costs remain **null**.\n\n## Two source scopes, with their original outcomes\n\n| Source and retained scope | Actual outcome | Interpretation |\n|---|---|---|\n| 6ec5993, original workspace controller v1 | Controller failure before any native command, caused by its assumption that two parent environment variables already existed. | The subsequent metadata-only controller correction preserved the original workspace command and budget. The failed preparation remains. |\n| 6ec5993, original workspace v2 | The original **4,200-second** budget expired: wrapper exit **124**, child **−9**, driver/collector/outer **1/1/1**. | Raw output proves native activity, but there is no final native Summary or fresh native JUnit. Complete execution counts are **null** and case closure is false. |\n| 6ec5993, partial records reader | Readback completed; **6,821 unique PASS-shaped raw keys** were observed before termination. | These are partial observations, not a verified full-workspace pass count. Declared start counts do not establish the complete executed roster. |\n| 6ec5993, timeout artifact retainer | Failed when the required target was unavailable; **zero paths and zero executable bytes copied**. | Original record inputs were stable. Complete source-after/helper/inventory verification was not reached, so those guards are not claimed as passed. |\n| d27431b, one exact counterfactual case | **One FAIL**, zero PASS, zero retries, 2,447 filtered cases outside selection. Native driver/test/collector remain **1/100/1**. | The expected `HEAD` assertion failure was observed. Expected counterfactual failure does not change the native outcome to PASS. |\n| d27431b, subsequent binary retention | One independently copied test binary, **453,757,728 bytes**, with exact hash and identity checks; retention and its independent readback returned 0. | The executable remains on the host and is not in this evidence package. Successful retention does not change the failed test. |\n\nThe workspace source is **6ec5993fec3dcd6a3c569498a1d5b4c277f1c142**, tree **b0ddbe6b6f83dc42657260b266774f79c9d1ed90**. The counterfactual source is **d27431b69195a2a6331a77d19e22ebeb4cf910c7**, tree **b1cf50c33f5ec9101217ae3f6a7ff987e3aba973**, with parent **3fc4725343dccfc9487e937f77e30bc6a5d80dbc**. Results are not transferred between these sources or to common bf42.\n\n## Workspace timeout and artifact availability\n\nThe timeout package retains the original controller attempt, corrected controller, original receipts and complete captured raw output. It also retains the bounded partial reader, process observation, failed forensic retainer, exact-path metadata observations, and the later read-only availability check of fourteen previously retained Core/helper copies and two tools. That preflight verified **3,037,089,672 bytes** of retained copies without executing them. It does not establish that the unavailable workspace target was restored or that a different target contains this run's compiled artifacts.\n\nThe bounded process observation found only the expected Root shell among its selected observable processes. Its many denied or unavailable `/proc` link reads remain explicit limitations; it is not proof that every escaped process was absent. Fixed-path observations preserve the actual missing-target facts. They do not identify a deletion actor or prove why the target became unavailable.\n\nThe timeout history was sealed at **13:27:05 UTC on 2026-11-09**. The first launch acknowledgment was retained through the later H readback interruption and was reconciled without replaying the seal. Independent packet verification finished at **14:16:13 UTC**. Those later observations do not move the original workspace execution cutoff or fabricate a native JUnit report.\n\n## Exact d274 counterfactual and retained provenance\n\nThe selected case is `unified_exec::async_watcher::tests::terminal_summary_retains_output_published_before_streaming_subscribes` in the Core library. Its frozen 2,841-byte source has SHA256 **cccd41df340c5776dd078eac87418c25a5816dde4d43bd6946861331d4065879**. The original failure is at `async_watcher_tests.rs:161:13`, where the expected `HEAD` prefix was absent. The complete original raw output, fresh JUnit and failed collector result remain unchanged. The native outer completed at **13:37:14.679131 UTC**.\n\nThe selected-case failure supplies bounded counterfactual evidence for this frozen oracle. It does not establish the precise race that caused the older bf42 large-output CI failure. The package retains the original V8/fix/Clippy/discovery receipts and the full source-inventory metadata before and after execution and retention. All **68** originally bound record inputs are included. Six source inventory files each describe **15,010 entries**; their contents are metadata, not copies of every source file.\n\nThe one retained executable was copied independently with a new inode, one link and mode 0555. Its original native-time discovery established a path/size/hash; complete inode identity was captured later at retention time. The evidence does not retroactively claim an earlier inode observation. The retained ELF's SHA256 is **89a1bc28b83a2c0d24a917badd2e6209126c514409a332cf308957e1a26ad7fb**; its bytes remain host-only.\n\nThere is one explicit nontext source-provenance member: the original **1,800-byte Git bundle**, SHA256 **0e753e10409b9619c7ddff22cd36f00bcfb74f248f5bbb09dadbc989222a6f5e**. Its exact packet, member path, size and hash are admitted. This exception does not admit ELF payloads, arbitrary NUL-containing members or other binary files. The bundle remains subject to the archive hash, exact member closure and the same bounded pattern scan.\n\nThe d274 history was sealed at **14:44:17.740007 UTC**. Independent member verification completed at **14:51:17.696594 UTC** with all 130 members and all 119 current original record files checked; all 136 readback inputs remained stable. These are records operations and add no native cases.\n\n## Exact package and supplementary metadata scope\n\n| Packet | Members | Compressed bytes | Original record boundary |\n|---|---:|---:|---|\n| desktop-6ec-workspace-timeout-and-artifact-availability-history-v1 | 146 | 2,599,580 | 140 originals, five generated metadata members and the manifest. |\n| d274-negative-native-retention-history-v1 | 130 | 1,342,472 | 119 originals, ten generated metadata members and the manifest. |\n\nThe two packages add **276 member entries** and **3,942,052 compressed bytes**. Those storage quantities include overlap and are not network-transfer measurements, unique-program counts or complete execution costs. Actual Git file counts are determined by staged-index and committed-blob verification.\n\nTwenty-six supplementary originals preserve the 009 publication and independent readback RESULT/commands pairs; each new packet's final seal RESULT and complete four-file outer receipt/log set; and each packet's independent RESULT, four-file outer set and exact verifier script. The 009 command metadata identifies its original stdout/stderr hashes, but this increment does not claim to copy that publication's entire raw-output directory. Every supplementary file requires exact bytes and mode verification in the staged index and final commit.\n\nThe timeout archive already preserves the PR-v7 observation and both versions of Root's 009 publication observation. The first hand-entered capture time is retained as a corrected historical value; the successor records the time evidence and leaves embedded original strings unchanged. Later PR revisions, source D/E preparation or publication, and new native activity are outside these two packet cutoffs unless a subsequent increment explicitly binds their originals.\n\nAll JSON comparisons preserve original Python integer values and exact types. Neither successful archiving, independent readback nor expected negative-control failure advances scientific qualification. The existing 009 README follows byte-for-byte as historical context.\n\n---\n\n"
ALLOWED={Path(d[k]["path"]) for d in PACKETS for k in ("archive","result","manifest","scope_file","count_bindings","independent")}
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
    assert len(roster)==1427 and len({x["path"] for x in roster})==1427
    return {"evidence":evidence,"common":common,"git_blob_roster":roster}

def verify_ready_metadata(d,result,manifest,scope,counts,verification):
    for v in (result,manifest,scope,verification):
        assert v['packet_id']==d['packet_id'] and v['source_sha']==d['source_sha'] and v['source_tree']==d['source_tree']
    assert type(result['returncode']) is type(verification['returncode']) is int
    assert result['returncode']==verification['returncode']==0
    assert result['member_count']==verification['member_count']==manifest['archive_member_count']==d['file_member_count']
    assert manifest['payload_member_count']==len(manifest['files'])==d['file_member_count']-1
    assert result['original_record_file_count']==verification['original_record_file_count']==d['original_record_file_count']
    for field,descriptor in (('archive','archive'),('manifest','manifest'),('scope','scope_file'),('count_bindings','count_bindings')):
        assert same_typed(result[field],d[descriptor])
    assert verification['archive_sha256']==d['archive']['sha256']
    assert result['original_inputs_before_after_unchanged'] is True
    assert verification['all_members_bytes_mode_sha_verified'] is True and verification['inputs_before_after_unchanged'] is True
    assert verification['native_tests_executed']==0 and verification['executable_payload_access'] is False
    assert same_typed(verification['count_bindings'],counts)
    assert scope['full_history_cost'] is scope['physical_cost'] is None
    assert scope['scientific_acceptance'] is False and scope['stages']=={f'S{i}':'HOLD' for i in range(6)}
    if d is PACKETS[0]:
        assert result['status']=='SEALED_ORIGINAL_TIMEOUT_AND_AVAILABILITY_RECORDS'
        assert verification['status']=='ALL_146_ORIGINAL_MEMBERS_VERIFIED_TIMEOUT_FAIL_PRESERVED'
        assert scope['case_closure_verified'] is False and scope['verified_counts'] is None
        assert counts['workspace_v2']=={'driver_returncode':1,'test_wrapper_exit':124,'test_child_exit':-9,
            'timed_out':True,'collector_returncode':1,'outer_returncode':1,'verified_complete_counts':None,
            'case_closure_verified':False,'raw_native_activity_observed':True,'fresh_native_junit_available':False}
        assert counts['partial_readback']['raw_pass_shaped_unique_keys']==6821 and counts['partial_readback']['these_are_not_complete_run_counts'] is True
        assert counts['forensic_retainer']['returncode']==1 and counts['forensic_retainer']['copied_paths']==0
        assert counts['forensic_retainer']['full_source_after_verification_completed'] is False
        assert scope['negative_control_preparation_cutoff']['actual_negative_native_or_outer_output_is_excluded'] is True
    else:
        assert result['status']=='SEALED_D274_NATIVE_FAIL_AND_FORENSIC_RETENTION_HISTORY'
        assert verification['status']=='ALL_130_ORIGINAL_MEMBERS_VERIFIED_NEGATIVE_FAIL_PRESERVED'
        assert result['original_native_status']=='FAIL' and result['original_native_returncode']==1
        assert same_typed(counts['original_native'],{'status':'FAIL','driver_returncode':1,'test_returncode':100,
            'collector_returncode':1,'unique_executed':1,'passed':0,'failed':1,'failure_exit_code':101,
            'filtered_outside_selection':2447,'selected_ignored':0,'retries':0})
        assert counts['counterfactual_HEAD_assertion_failure_observed'] is True
        assert counts['expected_failure_does_not_change_test_outcome_to_PASS'] is True
        assert counts['retention']=={'returncode':0,'copied_paths':1,'host_only_payload_bytes':453757728,'copied_executables_in_archive':0}
        assert verification['all_68_original_bound_inputs_included'] is True and verification['source_bundle_exact_exception_verified'] is True

def main():
    global created
    assert sys.argv[1:]==['--execute'],'only the explicit records preparation action is allowed'
    OUT.mkdir(mode=0o700,exist_ok=False);created=True;started=now()
    builder_before=state(Path(__file__).resolve())
    builder_bytes=Path(__file__).read_bytes();ast.parse(builder_bytes)
    builder_pin=write_bytes('builder.py',builder_bytes)
    before=identities()
    prior_bytes=git(W,'show',HEAD+':'+str(REL/'manifest.json'))
    assert digest(prior_bytes)==INDEX_SHA and prior_bytes==(W/REL/'manifest.json').read_bytes()
    prior=json.loads(prior_bytes)
    assert len(prior['packets'])==93 and sum(p['file_member_count'] for p in prior['packets'])==11108
    assert prior['latest_reviewed_common_source_sha']==COMMON and prior['latest_reviewed_common_source_tree']==COMMON_TREE
    assert prior['common_full_repository_ci_green'] is False and prior['stage_advancement_claimed'] is False
    assert prior['stages']=={f'S{i}':'HOLD' for i in range(6)}
    assert prior['physical_cost'] is prior['full_history_cost'] is None
    readme=git(W,'show',HEAD+':'+str(REL/'README.md'))
    assert digest(readme)=='861d0499bf3252f843b275fef782dc6dc5dc2aeeae612fbd3e77c57a3eaeb1a0'
    assert readme==(W/REL/'README.md').read_bytes()
    write_bytes('PARENT_MANIFEST.json',prior_bytes);write_bytes('PARENT_README.md',readme)
    write_json('PARENT_GIT_BLOB_ROSTER.json',before['git_blob_roster'])
    write_json('PARENT_COMMON_VALIDATION.json',prior['current_common_validation'])
    write_json('PARENT_PACKET_ENTRIES.json',prior['packets'])
    objects={};new_packets=[];json_pins=[];chunks_preview=[];all_member_entries=[];budget_rows=[]
    for d in PACKETS:
        pid=d['packet_id'];assert pid not in {p['packet_id'] for p in prior['packets']}
        archive=read(d['archive']['path'],d['archive'])
        rb,result=text_json(d['result']);mb,manifest=text_json(d['manifest'])
        sb,scope=text_json(d['scope_file']);cb,counts=text_json(d['count_bindings'])
        vb,verification=text_json(d['independent'])
        verify_ready_metadata(d,result,manifest,scope,counts,verification)
        expected={r['path']:r for r in manifest['files']}
        assert len(expected)==len(manifest['files'])==d['file_member_count']-1
        required=set(d['required_json_members']);assert len(required)==len(d['required_json_members'])
        captured={};bindings=[];bundle=None;bundle_seen=False
        if pid==SPEC['sole_nontext_original']['packet_id']:
            bundle={k:v for k,v in SPEC['sole_nontext_original'].items() if k!='packet_id'}
        with tarfile.open(fileobj=io.BytesIO(archive),mode='r:xz') as tf:
            members=tf.getmembers()
            assert len(members)==len({m.name for m in members})==d['file_member_count']
            assert {m.name for m in members}==set(expected)|{'MANIFEST.json'}
            for member in members:
                q=PurePosixPath(member.name)
                assert str(q)==member.name and not q.is_absolute() and '..' not in q.parts and '\\' not in member.name
                assert member.isfile() and not member.issym() and not member.islnk() and not member.mode&0o111
                assert member.uid==member.gid==0 and member.mtime==0
                data=tf.extractfile(member).read()
                if member.name=='MANIFEST.json':assert data==mb and member.mode==0o644
                else:
                    row=expected[member.name]
                    assert member.size==len(data)==row['bytes'] and member.mode==row['mode'] and digest(data)==row['sha256']
                if bundle is not None and member.name==bundle['path']:
                    assert len(data)==bundle['bytes'] and digest(data)==bundle['sha256'];bundle_seen=True
                else:
                    data.decode('utf-8');assert b'\0' not in data
                all_member_entries.append({'packet_id':pid,'path':member.name,'bytes':len(data),'mode':member.mode,'sha256':digest(data)})
                if member.name in required:
                    value=json.loads(data);captured[member.name]=value
                    binding={'path':member.name,'bytes':len(data),'sha256':digest(data),'equals':[{'path':[],'value':value}]}
                    bindings.append(binding);json_pins.append({'packet_id':pid,'path':member.name,'bytes':len(data),'sha256':digest(data)})
                    write_bytes('required-json/'+pid+'/'+member.name,data)
                if member.name=='metadata/SCOPE.json':assert data==sb
                if member.name=='metadata/COUNT_BINDINGS.json':assert data==cb
        assert set(captured)==required and bundle_seen is (bundle is not None)
        new_packets.append({'packet_id':pid,'scope':d['scope'],'archive_path':d['archive']['path'],'bytes':len(archive),
            'sha256':digest(archive),'file_member_count':d['file_member_count'],'required_json_members':bindings,
            'nontext_source_bundle_original':bundle})
        objects[pid]={'result':result,'scope':scope,'counts':counts,'verification':verification,'required':captured}
        parts=[]
        for number,offset in enumerate(range(0,len(archive),490000),1):
            raw=archive[offset:offset+490000];parts.append({'name':f'archive.part{number:03}','offset':offset,'bytes':len(raw),'sha256':digest(raw)})
        chunks_preview.append({'packet_id':pid,'archive_bytes':len(archive),'archive_sha256':digest(archive),'parts':parts})
        for k in ('archive','result','manifest','scope_file','count_bindings','independent'):budget_rows.append({'packet_id':pid,'role':k,**d[k]})
    assert len(new_packets)==2 and sum(p['file_member_count'] for p in new_packets)==276
    assert sum(p['bytes'] for p in new_packets)==3942052 and len(json_pins)==13
    tv=objects[PACKETS[0]['packet_id']];nv=objects[PACKETS[1]['packet_id']]
    base_observation={'host':'desktop','common_source_advanced':False,'full_workspace_qualified':False,
        'scientific_acceptance':False,'physical_cost':None,'full_history_cost':None,'new_native_executions_by_transaction':0}
    added={
        'desktop_6ec_workspace_timeout_and_artifact_availability_history':{
            **copy.deepcopy(base_observation),'packet_id':PACKETS[0]['packet_id'],
            'source_sha':PACKETS[0]['source_sha'],'source_tree':PACKETS[0]['source_tree'],
            'status':'FAIL','case_closure_verified':False,'verified_counts':None,'count_bindings':copy.deepcopy(tv['counts']),
            'original_execution_cutoff':tv['scope']['execution_cutoff'],
            'seal_finished_at':tv['result']['finished_at'],'independent_finished_at':tv['verification']['finished_at'],
            'negative_native_outcome_excluded_from_this_original_packet':True,
            'retainer_failure_not_upgraded_by_later_preflight':True,
            'missing_target_cause_or_actor_established':False,'bounded_proc_observation_is_global_absence':False},
        'd274_counterfactual_negative_native_retention_history':{
            **copy.deepcopy(base_observation),'packet_id':PACKETS[1]['packet_id'],
            'source_sha':PACKETS[1]['source_sha'],'source_tree':PACKETS[1]['source_tree'],'source_parent':'3fc4725343dccfc9487e937f77e30bc6a5d80dbc',
            'status':'FAIL','original_native_returncode':1,'count_bindings':copy.deepcopy(nv['counts']),
            'counterfactual_assertion_observed_does_not_turn_FAIL_into_PASS':True,
            'original_bf42_large_output_race_mechanism_established':False,
            'seal_finished_at':nv['result']['finished_at'],'independent_finished_at':nv['verification']['finished_at'],
            'original_68_inputs_included':True,'host_only_ELF_payload_in_archive':False,
            'sole_nontext_original':copy.deepcopy(SPEC['sole_nontext_original'])}
    }
    current=copy.deepcopy(prior['current_common_validation'])
    for key,value in added.items():
        assert key not in current['separate_source_observations'];current['separate_source_observations'][key]=value
    retained=copy.deepcopy(current)
    for key in added:del retained['separate_source_observations'][key]
    assert same_typed(retained,prior['current_common_validation'])
    observations=[];supplemental_objects={}
    for extra in EXTRA_METADATA:
        p=R/extra['relative_path'];raw=read(p,extra)
        raw.decode('utf-8');assert b'\0' not in raw
        kind='original_json_observation' if p.suffix=='.json' else 'original_text_observation'
        if kind=='original_json_observation':supplemental_objects[extra['relative_path']]=json.loads(raw)
        observations.append({'kind':kind,'source_path':str(p),'relative_path':'observations/'+extra['relative_path'],
            'bytes':len(raw),'sha256':digest(raw),'scope':'Original completed publication/seal/readback record; zero new native executions'})
    assert len(observations)==len({r['relative_path'] for r in observations})==26
    pins={r['relative_path'].removeprefix('observations/'):r for r in observations}
    pub=supplemental_objects['evidence-increment009-publication-v1/RESULT.json']
    rb=supplemental_objects['evidence-increment009-independent-readback-v1/RESULT.json']
    assert pub['commit']==rb['commit']==HEAD and pub['tree']==rb['tree']==TREE
    assert pub['packet_count']==rb['packet_count']==93 and pub['published_file_count']==rb['published_actual_committed_files']==1427
    assert pub['manifest_sha256']==rb['manifest_sha256']==INDEX_SHA
    assert pub['commands_receipt_sha256']==pins['evidence-increment009-publication-v1/commands.json']['sha256']
    assert rb['commands_sha256']==pins['evidence-increment009-independent-readback-v1/commands.json']['sha256']
    assert rb['publication_receipt_sha256']==pins['evidence-increment009-publication-v1/RESULT.json']['sha256']
    assert rb['publication_commands_sha256']==pub['commands_receipt_sha256']
    for key in ('evidence-increment009-publication-v1/commands.json','evidence-increment009-independent-readback-v1/commands.json'):
        assert all(type(c['exit_code']) is int and c['exit_code']==0 for c in supplemental_objects[key])
    for outer_prefix in ('desktop-6ec-workspace-timeout-history-seal-outer-v1','desktop-6ec-workspace-timeout-history-independent-outer-v1',
                         'd274-negative-native-history-seal-outer-v1','d274-negative-native-history-independent-outer-v1'):
        outer=supplemental_objects[outer_prefix+'/EXECUTION.json']
        assert type(outer['child_returncode']) is int and outer['child_returncode']==0
        assert outer['status']=='NATURALLY_COMPLETED' and outer['child_os_exit_code_directly_observed'] is True
        assert outer['automatic_retry'] is False and outer['extra_timeout_or_signals'] is False
        for field in ('request','stdout','stderr','result'):
            row=outer[field];rel=str(Path(row['path']).relative_to(R));expected=pins[rel]
            assert same_typed(row,{'path':expected['source_path'],'bytes':expected['bytes'],'sha256':expected['sha256']})
    scope={'source_commit':HEAD,'source_tree':TREE,'exact_supplementary_files':26,
        'files_included':'Prior009 publication/readback RESULT+commands pairs; each packet seal RESULT and complete four-file outer; each independent RESULT and complete four-file outer plus its exact verifier.',
        'complete_stdout_stderr_prefixes_archived_here':False,
        'complete_four_file_seal_and_independent_outers_included':True,
        'prior009_full_stdout_stderr_prefixes_included':False,
        'hash_references_not_claimed_as_archived_raw':True,'no_new_native_execution':True,'costs_are_not_complete':True}
    inputs={'schema_version':1,'phase':'increment-010a','transaction_status':'draft_preparation_only_not_appended',
        'expected_evidence_head':HEAD,'expected_evidence_tree':TREE,'expected_index_sha256':INDEX_SHA,
        'expected_prior_packet_count':93,'expected_final_packet_count':95,'expected_common_source_sha':COMMON,
        'expected_common_source_tree':COMMON_TREE,'formal_current_sha256':CURRENT,'current_common_validation':current,
        'packets':new_packets,'supplementary_observations':observations,'supplementary_observation_scope':scope,
        'all_old_common_validation_fields_retained_typed':True,'only_new_current_validation_paths':[['separate_source_observations',k] for k in added],
        'source_D_E_or_new_native_outcomes_included':False,'complete_execution_history':False,
        'physical_cost':None,'full_history_cost':None,'stage_advancement_claimed':False,'stages':{f'S{i}':'HOLD' for i in range(6)},
        'appender_execution_authorized_by_this_file':False,'publisher_prepared_or_executed':False}
    input_bytes=(json.dumps(inputs,separators=(',',':'),ensure_ascii=False)+'\n').encode()
    candidate_readme=README_ADDITION.encode()+readme
    assert len(input_bytes)<=490000 and len(candidate_readme)<=512000
    assert all(r['bytes']<=512000 for r in observations)
    sizes=[];append_paths=set()
    for packet,preview in zip(new_packets,chunks_preview):
        prefix='packets/'+packet['packet_id']+'/'
        members=[{k:r[k] for k in ('path','bytes','sha256')} for r in all_member_entries if r['packet_id']==packet['packet_id']]
        chunks=[{'sequence':i,'path':prefix+c['name'],'offset':c['offset'],'bytes':c['bytes'],'sha256':c['sha256']} for i,c in enumerate(preview['parts'],1)]
        proposed={**packet,'file_members':members,'publication_chunks':chunks,'reassembled_original_bytes_verified':True,
            'all_original_file_members_verified':True,'required_json_member_bindings_verified':True}
        raw=(json.dumps(proposed,indent=2)+'\n').encode();assert len(raw)<=512000
        sizes.append({'packet_id':packet['packet_id'],'bytes':len(raw),'sha256':digest(raw),'limit':512000})
        append_paths.add(prefix+'manifest.json');append_paths.update(c['path'] for c in chunks)
    append_paths.update(r['relative_path'] for r in observations)
    append_paths.update(('increment-010a-inputs.json','increment-010a-pattern-review.json'))
    assert len(append_paths)==39
    delta={'status':'reviewable_manifest_delta_only_no_index_written','phase':'increment-010a','parent_commit':HEAD,'parent_tree':TREE,
        'parent_manifest_sha256':INDEX_SHA,'protected_original_git_files':1427,'protected_original_packet_count':93,
        'protected_old_packet_entries':copy.deepcopy(prior['packets']),'old_packet_entry_values_and_old_blob_modes_must_remain_exact':True,
        'new_packet_count':2,'packet_count_after_if_approved':95,'old_member_entries_with_overlap':11108,
        'added_member_entries_with_overlap':276,'member_entries_after_if_approved':11384,'archive_bytes_total':3942052,
        'archive_chunks_preview':chunks_preview,'proposed_packet_manifests':sizes,'exact_new_append_paths':sorted(append_paths),
        'new_typed_separate_source_observations':added,'old_current_common_validation_preserved_typed':True,
        'new_metadata_staged_index_and_committed_blob_closed_set_required':True,'future_committed_file_count':None,
        'append_commit_push_performed':False,'native_executed':False,'full_history_cost':None,'physical_cost':None}
    input_pin=write_bytes('DRAFT_INPUTS.json',input_bytes)
    delta_pin=write_json('MANIFEST-DELTA-DRAFT.json',delta)
    obs_pin=write_json('NEW_SOURCE_OBSERVATIONS.json',added)
    supplementary_pin=write_json('SUPPLEMENTARY_METADATA_PINS.json',observations)
    write_json('SUPPLEMENTARY_METADATA_SCOPE.json',scope);write_json('REQUIRED_JSON_PINS.json',json_pins)
    write_json('PROPOSED_PACKET_MANIFEST_SIZES.json',sizes)
    addition_pin=write_bytes('README-ADDITION.md',README_ADDITION.encode())
    readme_pin=write_bytes('README-CANDIDATE.md',candidate_readme)
    diff=''.join(difflib.unified_diff(readme.decode().splitlines(keepends=True),candidate_readme.decode().splitlines(keepends=True),
        fromfile='a/'+str(REL/'README.md'),tofile='b/'+str(REL/'README.md')))
    readme_delta_pin=write_bytes('README-DELTA.patch',diff.encode())
    budget={'archive_bytes_total':3942052,'archive_member_entries_with_overlap':276,
        'archive_payload_bytes_with_overlap':sum(r['bytes'] for r in all_member_entries),'archive_chunk_count':sum(len(r['parts']) for r in chunks_preview),
        'required_whole_typed_JSON_bindings':13,'draft_inputs_bytes':len(input_bytes),'draft_inputs_bound':490000,
        'readme_bytes':len(candidate_readme),'supplementary_original_file_count':26,'supplementary_original_bytes':sum(r['bytes'] for r in observations),
        'explicit_input_files':budget_rows,'packet_manifest_sizes':sizes,'exact_new_append_path_count':39,
        'all_proposed_individual_publication_files_within_limit':True,
        'cost_semantics':'Storage bytes with overlap, not execution/transport cost','physical_cost':None,'full_history_cost':None}
    budget_pin=write_json('METADATA-BUDGET.json',budget)
    after=identities();assert same_typed(before,after)
    assert prior_bytes==(W/REL/'manifest.json').read_bytes() and readme==(W/REL/'README.md').read_bytes()
    for path,row in seen.items():assert state(path)==row,str(path)
    assert state(Path(__file__).resolve())==builder_before
    whitelist=[dict(row,role='explicit_terminal_records_input') for row in seen.values()]
    assert len(whitelist)==34
    whitelist_pin=write_json('EXACT_INPUT_WHITELIST.json',whitelist)
    write_json('INPUTS_AFTER.json',[state(Path(r['path'])) for r in whitelist])
    write_json('READ_ONLY_COMMANDS.json',commands)
    result={'status':'TWO_READY_PACKET_ADDITIVE_TRANSACTION_PREPARED_NOT_APPENDED','started_at':started,'finished_at':now(),
        'parent_commit':HEAD,'parent_tree':TREE,'parent_manifest_sha256':INDEX_SHA,'planned_packet_count':95,
        'planned_member_entries_with_overlap':11384,'two_archives_bytes':3942052,'new_packet_count':2,
        'all276_archive_members_size_mode_SHA_reverified':True,'all13_required_JSON_whole_typed_bindings_retained':True,
        'old93_packet_entries_and_old_current_validation_preserved_typed':True,'old1427_git_path_mode_blob_roster_preserved':True,
        'parent_worktree_clean_before_after':True,'originals_before_after_identical':True,'builder':builder_pin,
        'draft_inputs':input_pin,'manifest_delta':delta_pin,'new_source_observations':obs_pin,'metadata_budget':budget_pin,
        'readme_addition':addition_pin,'readme_candidate':readme_pin,'readme_delta':readme_delta_pin,
        'supplementary_metadata':supplementary_pin,'exact_input_whitelist':whitelist_pin,
        'source_D_E_or_new_native_outcomes_included':False,'old_README_exact_byte_suffix':True,
        'appender_executed':False,'commit_push_or_PR_change':False,'native_source_checkout_or_target_or_executable_read':False,
        'new_native_tests_executed':0,'full_history_cost':None,'physical_cost':None,'stages':{f'S{i}':'HOLD' for i in range(6)}}
    write_json('RESULT.json',result);print(json.dumps(result),flush=True)

if __name__=='__main__':
    try:main()
    except BaseException as exc:
        if created and not (OUT/'FAILED.json').exists():
            write_json('FAILED.json',{'status':'DRAFT_PREPARATION_FAILED_NOT_APPENDED','error':repr(exc),
                'finished_at':now(),'new_native_tests':0,'evidence_source_unchanged_by_preparer':True})
        raise
