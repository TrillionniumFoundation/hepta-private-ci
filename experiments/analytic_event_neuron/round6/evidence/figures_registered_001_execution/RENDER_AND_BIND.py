"""Render fixed summary with separate provenance and complete invocation cost."""
from datetime import datetime,timezone
import importlib.util,json,os
from pathlib import Path
BASE=Path('/dev/shm/hepta-round6-d831a963ef2f')
ROUND=BASE/'hepta-analytic/experiments/analytic_event_neuron/round6'
RESULTS=ROUND/'evidence/registered_001/RESULTS.json'
SCRIPT=ROUND/'render_results.py'
OUT=ROUND/'evidence/figures_registered_001'
RECORDS=ROUND/'evidence/figures_registered_001_execution'
EXPECTED_RESULTS='303e98b4c6679f7dd827bb2c3a7083d96010984adbba43e1c6548b7930f53a69'
EXPECTED_RENDERER='71b034e42678273187c8b87aff94f5063d9ff59858c91d98b82f8a72e4fe161b'
spec=importlib.util.spec_from_file_location('render_frozen_results',SCRIPT)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def write(name,value):
    with (RECORDS/name).open('x') as stream:
        json.dump(value,stream,sort_keys=True,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
before={'results_sha256':m.sha(RESULTS),'renderer_sha256':m.sha(SCRIPT)}
assert before=={'results_sha256':EXPECTED_RESULTS,'renderer_sha256':EXPECTED_RENDERER},before
write('SOURCE_BEFORE.json',{'schema':'hepta.frozen-figure.before.v6','created_utc':datetime.now(timezone.utc).isoformat(),**before})
try:
    rendered=m.render(RESULTS,OUT)
    after={'results_sha256':m.sha(RESULTS),'renderer_sha256':m.sha(SCRIPT)}
    assert after==before,'Source changed while rendering'
    assert set(rendered['figures'])=={'utility_and_calibration.png','utility_and_calibration.svg'}
    assert rendered['results_sha256']==EXPECTED_RESULTS
    final={'schema':'hepta.frozen-figure.rendering.v6','passed':True,'created_utc':datetime.now(timezone.utc).isoformat(),
           'identities_before':before,'identities_after':after,'figure_source_sha256':m.sha(OUT/'FIGURE_SOURCE.json'),
           'figures':rendered['figures'],'statistical_or_training_execution':False,'registered_run_written':False}
    write('RESULT.json',final)
    print(json.dumps(final,sort_keys=True))
except Exception as error:
    write('FAILURE.json',{'passed':False,'error':type(error).__name__+': '+str(error),'identities_before':before})
    raise
