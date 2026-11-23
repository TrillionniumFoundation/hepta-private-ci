"""Replay original registration and named source guards with the candidate present."""
import io, json, sys, unittest
from pathlib import Path
root=Path(sys.argv[1]).resolve()
qa=root/'qa/b4-no-bypass'
sys.path[:0]=[str(root/'scripts'),str(qa)]
import verify_hepta_callers as callers
manifest=callers._load_manifest(root/'CALLERS.toml')
rows=callers._verify_protected_files(root,manifest)
assert len(rows)==826 and len(manifest['boundary'])==1652
suites=['test_original_learning_owner_source_closure','test_successor_historical_client_source_closure']
result={}
for name in suites:
    suite=unittest.defaultTestLoader.loadTestsFromName(name)
    trace=io.StringIO()
    run=unittest.TextTestRunner(stream=trace,verbosity=2).run(suite)
    if not run.wasSuccessful(): raise RuntimeError(trace.getvalue())
    result[name]=run.testsRun
print(json.dumps({'protected':len(rows),'boundary':len(manifest['boundary']),'suites':result},sort_keys=True,indent=2))
