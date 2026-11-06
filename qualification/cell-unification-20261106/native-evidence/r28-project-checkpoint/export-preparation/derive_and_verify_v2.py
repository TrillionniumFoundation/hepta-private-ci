#!/usr/bin/env python3
"""Pure local controller-JSON readback; never import or execute either exporter."""
from pathlib import Path
import ast
import difflib
import hashlib
import json

ROOT=Path(__file__).resolve().parent
WORK=ROOT.parent


def pin(raw):
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}


def exact(name,raw):
    p=ROOT/name
    if p.exists():assert p.read_bytes()==raw
    else:p.write_bytes(raw)


def main():
    original=(ROOT/'export-r28-closed-template.py').read_bytes()
    assert pin(original)['sha256']=='6e3b27eb70806ce69ac66fc4d6c2b9ca61a76d41d5072063f069a7c2e7780452'
    before=b"require(len(raw)==v['size'] and v['text'].encode()==raw,'controller text/hex differs')"
    after=b"require(len(raw)==v['next_offset']-v['offset'] and v['size']>=v['next_offset'] and v['text'].encode()==raw,'controller text/hex differs')"
    assert original.count(before)==1
    revised=original.replace(before,after)
    assert revised.replace(after,before)==original
    ast.parse(revised)
    exact('export-r28-closed-template-v2.py',revised)
    patch=''.join(difflib.unified_diff(original.decode().splitlines(True),revised.decode().splitlines(True),fromfile='export-r28-closed-template.py',tofile='export-r28-closed-template-v2.py')).encode()
    exact('v1-to-v2.patch',patch)
    controller=WORK/'native-validation-results/r28-closed-input/controller'
    names=['launch.json','terminal-process-status.json','read-000000.json','read-002995.json','read-005725.json']
    raw={name:(controller/name).read_bytes() for name in names};values={name:json.loads(b) for name,b in raw.items()}
    terminal=values['terminal-process-status.json'];job='1a1b1e9bee0-fc05-7b7c'
    assert terminal['job_id']==job and values['launch.json']['job']['id']==job
    streams={}
    for stream in ('stdout','stderr'):
        parts=[];details=[]
        for name in names[2:]:
            record=values[name];assert record['job_id']==job
            v=record[stream];b=bytes.fromhex(v['bytes_hex'])
            assert len(b)==v['next_offset']-v['offset']
            assert v['size']>=v['next_offset'] and v['text'].encode()==b
            parts.append((v['offset'],b))
            details.append({'file':name,'offset':v['offset'],'next_offset':v['next_offset'],'reported_stream_size':v['size'],'actual_chunk_bytes':len(b),'raw_chunk':pin(b),'v1_size_equals_chunk_length':len(b)==v['size']})
        end=0;joined=[]
        for offset,b in sorted(parts,key=lambda x:x[0]):
            if not b:assert offset<=end;continue
            assert offset==end;end+=len(b);joined.append(b)
        assert terminal['log_bytes'][stream]['seen']==terminal['log_bytes'][stream]['stored']==end
        streams[stream]={'chunks':details,'contiguous_nonempty_offsets':True,'total_bytes':end,'terminal_seen':terminal['log_bytes'][stream]['seen'],'terminal_stored':terminal['log_bytes'][stream]['stored'],'joined':pin(b''.join(joined))}
    assert streams['stdout']['total_bytes']==8309 and streams['stderr']['total_bytes']==0
    report={'schema':'hepta.r28-export-controller-v2-readback.v1','original_template':pin(original),'revised_template':pin(revised),'patch':pin(patch),'only_change':'Controller size is total stream bytes; chunk length is next_offset minus offset. Require stream size at least next_offset.','exact_inverse_to_v1':True,'ast_parsed':True,'FROZEN':False,'unknown_binding_groups':3,'original_controller_files':[{'path':str((controller/name).relative_to(WORK)),**pin(raw[name])} for name in names],'stream_readback':streams,'exporter_imported_or_executed':False,'rust_native_or_new_probe_executed':False,'originals_modified':False,'native_observation_confirms_v1_reader_assumption_would_fail':True}
    exact('V2-CONTROLLER-READBACK.json',(json.dumps(report,indent=2)+'\n').encode())
    print(json.dumps({'template_v2':pin(revised),'patch':pin(patch),'controller_files':5,'stdout_bytes':8309,'stderr_bytes':0,'AST_and_JSON_readback_only':True},indent=2))


if __name__=='__main__':main()
