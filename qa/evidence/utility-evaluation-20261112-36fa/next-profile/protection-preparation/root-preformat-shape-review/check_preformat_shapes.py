from pathlib import Path
import importlib.util,sys,json,hashlib
sys.dont_write_bytecode=True
ROOT=Path('/tmp/hepta-36fa-root-postformat-review')
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    obj=importlib.util.module_from_spec(spec);sys.modules[name]=obj;spec.loader.exec_module(obj);return obj
ext=module('root_preformat_proposal_shapes',ROOT/'extract_postformat.py')
proof=module('root_exact_callers_for_shapes',ROOT/'source/scripts/verify_hepta_callers.py')
plan=json.loads((ROOT/'plan.json').read_bytes())
source={p:(ROOT/'source'/p).read_text() for p in {r['path'] for r in plan['rows']}}
def mask(s):return proof._strip_cfg_test_items(proof._strip_rust_non_code(s))
masked={p:mask(s) for p,s in source.items()}
report={'scope':'PREPARATION shape functions only on exact unformatted 86dd; main, maintenance, verifier, QA and Rust gates not run','extractor_git_blob':'f8686d5986f0f21404621d7e2d6a78634dc3f578','passed_selectors':0,'passed_literals':0,'passed_mounts':0,'rejected_same_length_literal_with_decoys':0,'failures':[]}
for row in plan['rows']:
    for selector in row['selectors']:
        try: ext.select_scope(proof,masked[row['path']],selector);report['passed_selectors']+=1
        except Exception as e:report['failures'].append({'row':row['id'],'selector':selector,'error':repr(e)})
for spec in plan['critical_literals']:
    p=spec['path'];raw=source[p]
    try:
        span=ext.literal_span(proof,masked[p],raw,spec);report['passed_literals']+=1
        token=raw[span['start']:span['end']];offset=token.index('"')+1
        replacement='x' if token[offset]!='x' else 'y'
        mutated=raw[:span['start']]+token[:offset]+replacement+token[offset+1:]+raw[span['end']:]
        mutated+='\n// preserved decoy '+token+'\nfn unrelated_literal_decoy() { let _unused = '+token+'; }\n'
        try: ext.literal_span(proof,mask(mutated),mutated,spec)
        except ext.PreconditionRejected:report['rejected_same_length_literal_with_decoys']+=1
        else:report['failures'].append({'literal':spec,'error':'accepted mutated actual literal with decoys'})
    except Exception as e:report['failures'].append({'literal':spec,'error':repr(e)})
for spec in plan['module_mounts']:
    p=spec['parent']
    try:ext.mount_span(proof,masked[p],source[p],spec);report['passed_mounts']+=1
    except Exception as e:report['failures'].append({'mount':spec,'error':repr(e)})
(ROOT/'preformat_shape_review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False))
