#!/usr/bin/env python3
"""Independent line weaving of four frozen entry files; no project execution."""
import difflib
import hashlib
import json
import re
from pathlib import Path

OUT=Path(__file__).resolve().parent
V3=Path('/tmp/hepta-36fa-root-product-composition-v3')
V2=Path('/tmp/hepta-36fa-root-product-composition-v2')
E2=Path('/tmp/hepta-36fa-root-product-e2-proposal-v1/ordinary-handoff-layer-v1')
E3=Path('/tmp/hepta-36fa-root-product-e3-proposal-v1/late-enrollment-layer-v1')
EXPLICIT=Path('/tmp/hepta-36fa-root-product-e3-proposal-v1/explicit-callers-increment-v1')
P='codex-rs/hepta-agentd/src/'
def pin(raw):
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}
def raw(path):
    path=Path(path); a=path.stat(); value=path.read_bytes(); b=path.stat()
    assert (a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns,a.st_ctime_ns)==(b.st_dev,b.st_ino,b.st_size,b.st_mtime_ns,b.st_ctime_ns)
    return value
def load_packet(folder,sha):
    data=raw(folder/'SOURCE_PACKET.json'); assert pin(data)['git_blob']==sha
    obj=json.loads(data); entries={e['path']:e for e in obj['entries']}
    assert len(entries)==len(obj['entries'])
    for e in entries.values():
        assert pin(e['after_utf8'].encode())==e['after']
        if e['before'] is not None: assert pin(e['before_utf8'].encode())==e['before']
    return entries,{'path':str(folder/'SOURCE_PACKET.json'),**pin(data)}
left,lpin=load_packet(E3,'388bfb3f3ab70e5f39d847c26d2d48daa2c7ead1')
right,rpin=load_packet(E2,'65e62f807885cd890d8fa9944c58e232dc55ae01')
explicit,epin=load_packet(EXPLICIT,'f1306c1243c83a758385cb592710e4fd30010a78')
review_raw=raw(V3/'PREQUALIFICATION_COMPOSITION_REVIEW.json')
assert pin(review_raw)=={'bytes':78780,'sha256':'0202156c9cda660305df3245a767ee247a9307e1320d6173dbe2dd92ef95842d','git_blob':'0f4c064a865c44a648e8e8b6c3f6e0b5741ae744'}
review=json.loads(review_raw)
expected={e['path']:e['after'] for e in review['files']}
previous_raw=raw(V2/'PREQUALIFICATION_COMPOSITION_REVIEW.json')
assert pin(previous_raw)['git_blob']=='6685e7b5fe7ff2c52f50e9ce936967702838b195'
previous=json.loads(previous_raw)
previous_files={e['path']:e for e in previous['files']}

def changes(before,after):
    a=before.splitlines(True); b=after.splitlines(True)
    return {(i,j):b[k:l] for kind,i,j,k,l in difflib.SequenceMatcher(a=a,b=b,autojunk=False).get_opcodes() if kind!='equal'}

reports=[]
for name in ['production_launcher.rs','production_launcher_inputs.rs']:
    path=P+name; a=left[path]; b=right[path]
    assert a['before_utf8']==b['before_utf8'] and a['before']==b['before']
    base=a['before_utf8']; lines=base.splitlines(True)
    e3=changes(base,a['after_utf8']); e2=changes(base,b['after_utf8'])
    edits={}; simultaneous=[]
    for interval in sorted(set(e3)|set(e2)):
        start,end=interval
        if interval in e3 and interval in e2:
            if start==end:
                edits[interval]=e3[interval]+e2[interval]
                simultaneous.append({'line_boundary':start,'E3_insert':''.join(e3[interval]),'E2_insert':''.join(e2[interval])})
            else:
                assert name=='production_launcher_inputs.rs'
                assert lines[start:end]==['const FLAGS: [&str; 19] = [\n']
                assert e3[interval]==e2[interval]==['const FLAGS: [&str; 20] = [\n']
                edits[interval]=['const FLAGS: [&str; 21] = [\n']
        else: edits[interval]=e3.get(interval,e2.get(interval))
    intervals=sorted(edits)
    for i,(a0,a1) in enumerate(intervals):
        for b0,b1 in intervals[i+1:]:
            assert a1<=b0, (name,(a0,a1),(b0,b1))
    output=[]; cursor=0
    for (start,end), replacement in sorted(edits.items()):
        output.extend(lines[cursor:start]); output.extend(replacement); cursor=end
    output.extend(lines[cursor:]); rebuilt=''.join(output).encode()
    actual=raw(V3/'after'/path)
    assert rebuilt==actual and pin(actual)==expected[path]
    reports.append({'path':path,'base':a['before'],'E3':a['after'],'E2':b['after'],'composed':pin(actual),
                    'independently_woven_exact':True,'coincident_insertions':simultaneous,
                    'only_noninsert_overlap':'FLAGS 19 -> 20 + 20 explicitly composed to 21' if name.endswith('_inputs.rs') else None})

libpath=P+'lib.rs'
before_v2=raw(V2/'after'/libpath)
assert pin(before_v2)==previous_files[libpath]['after']
lib3=left[libpath]
assert lib3['after_utf8'].startswith(lib3['before_utf8'])
suffix=lib3['after_utf8'][len(lib3['before_utf8']):]
assert suffix.count('pub use authority_host_runtime::')==4
lib=before_v2.decode()+suffix
splices=json.loads(raw(E2/'EXACT_SOURCE_SPLICES.json'))
libops=[x for x in splices if x['path']==libpath]
assert len(libops)==2
for x in libops:
    assert lib.count(x['before'])==1
    lib=lib.replace(x['before'],x['after'],1)
