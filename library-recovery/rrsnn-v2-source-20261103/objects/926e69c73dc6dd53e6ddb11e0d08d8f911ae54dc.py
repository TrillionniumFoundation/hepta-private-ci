"""Pack all source, frozen data, checkpoints and evidence, with SHA-256 inventory."""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parent


def included_files():
    files = []
    for p in sorted(ROOT.rglob('*')):
        if not p.is_file() or '__pycache__' in p.parts or p.name == 'file_manifest.json':
            continue
        if p.suffix in ('.pyc','.zip'):
            continue
        files.append(p)
    r0 = ROOT.parent/'rollover_snn_research'
    for name in ('analytic_neuron.py','README.txt','requirements.txt','build_notebook.py',
                 'rollover_snn_research.ipynb','results/validation_results.json',
                 'results/analytic_neuron_validation.png'):
        p = r0/name
        if p.exists():
            files.append(p)
    return files


def main():
    matrix = json.loads((ROOT/'results/matrix_status.json').read_text())
    assert matrix['completed'] == 60 and not matrix['failures']
    assert matrix['source_unchanged_during_matrix']
    numerical = json.loads((ROOT/'models/implementation_control_results.json').read_text())
    assert numerical['complete']
    files = included_files()
    entries = []
    for p in files:
        data = p.read_bytes()
        entries.append({'archive_path':str(p.relative_to(ROOT.parent)),
                        'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
    manifest = ROOT/'file_manifest.json'
    manifest.write_text(json.dumps({'schema':'rrsnn.deliverable-inventory.v1',
                                   'excluded':['this manifest itself','__pycache__','nested ZIP files'],
                                   'files':entries},indent=2)+'\n')
    output = ROOT.parent/'RR_SNN_R1_R5_Experiments.zip'
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in files+[manifest]:
            z.write(p,str(p.relative_to(ROOT.parent)))
    # Archive CRC checks catch incomplete or corrupted packaging, not scientific
    # correctness; that is checked by the component validation evidence.
    with zipfile.ZipFile(output) as z:
        assert z.testzip() is None
    print(json.dumps({'path':str(output),'files':len(files)+1,
                      'bytes':output.stat().st_size,
                      'sha256':hashlib.sha256(output.read_bytes()).hexdigest()}))


if __name__ == '__main__':
    main()
