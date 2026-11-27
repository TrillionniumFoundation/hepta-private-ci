import hashlib,json
from pathlib import Path
base=Path('/home/qian-qi/hepta-hcsn-localization-v2-20261108-v1')
manifest=json.loads((base/'source-manifest.json').read_text())
actual={name:hashlib.sha256((base/'source'/name).read_bytes()).hexdigest() for name in manifest['files']}
result={'schema':'localization-v2-complete-source-read-audit-v1','source_file_count':len(actual),'expected_source_sha256':manifest['files'],'actual_source_sha256':actual,'unchanged':actual==manifest['files'],'source_zip_sha256':hashlib.sha256((base/'source.zip').read_bytes()).hexdigest(),'training_or_model_forwards':0}
assert result['source_file_count']==36 and result['unchanged']
assert result['source_zip_sha256']==manifest['archive_sha256']=='d5d745c839204512ca53d617a7d2dbb84dad94e0de13d382174f67bbd8e59c82'
out=base/'interface-001-audit/all-source-audit.json'
with out.open('x') as f:f.write(json.dumps(result,indent=2,sort_keys=True)+'\n')
print(json.dumps({'path':str(out),'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'unchanged':result['unchanged'],'source_file_count':len(actual)}))
