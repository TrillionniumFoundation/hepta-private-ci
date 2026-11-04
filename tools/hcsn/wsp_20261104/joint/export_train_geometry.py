"""Reproduce finite TRAIN geometry using the pinned original model inference."""
from pathlib import Path
import argparse, hashlib, json, runpy
import numpy as np

def main():
    ap=argparse.ArgumentParser();ap.add_argument('data_root');ap.add_argument('output');args=ap.parse_args()
    output=Path(args.output)
    if output.exists():raise FileExistsError('output already exists')
    module=runpy.run_path(str(Path(__file__).with_name('run_head_edit.py')))
    arrays={};metadata={};root=Path(args.data_root)
    for fit in module['FITS']:
        modelpath=root/f'fit_{fit}/model_renewal/model.json';datapath=root/f'fit_{fit}/data/fit_{fit}_data.json'
        modelbytes=modelpath.read_bytes();databytes=datapath.read_bytes()
        assert hashlib.sha256(modelbytes).hexdigest()==module['RENEWAL_SHA'][fit]
        artifact=json.loads(modelbytes);data=json.loads(databytes)
        features=module['FrozenFeatures'](module['NumpyPolicy'](artifact))
        x,y,mask,posterior=module['row_arrays'](data['train']['rows'],features)
        for key,value in dict(x=x,y=y,mask=mask,posterior=posterior,theta=module['head'](artifact)).items():
            assert np.isfinite(value).all();arrays[f'fit{fit}_{key}']=value
        metadata[str(fit)]={'source_model_sha256':hashlib.sha256(modelbytes).hexdigest(),
                            'source_data_sha256':hashlib.sha256(databytes).hexdigest(),
                            'row_identity':[{'world':row['world'],'state':row['state']} for row in data['train']['rows']]}
    np.savez_compressed(output,**arrays)
    output.with_suffix('.metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
    print(json.dumps({'bytes':output.stat().st_size,'sha256':hashlib.sha256(output.read_bytes()).hexdigest()}))
if __name__=='__main__':main()