assert lib.encode()==raw(V3/'after'/libpath)
assert pin(lib.encode())==expected[libpath]
undone=lib
for x in reversed(libops):
    assert undone.count(x['after'])==1
    undone=undone.replace(x['after'],x['before'],1)
assert undone.endswith(suffix) and undone[:-len(suffix)].encode()==before_v2
reports.append({'path':libpath,'previous_v2':pin(before_v2),'E3_added_suffix':pin(suffix.encode()),
                'E2_splices':libops,'composed':pin(lib.encode()),'complete_inverse_equal':True})
mainpath=P+'main.rs'
main=raw(V3/'after'/mainpath)
assert main==right[mainpath]['after_utf8'].encode() and pin(main)==expected[mainpath]
reports.append({'path':mainpath,'before':right[mainpath]['before'],'composed':pin(main),'exact_E2_after':True})

# Explicit caller follow-up changes spelling only, including the same service
# owner, child cancellation token and original borrowed enrollment receiver.
explicit_splices=json.loads(raw(EXPLICIT/'EXACT_SOURCE_SPLICES.json'))
explicit_proof=[]
for path,entry in explicit.items():
    value=entry['before_utf8']; ops=[x for x in explicit_splices if x['path']==path]
    assert len(ops)==1
    for op in ops:
        assert value.count(op['before_text'])==1
        value=value.replace(op['before_text'],op['after_text'],1)
    assert value==entry['after_utf8']
    actual=raw(V3/'after'/path)
    assert actual==value.encode() and pin(actual)==expected[path]
    for op in reversed(ops):
        assert value.count(op['after_text'])==1
        value=value.replace(op['after_text'],op['before_text'],1)
    assert value==entry['before_utf8']
    explicit_proof.append({'path':path,'before':entry['before'],'after':entry['after'],'exact_inverse':True})

inputs=raw(V3/'after'/P/'production_launcher_inputs.rs').decode()
flag_body=inputs.split('const FLAGS: [&str; 21] = [\n',1)[1].split('];',1)[0]
flags=re.findall(r'"([^"]+)"',flag_body)
assert len(flags)==len(set(flags))==21
old_flags=re.findall(r'"([^"]+)"',right[P+'production_launcher_inputs.rs']['before_utf8'].split('const FLAGS: [&str; 19] = [\n',1)[1].split('];',1)[0])
assert set(flags)==set(old_flags)|{'--root-original-task-handoff-fd','--root-resident-learning-handoff-fd'}
numbers=inputs.split('let numbers = [\n',1)[1].split(']\n',1)[0]
fd_numbers=[x.strip().rstrip(',') for x in numbers.splitlines() if x.strip()]
assert len(fd_numbers)==len(set(fd_numbers))==14
assert 'original_task_handoff' in fd_numbers and 'resident_handoff' in fd_numbers
assert inputs.index('collect::<BTreeSet<_>>().len() != numbers.len()') < inputs.index('let handoff = UnixDatagram::from(take_descriptor(handoff)?);')
assert inputs.index('resident_handoff.is_some() && learning_handoff.is_some()') < inputs.index('let numbers = [')
launch=raw(V3/'after'/P/'production_launcher.rs').decode()
assert launch.index('drop_to_owner()?')<launch.index('receive_root_original_task_handoff(')
assert main.index(b'install_original_root_task(config).await?')<main.index(b'launch.run(config, arg0_paths).await?')
assert launch.index('original_task_handoff.is_some()')<launch.index('resident_enrollment::run_original(')
assert launch.index('inputs.resident_end = inputs.resident_handoff.as_ref().map(|_| session_end);')<launch.index('resident_enrollment::run_original(')
for name in ['RootOriginalTaskHandoffV1','receive_root_original_task_handoff',
             'RootResidentCandidateEnrollmentInputsV3','RootResidentCandidateEnrollmentServiceV3',
             'prepare_host_resident_candidate_enrollment_v3','recover_host_resident_candidate_enrollment_v3']:
    assert re.search(r'#\[cfg\(target_os = "linux"\)\]\npub use [^;]*\b'+name+r';',lib),name

result={'format':'hepta-e2-e3-v3-shared-entry-independent-byte-proof-v1',
 'root_composition_review':{'path':str(V3/'PREQUALIFICATION_COMPOSITION_REVIEW.json'),**pin(review_raw)},
 'input_packets':[lpin,rpin,epin],'four_files':reports,
 'explicit_caller_dependencies':explicit_proof,
 'flag_names':flags,'fd_numbers':fd_numbers,
 'all_fd_distinct_check_precedes_any_take':True,'legacy_v1_and_resident_v3_exclusion_preserved':True,
 'task_install_before_launch_run_and_enrollment':True,'both_new_exports_and_existing_cfg_scope_preserved':True,
 'scope':'Four shared entry files plus five spelling-only dependency mappings. No full79 semantic review claim.',
 'not_performed':['project imports','formatter','compiler','tests','QA','H','source Git/ref changes']}
out=(json.dumps(result,indent=2,sort_keys=True)+'\n').encode()
(OUT/'BYTE_COMPOSITION_REVIEW.json').open('xb').write(out)
print(json.dumps({'result':'complete','report':str(OUT/'BYTE_COMPOSITION_REVIEW.json'),**pin(out),'flags':len(flags),'fd_number_slots':len(fd_numbers)}))
