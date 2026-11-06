"""Bind actual Git publication before assigning any independent blob reads."""
from pathlib import Path
import argparse
import hashlib
import json
import re

HERE=Path(__file__).resolve().parent
WORK=HERE.parent
REPO='TrillionniumFoundation/hepta-private-ci'
REF='refs/heads/evidence/actual-elf-transport-20261105-93bfc-01'


def require(ok,reason):
    if not ok:raise ValueError(reason)


def sha(raw):return hashlib.sha256(raw).hexdigest()
def git_blob(raw):return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
def encode(value):return (json.dumps(value,sort_keys=True,indent=2)+'\n').encode()


def tool_json(path):
    raw=Path(path).read_bytes();obj=json.loads(raw)
    require(not obj.get('isError',False),'actual tool error: '+str(path))
    value=obj.get('structuredContent')
    if value is None:
        text=[x['text'] for x in obj['content'] if x['type']=='text']
        require(len(text)==1,'one tool JSON result required')
        value=json.loads(text[0])
    if isinstance(value,dict) and isinstance(value.get('content'),str):value=json.loads(value['content'])
    return value,sha(raw)


def tree_identity(paths):
    nested={}
    for path,blob in paths.items():
        cursor=nested;parts=path.split('/')
        for part in parts[:-1]:cursor=cursor.setdefault(part,{})
        require(parts[-1] not in cursor,'duplicate tree leaf')
        cursor[parts[-1]]=blob
    def visit(node):
        rows=[]
        for name,value in node.items():
            if isinstance(value,dict):mode,oid,key=b'40000',visit(value),name.encode()+b'/'
            else:mode,oid,key=b'100644',value,name.encode()
            rows.append((key,mode+b' '+name.encode()+b'\0'+bytes.fromhex(oid)))
        body=b''.join(raw for _,raw in sorted(rows))
        return hashlib.sha1(b'tree '+str(len(body)).encode()+b'\0'+body).hexdigest()
    return visit(nested)


def publish_metadata(name,meta):
    path=HERE/'metadata'/name;path.parent.mkdir(parents=True,exist_ok=True)
    raw=encode(meta)
    with path.open('xb') as output:output.write(raw)
    output=HERE/'receipts'/name.removesuffix('.json')
    output.parent.mkdir(parents=True,exist_ok=True)
    return dict(metadata_path=str(path),metadata_sha256=sha(raw),receipt_directory=str(output),
                transport_path=meta['transport_path'],request=meta['request'],
                payload_path=str(HERE/'data'/meta['transport_path']))


def metadata(prepared,path,size,digest,kind,original=None):
    blob=prepared['paths'][path]
    value=dict(schema='github-blob-readback-metadata-v1',kind=kind,repository=REPO,
        immutable_commit=prepared['commit'],immutable_tree=prepared['tree'],transport_path=path,
        transport_bytes=size,transport_sha256=digest,transport_git_blob_sha=blob,
        request={'repository_full_name':REPO,'blob_sha':blob})
    if original:value.update(original_bytes=original['bytes'],original_sha256=original['sha256'])
    return value


def verify_publication(args,plan,prepared):
    ref,ref_sha=tool_json(HERE/'control/ref.raw.json')
    commit,commit_sha=tool_json(HERE/'control/commit.raw.json')
    tree,tree_sha=tool_json(HERE/'control/tree.raw.json')
    require(ref['ref']==REF and ref['object']['type']=='commit' and ref['object']['sha']==prepared['commit'],'actual exact ref differs')
    require(commit['sha']==prepared['commit'] and commit['tree']['sha']==prepared['tree'] and commit['parents']==[],'actual orphan commit differs')
    require(tree['sha']==prepared['tree'] and tree.get('truncated') is False,'complete actual tree required')
    paths={}
    for row in tree['tree']:
        if row['type']=='tree':
            require(row['mode']=='040000','unexpected directory mode')
            continue
        require(row['type']=='blob' and row['mode']=='100644' and row['path'] not in paths,'unexpected tree leaf')
        paths[row['path']]=row['sha']
    require(paths==prepared['paths'] and len(paths)==166 and sorted(paths)==plan['expected_transport_paths'],'actual 166-file allowlist differs')
    require(tree_identity(paths)==prepared['tree'],'independently reconstructed full Git tree differs')
    require(prepared['parents']==[] and prepared['ref']==REF and prepared['expected_old'] is None,'prepared single new orphan route differs')
    return dict(repository=REPO,ref=REF,actual_commit=prepared['commit'],actual_tree=prepared['tree'],
        actual_blob_count=166,actual_parents=[],whole_tree_reconstructed=True,
        ref_rpc_sha256=ref_sha,commit_rpc_sha256=commit_sha,tree_rpc_sha256=tree_sha)


