"""Cloud-only exact H1/H2/H3 byte readback, then the original H4 consumer.

Inputs are actual canonical base64 files fetched from a separately reviewed
immutable Git transport tree. This program performs no network operation and
does not manufacture Git/MCP responses or alter the old downloaders.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile
import time

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent.parent
PART_BYTES = 4194304
RAW_TOTAL = 670306272
EXPECTED_PARTS = 162
ROUTE = 'canonical-base64-no-newline-per-original-part'
TRANSPORT_PLAN_SHA = 'de5bf769089153d2bfd1fae468cf0af7942da442a9856acc120ee611757e5d5b'
MODULES = {
 'archive_reference.py':'ce96de09dc981311753d37312c1b254751cce3b40c4f950f603303a523508425',
 'h2_verify_download.py':'be74ed776c851401a6931676bfb78543ab9639ca90d9c0698633ee4ed71fcbda',
 'h3_verify_download.py':'46d74e053141c42b318e0202e315f0487a8c649883bdb83ee3b0434ddec32477'}
PHASES = {
 'H1':dict(completion_sha256='034f518dc2bd8fd350d2cb7a322056300051c538382370089104a727f6c1341b',
           archive_bytes=130746864,archive_sha256='7a374c980126ed29507e55f182705486c33889c73e58c285d83e7d1ff5618296',
           index_sha256='587c970101b93ee3ecfa8f8e12f855d1782669c80573376aa79ed0a20ab58865',
           parts=32,images=4,metadata_files=4,members=9,elf_bytes=774620584),
 'H2':dict(completion_sha256='d991a50f630e509278c20d5fe9f6ca0e53d1006852d954109d268375978407c1',
           archive_bytes=256132128,archive_sha256='f75c5d36596b84261ebc10705cd73de8abbe68eb87897413fcdb7e0cc92631a7',
           index_sha256='dab6061f0fa17e1403bf084314ca6c52b8bf4ece6b9b3d7ed5feb09143aa6e5f',
           parts=62,images=8,metadata_files=5,members=14,elf_bytes=1512251368),
 'H3':dict(completion_sha256='93d7bf08914054e4bcf05f17eea3cd5ef36fac9bbf0d1e601dda59084e758cd3',
           archive_bytes=283427280,archive_sha256='5365fcf900781044108e9642ae02a110e4ac8d031d9ee516c4f0b0e471e1e773',
           index_sha256='b023aca6ab2dccf4324dccab2e5319a00ef9b32773e0dc73127efc9af3caa002',
           parts=68,images=11,metadata_files=4,members=16,elf_bytes=1674575368)}
H4_COMPLETION_SHA = 'd3bda29c2ff27a18895e04ca672109298ca78bc9a9fd290d28a5d3db62930018'
FIRST_CHUNK_SHA = '94972dacc09426ec1d38fb0c2c131ed33599ef68cf35e594582d457fbe2e8a9d'
FIRST_RPC_SHA = '848b74130282a058b7b654ccfa56c139830716f8f9c48fb8a193d7def770f5cc'


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value,sort_keys=True,indent=2)+'\n').encode()


def git_blob(raw):
    return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()


def load_approved(name):
    path=HERE/'reused'/name
    raw=path.read_bytes()
    require(sha(raw)==MODULES[name],'reviewed source changed: '+name)
    spec=importlib.util.spec_from_file_location('readback_'+name.replace('.','_'),path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def raw_regular(core,path,maximum,expected_sha=None):
    source,before=core.open_regular(Path(path).absolute(),maximum)
    with source:
        raw=source.read(maximum+1)
        after=core.metadata(os.fstat(source.fileno()))
    require(before==after and len(raw)==before['bytes'],'actual input changed during read')
    require(expected_sha is None or sha(raw)==expected_sha,'actual input SHA differs: '+str(path))
    return raw


def write_fresh(path,raw):
    with path.open('xb') as output:
        require(output.write(raw)==len(raw),'short output write')
        output.flush();os.fsync(output.fileno())


def state_snapshot(core):
    """Observe old control files without creating or modifying any of them."""
    result={}
    roots=[WORKSPACE/'pq_recovery/h1-actual-elf-download',
           WORKSPACE/'w1/h2-actual-elf-download',WORKSPACE/'w1/h3-actual-elf-download']
    for root in roots:
        require((root/'PAUSE_REMOTE_READS').is_file(),'original downloader must remain explicitly paused')
        progress=json.loads(raw_regular(core,root/'progress.json',1024*1024))
        require(progress['status']=='PAUSED' and progress['in_flight']==0,
                'original downloader has an unresolved or active operation')
        for name in ('PAUSE_REMOTE_READS','progress.json','active-batch.json','version-pin.json'):
            path=root/name
            if path.exists():
                raw=raw_regular(core,path,1024*1024)
                result[str(path)]=dict(exists=True,bytes=len(raw),sha256=sha(raw))
            else:
                result[str(path)]=dict(exists=False)
    return result


def original_completions(core):
    values={}
    for phase,pin in PHASES.items():
        path=WORKSPACE/'w1'/(phase.lower()+'-elf-export')/(phase+'-export-completion.json')
        raw=raw_regular(core,path,65536,pin['completion_sha256'])
        value=json.loads(raw)
        require(value['phase']==phase and value['status']=='COMPLETE' and
                value['archive_bytes']==pin['archive_bytes'] and value['archive_sha256']==pin['archive_sha256'] and
                value['archive_index_sha256']==pin['index_sha256'] and value['total_actual_elf_bytes']==pin['elf_bytes'] and
                value['unique_actual_elfs']==pin['images'],'original completion identity differs')
        offset=0
        for number,row in enumerate(value['parts']):
            require(row['index']==number and row['offset']==offset and
                    row['name']==phase+'-actual-retained-elfs.tar.xz.part-'+str(number).zfill(4) and
                    0<row['bytes']<=PART_BYTES,'original part coverage/name differs')
            if number<len(value['parts'])-1:
                require(row['bytes']==PART_BYTES,'nonfinal original part extent differs')
            offset+=row['bytes']
        require(len(value['parts'])==pin['parts'] and offset==pin['archive_bytes'],'complete original part count differs')
        values[phase]=(value,raw)
    return values


def frozen_transport_plan(core,repository,destination,completions):
    raw=raw_regular(core,HERE/'frozen-transport-plan.json',1024*1024,TRANSPORT_PLAN_SHA)
    plan=json.loads(raw)
    require(plan['schema']=='actual-archive-orphan-git-transport-plan-v1' and plan['frozen'] is True and
            plan['repository']==repository and plan['destination_ref']==destination and plan['route']==ROUTE and
            plan['orphan_data_only'] is True and plan['expected_ref_before'] is None and
            plan['transport_tree_blob_count']==166,'actual frozen route plan identity differs')
    require(plan['limits']['max_part_raw_bytes']==PART_BYTES and plan['limits']['max_parts']==EXPECTED_PARTS and
            plan['limits']['total_raw_bytes']==RAW_TOTAL and plan['limits']['total_envelope_bytes']==893742124,
            'original frozen transport byte bounds differ')
    original={row['phase']:row for row in plan['archives']}
    require(len(plan['archives'])==len(original)==3 and set(original)==set(PHASES),'frozen phase set differs')
    for phase,(completion,completion_raw) in completions.items():
        row=original[phase]
        require(row['parts']==completion['parts'] and row['completion_bytes']==len(completion_raw) and
                row['completion_sha256']==PHASES[phase]['completion_sha256'] and
                row['source_commit']==completion['source_commit'] and row['source_tree']==completion['source_tree'] and
                row['archive_bytes']==completion['archive_bytes'] and row['archive_sha256']==completion['archive_sha256'] and
                row['archive_index_sha256']==completion['archive_index_sha256'] and
                row['original_native_outcome']==completion['original_run_outcome'] and
                row['capture_limits']==completion['capture_limits'],'frozen original archive/part/source scope differs')
    return raw,plan


def check_transport_index(core,root,expected_sha,expected_blob,repository,destination,completions,transport_plan):
    raw=raw_regular(core,root/'transport-index.json',1024*1024,expected_sha)
    require(git_blob(raw)==expected_blob,'transport index Git blob differs')
    index=json.loads(raw)
    require(index['schema']=='actual-archive-base64-git-transport-index-v1' and
            index['route']==ROUTE and index['repository']==repository and index['destination_ref']==destination and
            index['route_plan_sha256']==TRANSPORT_PLAN_SHA and
            index['orphan_data_only'] is True and index['source_or_native_qualification'] is False,
            'transport identity or scope differs')
    archive_rows={row['phase']:row for row in index['archives']}
    require(len(index['archives'])==len(archive_rows)==3 and set(archive_rows)==set(PHASES),'exact three archives required')
    rows={};expected_paths={'transport-index.json'}
    for phase,(completion,original_raw) in completions.items():
        archive=archive_rows[phase]
        name='archives/'+phase+'/'+phase+'-export-completion.json'
        require(archive['completion_path']==name and archive['completion_bytes']==len(original_raw) and
                archive['completion_sha256']==PHASES[phase]['completion_sha256'] and
                archive['archive_bytes']==completion['archive_bytes'] and archive['archive_sha256']==completion['archive_sha256'] and
                archive['archive_index_sha256']==completion['archive_index_sha256'] and
                archive['original_native_outcome']==completion['original_run_outcome'] and
                archive['capture_limits']==completion['capture_limits'],'transport archive/completion/outcome differs')
        require(raw_regular(core,root/name,65536,PHASES[phase]['completion_sha256'])==original_raw,
                'transport completion did not preserve original bytes')
        expected_paths.add(name)
    require(len(index['envelopes'])==EXPECTED_PARTS,'exact 162 original envelopes required')
    for envelope in index['envelopes']:
        phase=envelope['phase'];require(phase in PHASES,'unknown archive phase')
        part=envelope['original_part'];number=part['index']
        require(type(number) is int and 0<=number<len(completions[phase][0]['parts']),'part index outside original set')
        require(part==completions[phase][0]['parts'][number],'original part metadata was changed or resegmented')
        name='archives/'+phase+'/parts/'+part['name']+'.b64'
        require(envelope['transport_path']==name and (phase,number) not in rows and
                envelope['transport_bytes']==4*((part['bytes']+2)//3) and
                re.fullmatch('[0-9a-f]{64}',envelope['transport_sha256']) and
                re.fullmatch('[0-9a-f]{40}',envelope['transport_git_blob']), 'canonical one-to-one envelope differs')
        expected_paths.add(name);rows[(phase,number)]=envelope
    require(set(rows)=={(phase,n) for phase,pin in PHASES.items() for n in range(pin['parts'])},
            'missing or repeated original part')
    require(set(transport_plan['expected_transport_paths'])==expected_paths and
            len(transport_plan['expected_transport_paths'])==166 and
            sum(row['transport_bytes'] for row in rows.values())==transport_plan['limits']['total_envelope_bytes'],
            'actual payload set or encoded bytes differ from the frozen transport plan')
    actual_paths={str(path.relative_to(root)) for path in root.rglob('*') if path.is_file() or path.is_symlink()}
    require(actual_paths==expected_paths,'data-only input tree has missing or extra files')
    return raw,index,rows


def decode_and_assemble(core,phase,completion,root,rows,output):
    partdir=output/'parts';partdir.mkdir()
    decoded=[]
    for original in completion['parts']:
        row=rows[(phase,original['index'])]
        text=raw_regular(core,root/row['transport_path'],4*((PART_BYTES+2)//3),row['transport_sha256'])
        require(len(text)==row['transport_bytes'] and git_blob(text)==row['transport_git_blob'],
                'actual UTF8 envelope length/Git blob differs')
        raw=base64.b64decode(text,validate=True)
        require(base64.b64encode(raw)==text and b'\n' not in text and b'\r' not in text and
                len(raw)==original['bytes'] and sha(raw)==original['sha256'],
                'canonical actual decoded part differs')
        target=partdir/original['name'];write_fresh(target,raw)
        actual_hash,info=core.actual_hash(target,PART_BYTES,original['bytes'])
        require(actual_hash==original['sha256'],'actual written decoded part differs')
        decoded.append(dict(original_part=original,transport_path=row['transport_path'],
            actual_transport_sha256=sha(text),actual_transport_git_blob=git_blob(text),
            decoded_path=str(target),actual_decoded_metadata=info,
            origin='actual Git UTF8 payload; not a synthetic binary_read chunk receipt'))
    parts_report=core.verify_transport_parts(completion,partdir)
    name=PurePosixPath(completion['archive_path']).name
    temporary=output/(name+'.partial');final=output/name
    digest=hashlib.sha256();total=0
    with temporary.open('xb') as destination:
        for original in completion['parts']:
            raw=raw_regular(core,partdir/original['name'],PART_BYTES,original['sha256'])
            require(len(raw)==original['bytes'],'part extent changed before assembly')
            require(destination.write(raw)==len(raw),'short archive assembly write')
            digest.update(raw);total+=len(raw)
        destination.flush();os.fsync(destination.fileno())
    require(total==completion['archive_bytes'] and digest.hexdigest()==completion['archive_sha256'],
            'actual decoded part concatenation differs')
    core.publish_without_overwrite(temporary,final,completion['archive_bytes'],completion['archive_sha256'],completion['archive_bytes'])
    core.sync_directory(output)
    return final,dict(parts=decoded,parts_report=parts_report,archive=str(final),
                     archive_bytes=total,archive_sha256=digest.hexdigest())


def extract_and_bind(core,phase,spec,archive,output,h2,h3):
    pin=PHASES[phase]
    actual=core.read_verified_archive(str(archive),spec['archive_bytes'],spec['archive_sha256'],spec['archive_index_sha256'])
    index=actual['index'];index_raw=actual['small']['export-index.json']
    require(index['schema']=='hepta-actual-retained-elf-archive-index-v1' and index['phase']==phase and
            index['source_commit']==spec['source_commit'] and index['source_tree']==spec['source_tree'] and
            index['plan_sha256']==spec['plan_sha256'] and index['exporter_sha256']==spec['exporter_sha256'],
            'actual archive index identity differs')
    require(len(index['files'])==pin['images'] and len(index['embedded_metadata_files'])==pin['metadata_files'] and
            len(actual['members'])==pin['members'],'actual archive member count differs')
    expected={row['name']:{k:row[k] for k in ('bytes','sha256')} for row in index['files']}
    require(len(expected)==pin['images'],'duplicate actual ELF entry')
    require(not(set(expected)&set(index['embedded_metadata_files'])),'ELF/metadata name collision')
    expected.update(index['embedded_metadata_files'])
    expected['export-index.json']=dict(bytes=len(index_raw),sha256=sha(index_raw))
    core.verify_member_inventory(actual['members'],expected)
    require(sum(row['bytes'] for row in index['files'])==pin['elf_bytes'] and
            index['original_run_outcome']==spec['original_run_outcome'] and index['native_reexecution'] is False and
            index['capture_limits']==spec['capture_limits'],'original native outcome/scope differs')
    for row in index['files']:
        require(row['name']==phase+'/elf/'+row['sha256']+'.elf' and
                actual['members'][row['name']]['elf_magic'] is True,'actual complete image ELF identity differs')
    staging=output/'extracted.partial';staging.mkdir(mode=0o700)
    # The earlier pass hashed every actual member. This second streaming pass
    # checks every written byte against those exact hashes, like the reviewed
    # original assemble_extract functions, without invoking downloader state.
    written={}
    with tarfile.open(archive,'r|xz') as stream:
        for member in stream:
            relative=PurePosixPath(member.name)
            require(member.isfile() and not relative.is_absolute() and '..' not in relative.parts and
                    relative.as_posix()==member.name and member.name in expected and member.name not in written,
                    'unsafe, repeated, or unexpected extraction member')
            require(member.size==expected[member.name]['bytes'],'member size changed before extraction')
            target=staging.joinpath(*relative.parts);target.parent.mkdir(parents=True,exist_ok=True)
            total=0;digest=hashlib.sha256()
            with stream.extractfile(member) as source,target.open('xb') as destination:
                while True:
                    block=source.read(1024*1024)
                    if not block:break
                    total+=len(block);require(total<=member.size,'member grew')
                    require(destination.write(block)==len(block),'short member write');digest.update(block)
                destination.flush();os.fsync(destination.fileno())
            require(total==member.size and digest.hexdigest()==expected[member.name]['sha256'],'streamed member differs')
            reread,meta=core.actual_hash(target,member.size,member.size)
            require(reread==digest.hexdigest(),'actual written member differs')
            written[member.name]=dict(bytes=total,sha256=reread)
    require(written==expected,'written original member set differs')
    final_archive_sha,_=core.actual_hash(archive,spec['archive_bytes'],spec['archive_bytes'],actual['metadata'])
    require(final_archive_sha==spec['archive_sha256'],'archive changed during extraction')
    plan_raw=raw_regular(core,staging/'export-plan.json',2*1024*1024,spec['plan_sha256'])
    plan=json.loads(plan_raw)
    require(raw_regular(core,staging/'exporter.py',2*1024*1024,spec['exporter_sha256']) and
            raw_regular(core,staging/'owned-release-proof.json',1024*1024,spec['release_proof_sha256']),
            'original embedded code/release missing')
    original=raw_regular(core,staging/(phase+'/original-source-map.json'),1024*1024,plan['source_map']['sha256'])
    require(len(original)==plan['source_map']['bytes'] and
            base64.b64decode(plan['source_map']['data_base64'],validate=True)==original and
            plan['original_run_outcome']==index['original_run_outcome'],'exact original map/outcome bytes differ')
    planned={row['name']:row for row in plan['files']}
    require(len(planned)==pin['images'],'original plan image count differs')
    for row in index['files']:
        require(row['name'] in planned and all(row.get(k)==v for k,v in planned[row['name']].items()) and
                row['second_read_sha256']==row['sha256'] and row['first_read_metadata']==row['second_read_metadata'] and
                row['other_aliases_reopened_by_this_export'] is False,'original image observations/alias scope differs')
    if phase=='H2':
        scope=h2.verify_partial_representation(spec,index,staging)
        require(scope['bytes']==314572800 and scope['sha256']=='b9dc995ee3e6e623056a2563ab8aed3629c003a418b28486ac09db914a0b3f8d' and
                scope['complete_executable'] is False and scope['completed_process_binding'] is False and
                scope['native_evidence_credit'] is False,'H2 partial prefix gained invalid credit')
    elif phase=='H3':
        scope=h3.verify_complete_image_binding(spec,index,staging)
    else:
        scope=dict(original_native_outcome=index['original_run_outcome'],capture_limits=index['capture_limits'],
                   missing_individual_captures_filled=False,all_aliases_preserved_in_original_map=True)
    final=output/'extracted';staging.rename(final);core.sync_directory(output)
    return dict(phase=phase,archive=str(archive),original_completion_sha256=pin['completion_sha256'],
        actual_index_sha256=sha(index_raw),members=written,actual_member_bytes=sum(v['bytes'] for v in written.values()),
        actual_ELF_bytes=pin['elf_bytes'],original_native_outcome=index['original_run_outcome'],scope=scope,
        extraction_directory=str(final),new_native_or_capture_credit=False)


def compare_first_h1_range(core,archive):
    old=WORKSPACE/'pq_recovery/h1-actual-elf-download/chunks'
    chunk=raw_regular(core,old/'000000000.bin',65536,FIRST_CHUNK_SHA)
    rpc=raw_regular(core,old/'000000000.rpc.json',2*1024*1024,FIRST_RPC_SHA)
    request=raw_regular(core,old/'000000000.request.json',65536)
    verified=json.loads(raw_regular(core,old/'000000000.verified.json',65536))
    require(len(chunk)==65536 and verified['chunk_sha256']==FIRST_CHUNK_SHA and
            verified['rpc_sha256']==FIRST_RPC_SHA,'previous actual first chunk identity differs')
    source,before=core.open_regular(archive,PHASES['H1']['archive_bytes'],PHASES['H1']['archive_bytes'])
    with source:
        current=source.read(65536);after=core.metadata(os.fstat(source.fileno()))
    require(before==after and current==chunk,'actual new Git-route range differs from original binary_read range')
    return dict(bytes=65536,offset=0,sha256=sha(current),actual_previous_bin=str(old/'000000000.bin'),
        actual_previous_rpc_sha256=sha(rpc),original_request_sha256=sha(request),
        actual_byte_equality=True,new_binary_read_receipt_fabricated=False)


def run(args):
    start=time.monotonic()
    core=load_approved('archive_reference.py')
    h2=load_approved('h2_verify_download.py');h3=load_approved('h3_verify_download.py')
    state_before=state_snapshot(core)
    root=Path(args.transport_root).absolute()
    require(root.resolve(strict=True)==root,'canonical complete transport data root required')
    require(re.fullmatch('[0-9a-f]{40}',args.transport_commit) and re.fullmatch('[0-9a-f]{40}',args.transport_tree),
            'full caller-reviewed immutable Git identities required')
    provenance=raw_regular(core,Path(args.fetch_receipts_manifest).absolute(),32*1024*1024,args.expected_fetch_receipts_sha256)
    completions=original_completions(core)
    transport_plan_raw,transport_plan=frozen_transport_plan(core,args.repository,args.destination_ref,completions)
    index_raw,index,rows=check_transport_index(core,root,args.expected_index_sha256,args.expected_index_git_blob,
                                              args.repository,args.destination_ref,completions,transport_plan)
    output=Path(args.output).absolute()
    require(output.parent.resolve(strict=True)==output.parent and not output.exists(),'fresh canonical output required')
    output.mkdir(mode=0o700)
    write_fresh(output/'original-frozen-transport-plan.json',transport_plan_raw)
    write_fresh(output/'original-transport-index.json',index_raw)
    write_fresh(output/'original-fetch-receipts-manifest',provenance)
    phase_results={};raw_total=0
    for phase,(completion,raw) in completions.items():
        own=output/phase;own.mkdir()
        write_fresh(own/(phase+'-export-completion.json'),raw)
        archive,transport=decode_and_assemble(core,phase,completion,root,rows,own)
        verified=extract_and_bind(core,phase,completion,archive,own,h2,h3)
        if phase=='H1':
            verified['previous_actual_binary_read_first_range']=compare_first_h1_range(core,archive)
        verified['transport']=transport
        write_fresh(own/'readback-verification.json',encoded(verified))
        phase_results[phase]=verified;raw_total+=completion['archive_bytes']
        print(json.dumps({'phase':phase,'status':'ACTUAL_ORIGINAL_ARCHIVE_BYTES_VERIFIED',
                          'archive_bytes':completion['archive_bytes'],'members':len(verified['members'])}),flush=True)
    require(raw_total==RAW_TOTAL,'combined original archive byte total differs')
    h4=WORKSPACE/'w1/h4-reference-export'
    full_dependency=core.consume(
        output/'H3/H3-actual-retained-elfs.tar.xz',output/'H3/H3-export-completion.json',output/'H3/parts',
        h4/'H4-actual-retained-image-references.tar.xz',h4/'H4-export-completion.json',h4/'H4-child-parts',
        H4_COMPLETION_SHA,MODULES['archive_reference.py'])
    require(full_dependency['status']=='VERIFIED_COMPLETE_BYTE_CLOSURE','H4 actual dependent consumer did not close')
    write_fresh(output/'H4-full-dependent-consumer.json',encoded(full_dependency))
    state_after=state_snapshot(core)
    require(state_before==state_after,'old paused downloader state changed')
    result=dict(schema='unified-actual-archive-byte-readback-v1',status='VERIFIED_ORIGINAL_H1_H2_H3_AND_DEPENDENT_H4_BYTES',
        elapsed_seconds=time.monotonic()-start,transport_route=ROUTE,repository=args.repository,
        caller_reviewed_transport_commit=args.transport_commit,caller_reviewed_transport_tree=args.transport_tree,
        actual_transport_index_sha256=sha(index_raw),actual_transport_index_git_blob=git_blob(index_raw),
        original_frozen_transport_plan_sha256=sha(transport_plan_raw),
        referenced_fetch_receipts_manifest_sha256=sha(provenance),
        Git_network_or_credential_authentication_performed=False,
        Git_provenance_scope='Caller-reviewed immutable fetch-receipt manifest retained verbatim; this verifier checks local payload/Git-blob/archive byte identities and does not authenticate a network response.',
        actual_original_parts=EXPECTED_PARTS,actual_original_archive_bytes=raw_total,
        phases=phase_results,H4_dependency_consumer=full_dependency,
        original_downloader_state_before=state_before,original_downloader_state_after=state_after,
        old_binary_read_progress_changed=False,new_binary_read_receipts_created=False,
        native_reexecution=False,new_native_or_capture_credit=False,
        H2_second_process_complete_binding=False,originals_deleted_or_replaced=False)
    write_fresh(output/'completion.json',encoded(result));core.sync_directory(output)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('transport-root','expected-index-sha256','expected-index-git-blob','repository','destination-ref',
                 'transport-commit','transport-tree','fetch-receipts-manifest','expected-fetch-receipts-sha256','output'):
        parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    result=run(args)
    print(json.dumps({'status':result['status'],'elapsed_seconds':result['elapsed_seconds'],
                      'archive_bytes':result['actual_original_archive_bytes'],'parts':result['actual_original_parts']}),flush=True)


if __name__=='__main__':
    main()
