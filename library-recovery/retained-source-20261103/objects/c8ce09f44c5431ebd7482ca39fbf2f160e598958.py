import hashlib, json, random, subprocess, sys
from pathlib import Path
root=Path('/mnt/data/neuron-trial-smoke-final')
sys.path.insert(0,'/mnt/data/neuron-trials/scripts')
from hepta_neuron_model_trials import sha_file, blind_rows, canonical_jsonl
rng=random.Random(3091)
Q=1<<24
rows=[]
for idx,(split,count) in enumerate((('train',60),('calibration',8),('holdout',12),('future_1',12),('future_2',12))):
 for k in range(count):
  xs=[int(rng.uniform(-.35,.35)*Q) for _ in range(512)]
  # Exactly fixed, deterministic teacher; target outputs are bounded Q24.
  ys=[(xs[(i*13+7)%512]//3)+(xs[(i*23+9)%512]//6) for i in range(512)]
  rows.append({'id':f'{split}-{k:03}', 'split':split,
               'source_group':f'{split}-{k:03}', 'observed_at_ms':(idx+1)*100000+k,
               'features_q24':xs,'target_q24':ys})
sealed=root/'heads-sealed.jsonl'
sealed.write_text(''.join(json.dumps(x,separators=(',',':'))+'\n' for x in rows),encoding='utf8')
blind=root/'heads-blind.jsonl'
blind.write_bytes(canonical_jsonl(blind_rows(rows,'heads')))
source_sha=subprocess.run(['git','rev-parse','HEAD'],cwd='/mnt/data/neuron-trials',check=True,capture_output=True,text=True).stdout.strip()
manifest={'schema':'hepta.neuron.model-trial.v1','family':'heads','source_sha':source_sha,
          'dataset_sha256':sha_file(sealed),'blind_dataset_sha256':sha_file(blind),
          'host_profile_digest':hashlib.sha256(b'SYNTHETIC-local-host').hexdigest(),
          'parameter_cap':262656,'head':{'input_dimension':512,'state_width':256,'encoder_digest':hashlib.sha256(b'SYNTHETIC-encoder').hexdigest(),
            'seed':17,'epochs':2,'batch_size':16,'learning_rate':.0003}}
(root/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf8')
print('Generated synthetic sealed/blinded datasets, source_sha',source_sha)
