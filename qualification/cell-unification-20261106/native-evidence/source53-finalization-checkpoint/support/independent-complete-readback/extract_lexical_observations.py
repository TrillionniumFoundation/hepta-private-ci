"""Reproduce the stored patch-derived lexical observations; data analysis only."""
import argparse
import json
import tarfile
from pathlib import Path

from source_compare import apply_section, lexical_deltas, parse_patch, pin, python_ast_readback, require

parser=argparse.ArgumentParser()
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
evidence=Path('native-validation-results/source53-finalization-closed/evidence')
patch=(evidence/'format-only.patch').read_bytes()
sections=parse_patch(patch)
with tarfile.open('native-validation-results/r31-archive-closed/checkpoint-r31-closed.tar.gz','r:gz') as archive:
    before={s['path']:archive.extractfile('source/'+s['path']).read() for s in sections}
results=[]
for section in sections:
    path=section['path'];after=apply_section(before[path],section)
    require(pin(after)['git_blob']==section['after_blob'],'derived after blob')
    review=python_ast_readback(before[path],after) if path.endswith('.py') else lexical_deltas(before[path],after)
    results.append({'path':path,'before':pin(before[path]),'after_derived_from_original_patch':pin(after),'review':review})
output={'schema':'hepta.finalization-independent-patch-lexical-observations.v1',
        'source_origin':'Original R31 archive before bytes plus exact native format-only.patch; final archive raw readback not yet claimed',
        'patch':pin(patch),'files':results,'raw_final_snapshot_verified':False,'project_code_imported_or_executed':False}
raw=(json.dumps(output,indent=2,ensure_ascii=False)+'\n').encode()
with args.output.open('xb') as handle:handle.write(raw)
print(json.dumps({'path':str(args.output),**pin(raw)}))
