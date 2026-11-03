"""One source/evidence packaging preparation, not a qualification or model run.

Writes only this newly created candidate. Preserve prior package trees. This
script is retained for provenance; never rerun it against a frozen package.
"""
import ast
import hashlib
import json
import os
from pathlib import Path
import resource
import time
import zipfile

ROOT = Path(__file__).absolute().parent
WS = ROOT.parent
DESIGN = WS / 'joint-product-six-capsule-design-v1'
H = lambda b: hashlib.sha256(b).hexdigest()
def enc(x): return (json.dumps(x, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('ascii')
def write(p,b):
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('xb') as f:f.write(b)


def main():
    start=time.monotonic(); cpu=time.process_time(); before=resource.getrusage(resource.RUSAGE_SELF)
    if (ROOT/'capsule-manifest.json').exists():raise FileExistsError('immutable prepared package already exists')
    inv=json.loads((DESIGN/'INVENTORY.json').read_bytes())
    assert H((DESIGN/'MANIFEST.json').read_bytes())=='d0dd53cfd0a747a0cd659eb063f3cc68761b7fe69bae2052595ad0d09c71df73'
    for p,h in json.loads((DESIGN/'MANIFEST.json').read_bytes()).items():assert H((DESIGN/p).read_bytes())==h
    assert H((DESIGN/'DESIGN_REVIEW.json').read_bytes())=='d3410c0b1b9a7fb2920fc316ca77c34ff07eae3b21a71422bfca6c43002088f7'
    blobs={}; roles={}; reads=0; read_bytes=0; hash_bytes=0
    def add(path,role,expected=None):
        nonlocal reads,read_bytes,hash_bytes
        if path in blobs:
            roles[path].add(role)
            if expected:
                assert len(blobs[path])==expected['bytes'] and H(blobs[path])==expected['sha256']
            return
        p=WS/path
        assert not p.is_symlink() and p.is_file()
        b=p.read_bytes();reads+=1;read_bytes+=len(b);hash_bytes+=len(b)
        if expected:assert len(b)==expected['bytes'] and H(b)==expected['sha256'],path
        blobs[path]=b;roles[path]={role}
    capsules={};closure={};frozen_count=0
    for c in inv['candidates']:
        name=c['candidate'];base=WS/name
        freeze=json.loads((base/'FREEZE.json').read_bytes())
        assert H((base/'FREEZE.json').read_bytes())==c['freeze_sha256']
        assert H((base/'INDEPENDENT_SAVED_REVIEW.json').read_bytes())==c['review_sha256']
        assert len(freeze)==c['frozen_files'];frozen_count+=len(freeze)
        source=[];imports={}
        for rel,dg in sorted(freeze.items()):
            path=name+'/'+rel;add(path,'frozen_source_or_metadata');assert H(blobs[path])==dg
            source.append(path)
            if rel.endswith('.py'):
                tree=ast.parse(blobs[path],filename=path)
                imports[rel]=sorted({(n.module or '') if isinstance(n,ast.ImportFrom) else a.name for n in ast.walk(tree) if isinstance(n,(ast.Import,ast.ImportFrom)) for a in (n.names if isinstance(n,ast.Import) else [None])})
        add(name+'/FREEZE.json','original_target_freeze');source.append(name+'/FREEZE.json')
        for rel in ('INDEPENDENT_SOURCE_REVIEW.json','INDEPENDENT_SAVED_REVIEW.json','COST_COVERAGE.json','SAVED_FINDINGS.md','RUN_ONCE/OUTER_WAIT4_RECEIPT.json'):
            add(name+'/'+rel,'copied_review_receipt_or_findings')
        inputs=json.loads((base/'INPUTS.json').read_bytes())['inputs']
        assert set(inputs)==set(c['inputs'])
        for value in inputs.values():add(value['path'],'runtime_input',value)
        paths=sorted(v['path'] for v in inputs.values())
        assert not set(source)&set(paths)
        capsules[name]={'source_files':sorted(source),'input_files':paths,'expanded_files':len(source)+len(paths),'expanded_bytes':sum(len(blobs[p]) for p in source+paths)}
        closure[name]={'entry':'run_once.py','original_freeze_sha256':c['freeze_sha256'],'frozen_files':len(freeze),'materialized_original_freeze':name+'/FREEZE.json','input_paths':paths,'AST_imports':imports,'supported_scope':'fixed run_once to supervisor/worker Fashion paths only; lazy multimodal_contract legacy serve API is excluded','external_prerequisites':['caller-supplied existing shared benchmark lock','compatible Python and NumPy','Linux flock/resource/fork/wait4/sched_setaffinity/proc facilities'],'prior_independent_static_review': 'joint-product-six-capsule-design-v1/PRIOR_DESIGN_REVIEW_64957cbe.json'}
    assert frozen_count==173
    assert len(inv['inputs'])==13 and sum(x['bytes'] for x in inv['inputs'].values())==1772664
    # Preserve every explicitly enumerated prior-failure item, not just a success summary.
    for name in ('joint-policy-delivery-candidate-v2','joint-policy-output-budget-outcome-candidate-v2'):
        old=json.loads(blobs[name+'/PRIOR_FAILURE.json'])
        entries=old['references'] if 'references' in old else [dict(path=k,**v) for k,v in old.items()]
        for item in entries:add(item['path'],'prior_failure_provenance',item)
    for p in sorted(DESIGN.iterdir()):
        if p.is_file():add(str(p.relative_to(WS)),'copied_design_provenance')
    copied_paths=set(blobs)
    omitted=[]; raw_totals={}
    receipt_paths=[p for p in blobs if p.endswith('/RUN_ONCE/OUTER_WAIT4_RECEIPT.json')]
    for path in sorted(receipt_paths):
        receipt=json.loads(blobs[path]);prefix=path.rsplit('/',1)[0]
        omitted_count=0; omitted_bytes=0
        for rel,meta in sorted(receipt['inventory'].items()):
            full=prefix+'/'+rel
            if full in copied_paths:
                assert len(blobs[full])==meta['bytes'] and H(blobs[full])==meta['sha256']
            else:
                omitted.append({'path':full,'bytes':meta['bytes'],'sha256':meta['sha256'],'authority':path,'reason':'raw runtime evidence not copied or revalidated; identity transcribed from exact copied outer receipt'})
                omitted_count+=1;omitted_bytes+=meta['bytes']
        raw_totals[prefix]={'receipt_inventory_files':len(receipt['inventory']),'omitted_files':omitted_count,'omitted_bytes':omitted_bytes}
    # Reference pins are catalogued without opening resources outside the fixed allowlist.
    reference_pins={}
    def refs(value):
        if isinstance(value,dict):
            if {'path','bytes','sha256'}<=set(value):reference_pins[value['path']]={'bytes':value['bytes'],'sha256':value['sha256']}
            for k,v in value.items():
                if isinstance(v,dict) and {'bytes','sha256'}<=set(v) and '/' in k:reference_pins[k]={'bytes':v['bytes'],'sha256':v['sha256']}
                refs(v)
        elif isinstance(value,list):
            for v in value:refs(v)
    for path,b in blobs.items():
        if path.endswith(('/REFERENCES.json','/PRIOR_FAILURE.json')):refs(json.loads(b))
    omitted_refs=[dict(path=p,**v,reason='historical reference only; not copied or read by packaging') for p,v in sorted(reference_pins.items()) if p not in copied_paths]
    write(ROOT/'OMITTED_RAW_EVIDENCE.json',enc({'scope':'Exact hash-only index copied from eight original outer receipts, plus explicit historical reference pins. No new raw-run audit or recursive historical closure claim. Copied runtime inputs are byte verified separately.','raw_archives':raw_totals,'omitted_raw_files':omitted,'other_omitted_references':omitted_refs}))
    write(ROOT/'SOURCE_CLOSURE_AUDIT.json',enc({'scope':'Static source/import census, no candidate imports/execution; detailed fixed-entry closure inspected in copied design review and original source reviews. Every target frozen member plus its original FREEZE and every INPUTS path is included. RUN outputs are created by future original runners, not package prerequisites.','capsules':closure,'all_frozen_entries':173,'legacy_surface_excluded':'multimodal_contract.to_legacy_request/dispatch lazy serve import; no arbitrary API closure claim','no_new_model_admission':True}))
    content=inv['oversize_inputs'][0]['path'];raw=blobs[content]
    import io
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        infos=z.infolist();assert len(infos)==78 and all(x.compress_type==0 and x.flag_bits==0 for x in infos)
        offsets=[i.header_offset for i in infos]+[z.start_dir,len(raw)]
        assert offsets[0]==0 and offsets[-2]==1555447 and len(raw)-z.start_dir==4960
    records=[]; stored={};entries=[]
    for index in range(79):
        a,b=offsets[index:index+2];part=raw[a:b];dg=H(part);hash_bytes+=len(part)
        assert len(part)<=401600
        records.append({'index':index,'offset':a,'bytes':len(part),'sha256':dg})
        stored['objects/'+dg+'.bin']=part
    assert len(records)==79 and records[-1]['bytes']==4960 and len(stored)==79
    for path,b in sorted(blobs.items()):
        dg=H(b);hash_bytes+=len(b)
        if path==content:storage={'kind':'raw-zip-records','records':records}
        else:
            loc='files/'+path;stored[loc]=b;storage={'kind':'whole-file','path':loc}
        entries.append({'path':path,'bytes':len(b),'sha256':dg,'storage':storage})
    for path,b in sorted(stored.items()):assert len(b)<=511999;write(ROOT/path,b)
    manifest={'schema':'joint-product-six-capsules-v1','capsules':capsules,'files':entries,'storage_files':len(stored),'storage_bytes':sum(map(len,stored.values()))}
    mb=enc(manifest);assert len(mb)<=511999;write(ROOT/'capsule-manifest.json',mb)
    expected={e['path']:[e['bytes'],e['sha256']] for e in entries}
    spec='"""Frozen exact scalar layout. Generated by prepare_package.py, no runtime I/O."""\n'
    for k,v in [('CAPSULES',capsules),('EXPECTED_FILES',expected),('EXPECTED_RECORDS',records),('MANIFEST_BYTES',len(mb)),('MANIFEST_SHA256',H(mb)),('STORAGE_BYTES',sum(map(len,stored.values()))),('STORAGE_FILES',len(stored)),('CONTENT_PATH',content)]:spec+=k+' = '+repr(v)+'\n'
    write(ROOT/'capsule_spec.py',spec.encode('ascii'))
    write(ROOT/'COPIED_PROVENANCE.json',enc({'files':[{'path':p,'roles':sorted(roles[p]),'bytes':len(blobs[p]),'sha256':H(blobs[p])} for p in sorted(blobs)],'copied_raw_scope':'six current complete outer receipts and every prior_failure pin; remaining raw run files are explicit hash-only references','source_freeze_entries':173,'target_freeze_files':6,'runtime_input_union_files':13,'runtime_input_union_bytes':1772664}))
    after=resource.getrusage(resource.RUSAGE_SELF)
    write(ROOT/'PREPARATION_COST.json',enc({'scope':'prepare_package.py measured prefix only; earlier manual source review, authoring, shell/tool startup and later freeze work are additional unmeasured cost, not zero','status':'PACKAGED_NOT_QUALIFIED','CPU_prefix_seconds':time.process_time()-cpu,'wall_prefix_seconds':time.monotonic()-start,'self_rusage_before':list(before),'self_rusage_prefix_after':list(after),'defined_read_scope':{'original_files_newly_loaded':reads,'bytes_loaded':read_bytes,'digest_bytes_accounted':hash_bytes,'excluded':'design preflight reads, repeated assertion hashes, AST work, metadata operations and later accounting are not included in these I/O byte counters'},'storage_writes_files':len(stored),'storage_writes_bytes':sum(map(len,stored.values())),'compression':'none; raw ZIP record slicing and exact byte copying only','CPU_tail':'unknown_not_zero','original_scientific_costs':'preserved, never reset/refunded'}))
    print(json.dumps({'manifest_sha256':H(mb),'manifest_bytes':len(mb),'stored_files':len(stored),'stored_bytes':sum(map(len,stored.values())),'original_entries':len(entries),'expanded_workspaces_bytes':sum(c['expanded_bytes'] for c in capsules.values()),'expanded_workspaces_files':sum(c['expanded_files'] for c in capsules.values())},sort_keys=True))

if __name__=='__main__':main()
