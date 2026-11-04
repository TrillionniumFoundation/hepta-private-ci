"""Restore exact prior candidate inputs; no optimization or evaluation.

Use the public source checkpoint plus recorded small last-layer arrays to
reconstruct the exact candidate JSON whose hash was frozen before this follow-up.
Keep the original result bytes (including their original timing records) as
source evidence; do not substitute new measurements into that source identity.
"""
from pathlib import Path
import argparse,gzip,hashlib,json

ROOT=Path(__file__).resolve().parent

def sha(b):return hashlib.sha256(b).hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--study-root',required=True);ap.add_argument('--inputs',required=True)
    ap.add_argument('--recorded-results',help='optional original uncompressed or gzipped results path; hash must still match')
    ap.add_argument('--output',required=True);args=ap.parse_args()
    out=Path(args.output)
    if out.exists():raise FileExistsError('output must be new')
    protocol=json.loads((ROOT/'PROTOCOL_BEFORE_RESULTS.json').read_text())
    heads=json.loads(gzip.decompress((ROOT/'OLD_CONTINUATION_HEADS.json.gz').read_bytes()))
    result_path=Path(args.recorded_results) if args.recorded_results else Path(args.study_root)/'records/results_strict.json.gz'
    result_bytes=result_path.read_bytes()
    if result_path.suffix=='.gz':result_bytes=gzip.decompress(result_bytes)
    assert sha(result_bytes)==heads['source_results_sha256']==protocol['source_original_results_sha256']
    original_results=json.loads(result_bytes);expected={f['fit']:f for f in original_results['fits']}
    candidates={};data_root=Path(args.inputs)
    for entry in heads['fits']:
        fit=entry['fit'];path=data_root/f'fit_{fit}/model_renewal/model.json';b=path.read_bytes()
        assert sha(b)==entry['source_model_sha256']==expected[fit]['source_model_sha256']
        artifact=json.loads(b)
        assert artifact['network']['w2'][3]==entry['network_w2'][3] and artifact['network']['b2'][3]==entry['network_b2'][3]
        artifact['network']['w2']=entry['network_w2'];artifact['network']['b2']=entry['network_b2']
        candidate=(json.dumps(artifact,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()
        assert sha(candidate)==entry['candidate_model_sha256']==expected[fit]['candidate_model_sha256']
        candidates[f'fit_{fit}_candidate_model.json']=candidate
    assert len(candidates)==5
    out.mkdir(parents=True,mode=0o700,exist_ok=False)
    for name,b in candidates.items():
        with (out/name).open('xb') as f:f.write(b)
    with (out/'results.json').open('xb') as f:f.write(result_bytes)
    receipt={'schema':'hepta-frozen-continuation-input-restoration-v1','source_results_sha256':sha(result_bytes),
             'restored_candidates':{name:sha(b) for name,b in candidates.items()},'new_optimizer_calls':0,'new_policy_evaluations':0}
    (out/'RESTORATION_RECEIPT.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt))
if __name__=='__main__':main()
