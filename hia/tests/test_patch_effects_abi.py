#!/usr/bin/env python3
"""Check native effect frames, explicit transitions and no-write boundaries.

Public filesystem parity is qualified by the separate complete original owner
gate. These requests exercise the private continuation ABI without filesystem
callbacks. Live disjoint buffers have deliberately unaligned pointers.
"""
import argparse
import ctypes
import hashlib
import json
import struct
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAX = (1 << 64) - 1
INVALID = (1 << 32) - 1
SHORT = INVALID - 1


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def frame(kind=1,phase=0,status=0,*,count=1,index=0,move=0,exact=1,length=0,old=0,destination=MAX,metadata=0,parent=0,expected=b'',observed=b''):
 probe=phase in (13,31)
 words=[1,phase,count,index,kind,move,exact,length,old,destination,status,metadata,parent,len(expected) if probe else 0,176 if probe else 0,len(observed) if probe else 0,176+len(expected) if probe else 0,1,0,0,0,0]
 return struct.pack('<22Q',*words)+expected+observed


def verify(library_dir):
    source = ROOT / "hia/patch_effects.hepta"
    contract_path = ROOT / "hia/patch_effects_buffer_contract.json"
    build_path = library_dir / "build.json"
    build = json.loads(build_path.read_text())
    assert build["status"] == "built" and build["compiler_fixed_point"] is True
    component = build["modules"]["patch_effects"]
    abi = component["codex_link_abi"]
    library_path = library_dir / "libcodex_hia_patch_effects.so"
    archive_path = library_dir / "libcodex_hia_patch_effects.a"
    contract = json.loads(contract_path.read_text())
    assert component["source_sha256"] == contract["source_sha256"] == sha(source)
    assert abi["symbol"] == "codex_hia_patch_effects"
    assert abi["library_sha256"] == sha(library_path)
    assert abi["archive_sha256"] == sha(archive_path)
    before = {str(path): sha(path) for path in (
        source, contract_path, build_path, library_path, archive_path,
    )}
    library = ctypes.CDLL(str(library_path))
    native = library.codex_hia_patch_effects
    native.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    native.restype = ctypes.c_uint64
    records = []
    def check(label,request,expected=0,want=None,capacity=160,workspace_len=0):
     guard=b'\xd3'*17;s=bytearray(guard+request+guard);o=bytearray(guard+b'\xa5'*capacity+guard);w=bytearray(guard+b'\x79'*workspace_len+guard)
     snapshots=[bytes(v) for v in (s,o,w)];views=[(ctypes.c_ubyte*len(v)).from_buffer(v) for v in (s,o,w)]
     actual=native(ctypes.addressof(views[0])+17,len(request),ctypes.addressof(views[1])+17,capacity,ctypes.addressof(views[2])+17,workspace_len)
     assert actual==expected,(label,actual,expected)
     assert bytes(s)==snapshots[0] and bytes(w)==snapshots[2],label
     if expected:assert bytes(o)==snapshots[1],('error wrote output',label)
     else:
      assert o[:17]==guard and o[145:]==snapshots[1][145:],('output boundary',label)
      words=struct.unpack('<16Q',o[17:145]);assert words[0]==1 and words[14:]==(0,0),label
      for offset,value in (want or {}).items():assert words[offset]==value,(label,offset,words[offset],value)
     return {'case':label,'status':int(actual),'source_bytes':len(request),'output_sha256':hashlib.sha256(o).hexdigest()}
    cases=[
     ('empty',frame(0,count=0),{1:18,11:1,3:1,4:0}),
     ('complete',frame(0,count=3,index=3,length=2),{1:0,4:2,5:3}),
     ('begin-add',frame(),{1:1,2:1,3:1}),
     ('add-commit',frame(1,4,1,old=1,length=2),{1:17,4:3,5:1,8:1,9:1}),
     ('add-retry-select',frame(1,4,2),{1:10,2:5,3:1}),
     ('add-retry-ends',frame(1,7,2),{1:18,3:0,11:3}),
     ('mkdir-error',frame(1,6,3),{1:18,3:0,11:5}),
     ('no-parent-retry',frame(1,5,1),{1:8,2:7}),
     ('parent-create',frame(1,5,1,parent=1),{1:12,2:6}),
     ('delete-probe-inexact',frame(2,12,3,old=1,exact=0),{1:16,2:13,3:0}),
     ('delete-no-old-no-probe',frame(2,12,3),{1:18,3:0,11:7}),
     ('delete-no-old-commit',frame(2,12,1,exact=0,length=2),{1:17,4:2,8:0,9:3}),
     ('delete-directory',frame(2,11,1,old=1,metadata=4),{1:18,11:8}),
     ('move-destination-first',frame(3,24,1,old=1,move=1,length=2),{1:14,2:25,4:3,6:2,8:4,9:0}),
     ('move-failure-keeps-add',frame(3,25,3,old=1,move=1,length=3,destination=2),{1:18,4:3,6:2,8:0,11:9}),
     ('move-success-replaces',frame(3,26,1,old=1,move=1,length=3,destination=2),{1:17,4:3,6:MAX,8:5,9:2}),
     ('inplace-no-retry',frame(3,30,2,old=1),{1:18,3:0,11:3}),
     ('optional-missing',frame(1,3,2),{1:8,3:1,7:0}),
     ('optional-error',frame(1,3,3),{1:8,3:0,7:0}),
     ('delete-missing',frame(2,10,2),{1:14,3:0,7:0}),
     ('metadata-symlink',frame(1,2,1,metadata=3),{1:3,3:0}),
     ('metadata-file',frame(1,2,1,metadata=1),{1:3,3:1}),
     ('metadata-missing',frame(1,2,2),{1:3,3:1})]
    for follow in (0,1):
     for mode in (0,1):
      for label,request,want in cases:
       words=list(struct.unpack('<22Q',request));words[17:19]=[follow,mode]
       records.append(check(f'{label}-f{follow}-m{mode}',struct.pack('<22Q',*words),want={**want,12:follow,13:mode}))
    for value in (b'',b'\x00\xffbinary','甲\r\n乙\r'.encode(),b'x'*(2*1024*1024)):
     for exact in (0,1):
      records.append(check('equal-'+str(len(value))+'-'+str(exact),frame(2,13,1,old=1,exact=exact,expected=value,observed=value),want={1:18,3:exact,11:7}))
      records.append(check('different-'+str(len(value))+'-'+str(exact),frame(2,13,1,old=1,exact=exact,expected=value,observed=value+b'z'),want={1:18,3:0,11:7}))
    records.append(check('failed-empty-read',frame(2,13,2,old=1),want={1:18,3:0,11:7}))
    base=frame()
    for length in range(176):records.append(check('short-source-'+str(length),base[:length],expected=SHORT))
    for capacity in (0,1,7,64,127):records.append(check('short-output-'+str(capacity),base,capacity=capacity,expected=SHORT))
    records.append(check('nonempty-workspace',base,workspace_len=1,expected=INVALID));records.append(check('plain-tail',base+b'x',expected=INVALID))
    for index,value in [(0,0),(0,2),(1,8),(1,255),(2,0),(3,1),(4,4),(5,1),(5,2),(6,2),(8,1),(8,2),(9,0),(10,1),(10,4),(11,1),(11,8),(12,1),(13,MAX),(14,176),(15,1),(16,176),(17,2),(18,2),(19,1),(20,1),(21,1)]:
     words=list(struct.unpack('<22Q',base));words[index]=value;records.append(check('invalid-word-'+str(index)+'-'+str(value),struct.pack('<22Q',*words),expected=INVALID))
    for kind,phase,move in [(1,4,0),(3,24,1),(3,30,0)]:records.append(check('delta-overflow-'+str(phase),frame(kind,phase,1,move=move,old=1,length=MAX),expected=INVALID))
    for index,value in [(13,MAX),(14,175),(15,MAX),(16,0),(9,0)]:
     request=frame(2,13,1,old=1,expected=b'a',observed=b'a');words=list(struct.unpack('<22Q',request[:176]));words[index]=value
     records.append(check('probe-span-'+str(index),struct.pack('<22Q',*words)+request[176:],expected=INVALID))
    def concurrent(index):
     value=(str(index)+'甲乙\r\n').encode()*4096
     return check('concurrent-'+str(index),frame(2,13,1,old=1,exact=index%2,expected=value,observed=value),want={1:18,3:index%2,11:7})
    with ThreadPoolExecutor(max_workers=8) as pool:records.extend(pool.map(concurrent,range(128)))
    assert all(sha(path) == digest for path, digest in before.items())
    return {
        "schema": "codex.hia.patch-effects-abi.v1",
        "passed": True,
        "scope": "Raw ABI and explicit semantic transitions; complete original filesystem differential remains a separate gate.",
        "native_calls": len(records),
        "error_no_write_cases": sum(row["status"] != 0 for row in records),
        "concurrent_calls": 128,
        "skipped": 0,
        "unaligned_disjoint_buffers": True,
        "source_and_artifacts_unchanged": True,
        "compiler_sha256": build["compiler_sha256"],
        "inputs": before,
        "records": records,
        "whole_product_qualified": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-dir", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    library_dir = args.library_dir.resolve(strict=True)
    if args.report:
        target = args.report.resolve()
        if target == ROOT or target.is_relative_to(ROOT) or target.is_relative_to(library_dir):
            parser.error("report must be outside source and native artifact directories")
    result = verify(library_dir)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in (
        "passed", "native_calls", "error_no_write_cases", "concurrent_calls", "skipped",
    )}))


if __name__ == "__main__":
    main()