def run(args):
    plan_raw=Path(args.plan).read_bytes();require(sha(plan_raw)==args.plan_sha256,'frozen actual plan changed')
    plan=json.loads(plan_raw);prepared_raw=Path(args.prepared).read_bytes();prepared=json.loads(prepared_raw)
    require(plan['repository']==REPO and plan['destination_ref']==REF and plan['limits']['total_raw_bytes']==670306272,'fixed repository/route/data required')
    publication=verify_publication(args,plan,prepared)
    if args.stage=='metadata':
        rows=[]
        remote_index=Path(args.desktop_index).read_bytes()
        require(sha(remote_index)==prepared['index_sha256'] and git_blob(remote_index)==prepared['paths']['transport-index.json'],'actual desktop index differs')
        rows.append(publish_metadata('transport-index.json',metadata(prepared,'transport-index.json',len(remote_index),sha(remote_index),'json-utf8')))
        for archive in plan['archives']:
            phase=archive['phase'];path='archives/'+phase+'/'+phase+'-export-completion.json'
            original=(WORK/'w1'/(phase.lower()+'-elf-export')/(phase+'-export-completion.json')).read_bytes()
            require(len(original)==archive['completion_bytes'] and sha(original)==archive['completion_sha256'] and git_blob(original)==prepared['paths'][path],'original completion blob differs '+phase)
            rows.append(publish_metadata(phase+'-completion.json',metadata(prepared,path,len(original),sha(original),'json-utf8')))
        report=dict(schema='actual-git-metadata-read-assignment-v1',publication=publication,plan_sha256=sha(plan_raw),
            prepared_commit_record_sha256=sha(prepared_raw),assignments=rows)
        target=HERE/'control/metadata-assignment.json'
    else:
        index_raw=(HERE/'data/transport-index.json').read_bytes();index=json.loads(index_raw)
        require(sha(index_raw)==prepared['index_sha256'] and git_blob(index_raw)==prepared['paths']['transport-index.json'],'actual Git-read index differs')
        require(index['route_plan_sha256']==args.plan_sha256 and index['repository']==REPO and index['destination_ref']==REF and index['orphan_data_only'] is True,'actual index route binding differs')
        require(index['route']==plan['route'] and len(index['envelopes'])==162,'actual envelope set differs')
        archives={a['phase']:a for a in plan['archives']};by_phase={phase:[] for phase in ['H1','H2','H3']}
        seen=set();raw_total=text_total=0
        for row in index['envelopes']:
            phase=row['phase'];part=row['original_part'];number=part['index']
            require(phase in by_phase and 0<=number<len(archives[phase]['parts']) and part==archives[phase]['parts'][number],'original source part differs')
            path='archives/'+phase+'/parts/'+part['name']+'.b64'
            require(row['transport_path']==path and path not in seen and row['transport_git_blob']==prepared['paths'][path],'actual part Git mapping differs')
            require(row['transport_bytes']==4*((part['bytes']+2)//3) and re.fullmatch('[0-9a-f]{64}',row['transport_sha256']),'canonical byte bounds differ')
            seen.add(path);raw_total+=part['bytes'];text_total+=row['transport_bytes']
            meta=metadata(prepared,path,row['transport_bytes'],row['transport_sha256'],'base64-original-part',part)
            by_phase[phase].append(publish_metadata(phase+'/'+str(number).zfill(4)+'.json',meta))
        require([len(by_phase[p]) for p in ['H1','H2','H3']]==[32,62,68] and raw_total==670306272 and text_total==893742124,'actual full source coverage differs')
        report=dict(schema='actual-git-original-parts-read-assignment-v1',publication=publication,plan_sha256=sha(plan_raw),
            actual_index_sha256=sha(index_raw),actual_index_git_blob=git_blob(index_raw),
            raw_total=raw_total,envelope_total=text_total,parts=162,assignments=by_phase,
            old_binary_read_state_modified=False,new_native_credit=False)
        target=HERE/'control/parts-assignment.json'
    raw=encode(report)
    with target.open('xb') as output:output.write(raw)
    print(json.dumps({'stage':args.stage,'status':'PASS_ACTUAL_GIT_PROVENANCE_AND_ASSIGNMENT','report':str(target),'sha256':sha(raw)}))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('stage',choices=['metadata','parts'])
    for name in ['plan','plan-sha256','prepared']:
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--desktop-index')
    run(parser.parse_args())
