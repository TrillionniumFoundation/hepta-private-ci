"""Re-fit the buyer from the released features, replay selection and confirm decisions."""
import argparse
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
from . import experiment as ex
from .verify_selector import verify
from qualification.hcsn_intervention_value.replay import unpack
from .incumbents import evaluate
from . import readout_edit, verify_edit, verify_joint


def equal(reference, actual, omit=()):
    a,b=ex.read(reference),ex.read(actual)
    for key in omit:
        a.pop(key); b.pop(key)
    if a!=b:
        raise ValueError('replay differs from '+str(reference))


def check(root, old, policies, scratch):
    original=root/'outcomes'
    new=scratch/'refitted'
    ex.fit(SimpleNamespace(root=root/'media',old=old,output=new))
    for name in ('fit.json','selection.json','train_dev_traces.json'):
        equal(original/name,new/name)
    restored=scratch/'confirmed'
    restored.mkdir()
    for name in (*ex.read(original/'seal.json')['files'], 'seal.json'):
        shutil.copyfile(original/name,restored/name)
    ex.confirm(SimpleNamespace(root=root/'media',old=old,output=restored,expected_seal=ex.digest(original/'seal.json')))
    equal(original/'test.json',restored/'test.json',['wall_seconds'])
    equal(original/'test_traces.json',restored/'test_traces.json')
    stats=verify(restored)
    raw=root/'media'
    refit=SimpleNamespace(root=raw,old=old,output=new)
    readout_edit.fit(refit)
    exact=ex.read(original/'edit_seal.json'); rebuilt=ex.read(new/'edit_seal.json')
    # Fresh wall-clock fields and the new fit's timing hash differ between processes.
    for name in exact['rows']:
        for radius in exact['rows'][name]:
            exact['rows'][name][radius].pop('elapsed')
            rebuilt['rows'][name][radius].pop('elapsed')
    if exact['rows']!=rebuilt['rows'] or exact['selected']!=rebuilt['selected']:
        raise ValueError('refitted bounded edits or development selection differ')
    shutil.copyfile(original/'edit_seal.json',restored/'edit_seal.json')
    readout_edit.confirm(SimpleNamespace(root=raw,old=old,output=restored,expected_seal=ex.digest(original/'edit_seal.json')))
    equal(original/'edit_test.json',restored/'edit_test.json')
    edit_checks=verify_edit.verify(raw,old,restored)
    panel, _ = ex.panel(root/'media',old,'test')
    incumbents=evaluate(panel,old,policies)
    previous=ex.read(original/'incumbents.json')
    previous.pop('wall_seconds')
    if incumbents!=previous:
        raise ValueError('legacy head replay differs')
    return {'passed':True,'deterministic_fit_outputs':3,'deterministic_confirmation_outputs':2,
            'bounded_edit_rows':edit_checks['split_decisions'],'edit_fit_and_test_checked':True,
            'independent_decisions':stats['row_decisions'],'independent_calibration_bins':stats['calibration_bins'],
            'legacy_heads':len(incumbents['old_heads']),'legacy_table_and_opportunity':True}


def main():
    import json
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('evidence',type=Path); cli.add_argument('old_evidence',type=Path); opt=cli.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        scratch=Path(tmp)
        unpack(opt.evidence,scratch/'new')
        unpack(opt.old_evidence,scratch/'old')
        prior=scratch/'old/primary'
        result=check(scratch/'new',prior/'discovery',prior/'policies',scratch)
        result['exact_hull_checks']=verify_joint.verify(scratch/'new/media',prior/'discovery',scratch/'new/outcomes',
                                                       opt.evidence/'joint_capacity.json')['panels']
        print(json.dumps(result,indent=2))


if __name__=='__main__':main()
