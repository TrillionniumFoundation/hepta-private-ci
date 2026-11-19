"""One authorized manager exposure, never a model-development entrypoint."""
import json
import os
from pathlib import Path
import partition as p

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'RUN_ONCE'
CATEGORIES = frozenset(('compressed_cap','source_identity','gzip','decoded_cap','gzip_boundary','newline','row_count','row_length','integer_csv','range','conflicting_group','minimum_groups','output_cap','artifact_set','output_directory','artifact_type','artifact_cap','completion_json','completion_schema','binding_schema','binding_mismatch','documentary_identity','io_failure','resource_failure','internal_failure'))

def write_result(value):
    raw = p.encode_json(value)
    if len(raw) > 16384:
        raise p.Reject('output_cap')
    with (OUT / 'RESULT.json').open('xb') as f:
        f.write(raw); f.flush(); os.fsync(f.fileno())

def run():
    inputs = json.loads((ROOT / 'INPUTS.json').read_bytes())
    result = {'source': inputs['source'], 'passed': False, 'category': 'internal_failure'}
    try:
        for doc in inputs['documentary_pins']:
            with open(doc['path'], 'rb') as f:
                raw = f.read(2*1024*1024+1)
            if len(raw)>2*1024*1024 or p.sha(raw)!=doc['sha256']:
                raise p.Reject('documentary_identity')
        with open(inputs['source']['path'], 'rb') as f:
            blob = f.read(p.MAX_COMPRESSED + 1)
        files = p.build(blob, p.REAL)
        marker = p.encode_json({n:{'bytes':len(b),'sha256':p.sha(b)} for n,b in sorted(files.items())})
        # Reserve 64 KiB for RESULT and terminal parent receipt.
        if sum(map(len, files.values())) + len(marker) > p.MAX_OUTPUT-65536:
            raise p.Reject('output_cap')
        p.publish(files, OUT / 'private_manager')
        p.verify_complete(OUT / 'private_manager')
        result.update(passed=True, category='complete', aggregate=json.loads(files['PUBLIC_RECEIPT.json']), attribution=inputs['attribution'])
    except p.Reject as exc:
        result['category'] = exc.args[0] if len(exc.args)==1 and exc.args[0] in CATEGORIES else 'internal_failure'
    except OSError:
        result['category'] = 'io_failure'
    except MemoryError:
        result['category'] = 'resource_failure'
    except BaseException:
        result['category'] = 'internal_failure'
    write_result(result)
    return 0 if result['passed'] else 1
