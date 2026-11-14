"""Model-free tokenizer/mask identity audit of the completed mechanical fixture."""
import os
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',USE_TF='0',TOKENIZERS_PARALLELISM='false',OMP_NUM_THREADS='1')
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
from transformers import AutoTokenizer
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent/'hepta-cell-training-current'
OUT=HERE/'harrier-real-cell-integration-v2'
sys.path.insert(0,str(ROOT/'codex-rs/hepta-neuron/qualification'))
from laya_loader_view import _inventory
S=Path('/workspace/shared/hepta-cell-model-cache/models--microsoft--harrier-oss-v1-270m/snapshots/31de22b673913c7d658c0f03f792d77c2dcf8ebd')
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
original=json.loads((OUT/'model-inventory-before.json').read_text())
assert _inventory(S)==original
rows=json.loads((OUT/'synthetic-rows.json').read_text())
t=AutoTokenizer.from_pretrained(str(S),local_files_only=True,trust_remote_code=False,use_fast=True)
texts=[r['text'] for r in rows]+[r['text']+'\nCandidate under evaluation: '+c for r in rows for c in r['candidates']]
batches=[]
for start in range(0,len(texts),4):
 encoded=t(texts[start:start+4],padding=True,truncation=True,max_length=192,return_tensors='np')
 batches.append({'rows':len(encoded['input_ids']),'shape':list(encoded['input_ids'].shape),'nonpadding_tokens':encoded['attention_mask'].sum(-1).tolist()})
assert _inventory(S)==original
result={'status':'PASS_MODEL_FREE_TOKENIZER_IDENTITY_AUDIT','input_report_sha256':sha(OUT/'report.json'),'driver_sha256':sha(__file__),
 'tokenizer_class':type(t).__name__,'tokenizer_module':type(t).__module__,'is_fast':t.is_fast,
 'padding_side':t.padding_side,'truncation_side':t.truncation_side,'pad_token_id':t.pad_token_id,'bos_token_id':t.bos_token_id,'eos_token_id':t.eos_token_id,
 'add_bos_token':t.add_bos_token,'add_eos_token':t.add_eos_token,'explicit_max_length':192,
 'truncation':True,'padding':True,'special_tokens':'tokenizer defaults; unmasked special tokens participate in mean pooling',
 'texts':len(texts),'text_order_sha256':hashlib.sha256((json.dumps(texts,ensure_ascii=False,separators=(',',':'))+'\n').encode()).hexdigest(),
 'mask_audit_batches':batches,'model_bytes_unchanged':True,'encoder_executed':False,
 'note':'These masks were regenerated without a backbone after the run, not captured model-forward receipts; actual new forward receipts remain in report.json.'}
raw=(json.dumps(result,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
with (OUT/'tokenizer-audit.json').open('xb') as f:f.write(raw)
print(json.dumps({'status':result['status'],'sha256':hashlib.sha256(raw).hexdigest(),'class':result['tokenizer_class'],'pad':t.pad_token_id,'bos':t.bos_token_id,'eos':t.eos_token_id,'texts':len(texts)}))
