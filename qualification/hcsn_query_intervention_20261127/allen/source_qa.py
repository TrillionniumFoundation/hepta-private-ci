"""Input-only checks. The previous extraction is optional and used only for differences."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

def run(directory, previous=None):
    roster = json.loads((directory/'roster.json').read_text())['cells']
    rows = []
    for specimen in roster:
        path = directory / f'{specimen}.json'
        ledger = json.loads(path.read_text())
        packet = path.with_suffix('.npz')
        assert hashlib.sha256(packet.read_bytes()).hexdigest() == ledger['npz_sha256']
        arrays = np.load(packet)
        old = None if previous is None else np.load(previous/packet.name)
        if old is not None:
            before = json.loads((previous/path.name).read_text())
            assert before['nwb_sha256'] == ledger['nwb_sha256']
        for sweep in ledger['sweeps']:
            k = sweep['key']
            x = arrays[next(a for a in arrays if k in a and 'x' in a)]
            y = arrays[next(a for a in arrays if k in a and 'y' in a)]
            maximum = float(abs(x).max())
            assert maximum == sweep['max_abs_current_pa']
            ratio = maximum/sweep['row']['stimulus_absolute_amplitude']
            record = dict(specimen=specimen,key=k,current_bin_to_metadata_ratio=ratio,
                          pipeline=sweep['pipeline_version'],n_bins=len(y))
            if old is not None:
                oldx = old[next(a for a in old if k in a and 'x' in a)]
                oldy = old[next(a for a in old if k in a and 'y' in a)]
                record.update(pA_scale_correction_log10=round(np.log10(maximum/float(abs(oldx).max()))),
                              changed_output_bins=int(np.count_nonzero(y != oldy)))
            rows.append(record)
    return dict(specimens=len(roster),sweeps=len(rows),n_bins=sum(r['n_bins'] for r in rows),
          amplitude_ratio_range=[min(r['current_bin_to_metadata_ratio'] for r in rows),max(r['current_bin_to_metadata_ratio'] for r in rows)],rows=rows)

if __name__=='__main__':
    cli=argparse.ArgumentParser()
    cli.add_argument('data',type=Path);cli.add_argument('--previous',type=Path)
    args=cli.parse_args()
    print(json.dumps(run(args.data,args.previous),indent=1))
