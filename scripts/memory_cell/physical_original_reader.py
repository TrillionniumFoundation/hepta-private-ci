"""Frozen original 135M-Reader physical research replay, no HF parity/production claim.

Reimplementation bound to the original archived safetensors and tokenizer; the
reference source is qualification/amcn-v1/amcn_original_text_reader.py in PR #2085.
It independently checks a pre-published, original four-token numerical fingerprint.
"""
from __future__ import annotations
import hashlib,json,math
from functools import lru_cache
from pathlib import Path
import regex, torch
import torch.nn.functional as F
from safetensors import safe_open

WEIGHT_SHA='5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c'
TOKENIZER_SHA='9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c'
ORIGINAL_LOGITS_SHA='0e213cba29020f3140dee7e72d5b8737ebcb2ce0e0189e5662b8415a09f71776'

def digest(raw):return hashlib.sha256(raw).hexdigest()
def filehash(path):
 with open(path,'rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def require(v,msg):
 if not v:raise ValueError(msg)

def byte_map():
 bs=list(range(ord('!'),ord('~')+1)) + list(range(ord('¡'),ord('¬')+1)) + list(range(ord('®'),ord('ÿ')+1))
 cs=bs[:];n=0
 for b in range(256):
  if b not in bs:bs.append(b);cs.append(256+n);n+=1
 return dict(zip(bs,map(chr,cs)))

class ReaderTokenizer:
 PATTERN=regex.compile(r"'s|'t|'re|'ve|'m|'ll|'d| ?\p{L}+| ?\p{N}+| ?[^\s\p{L}\p{N}]+|\s+(?!\S)|\s+",regex.IGNORECASE)
 DIGITS=regex.compile(r'(\p{N})')
 def __init__(self,path):
  path=Path(path)
  require(filehash(path)==TOKENIZER_SHA,'original archived tokenizer SHA mismatch')
  d=json.loads(path.read_bytes());require(d['model']['type']=='BPE' and d['pre_tokenizer']['type']=='Sequence','tokenizer format drift')
  require([x['type'] for x in d['pre_tokenizer']['pretokenizers']]==['Digits','ByteLevel'],'pretokenizer drift')
  require(d['pre_tokenizer']['pretokenizers'][0]['individual_digits'] and not d['pre_tokenizer']['pretokenizers'][1]['add_prefix_space'] and d['normalizer'] is None,'tokenizer options drift')
  self.vocab=d['model']['vocab'];require(len(self.vocab)==49152,'vocab size drift')
  self.inv={v:k for k,v in self.vocab.items()};require(len(self.inv)==len(self.vocab),'duplicate token ids')
  self.merges={tuple(x.split(' ',1)):i for i,x in enumerate(d['model']['merges'])}
  self.special={x['content']:x['id'] for x in d['added_tokens'] if x['special']}
  require(self.special.get('<|im_start|>')==1 and self.special.get('<|im_end|>')==2,'missing original specials')
  self.special_re=regex.compile('('+ '|'.join(map(regex.escape,sorted(self.special,key=len,reverse=True))) +')')
  self.encoder=byte_map();self.decoder={v:k for k,v in self.encoder.items()}
 @lru_cache(maxsize=30000)
 def bpe(self,text):
  chars=tuple(text)
  while len(chars)>1:
   pairs=[(self.merges[(x,y)],i) for i,(x,y) in enumerate(zip(chars,chars[1:])) if (x,y) in self.merges]
   if not pairs:break
   _,i=min(pairs);chars=chars[:i]+(chars[i]+chars[i+1],)+chars[i+2:]
  return chars
 def encode(self,text):
  require(isinstance(text,str) and len(text.encode('utf-8'))<100000,'input bound')
  ids=[]
  for piece in self.special_re.split(text):
   if not piece:continue
   if piece in self.special:ids.append(self.special[piece]);continue
   for part in self.DIGITS.split(piece):
    if not part:continue
    for chunk in self.PATTERN.findall(part):
     encoded=''.join(self.encoder[x] for x in chunk.encode())
     for token in self.bpe(encoded):
      require(token in self.vocab,'unknown BPE component');ids.append(self.vocab[token])
  return ids
 def decode(self,ids):
  pieces=[];buf=bytearray()
  for i in ids:
   require(i in self.inv,'token id out of range')
   token=self.inv[i]
   if token in self.special:
    if buf:pieces.append(buf.decode(errors='replace'));buf.clear()
    continue
   for c in token:buf.append(self.decoder[c])
  if buf:pieces.append(buf.decode(errors='replace'))
  return ''.join(pieces)

class ReaderModel:
 def __init__(self,directory):
  path=Path(directory)/'model.safetensors'
  require(filehash(path)==WEIGHT_SHA,'original safetensors weight mismatch')
  self.config=json.loads((Path(directory)/'config.json').read_bytes()); c=self.config
  require((c['model_type'],c['num_hidden_layers'],c['hidden_size'],c['num_attention_heads'],c['num_key_value_heads'],c['vocab_size'])==('llama',30,576,9,3,49152) and c['tie_word_embeddings'],'wrong architecture')
  self.hidden=576;self.heads=9;self.kvheads=3;self.dim=64
  self.theta=float(c['rope_theta']);self.eps=float(c['rms_norm_eps'])
  with safe_open(str(path),framework='pt',device='cpu') as f:
   require(len(f.keys())==272,'unexpected original tensor count')
   self.w={k:f.get_tensor(k).to(torch.float32) for k in f.keys()}
  self.embed=self.w['model.embed_tokens.weight']
  self.cache=None;self.position=0
 def rms(self,x,w):return x*torch.rsqrt(x.square().mean(-1,keepdim=True)+self.eps)*w
 def rope(self,q,k,start,n):
  freqs=torch.outer(torch.arange(start,start+n,dtype=torch.float32),self.theta**(-torch.arange(0,64,2,dtype=torch.float32)/64))
  c=torch.cat((freqs.cos(),freqs.cos()),dim=-1).unsqueeze(0)
  s=torch.cat((freqs.sin(),freqs.sin()),dim=-1).unsqueeze(0)
  def rotate(x):
   a,b=x.chunk(2,dim=-1);return torch.cat((-b,a),dim=-1)
  return q*c+rotate(q)*s,k*c+rotate(k)*s
 @torch.inference_mode()
 def forward(self,ids,reset=False):
  if reset:self.cache=[None]*30;self.position=0
  require(self.cache is not None and 0<len(ids) and self.position+len(ids)<=1024 and all(type(i)==int and 0<=i<49152 for i in ids),'invalid model prompt')
  n=len(ids);start=self.position
  x=self.embed[torch.tensor(ids)];h=self.heads;kv=self.kvheads;d=self.dim
  for i in range(30):
   p=f'model.layers.{i}.';g=lambda key:self.w[p+key]
   z=self.rms(x,g('input_layernorm.weight'))
   q=F.linear(z,g('self_attn.q_proj.weight')).reshape(n,h,d).transpose(0,1)
   k=F.linear(z,g('self_attn.k_proj.weight')).reshape(n,kv,d).transpose(0,1)
   v=F.linear(z,g('self_attn.v_proj.weight')).reshape(n,kv,d).transpose(0,1)
   q,k=self.rope(q,k,start,n)
   if self.cache[i] is not None:
    k=torch.cat((self.cache[i][0],k),dim=-2);v=torch.cat((self.cache[i][1],v),dim=-2)
   self.cache[i]=(k,v)
   kk=k.repeat_interleave(h//kv,dim=0);vv=v.repeat_interleave(h//kv,dim=0)
   attn=q @ kk.transpose(-1,-2)/math.sqrt(d)
   if n>1:attn=attn.masked_fill(torch.arange(start+n).unsqueeze(0)>torch.arange(start,start+n).unsqueeze(1),float('-inf'))
   y=(attn.softmax(-1)@vv).transpose(0,1).contiguous().reshape(n,h*d)
   x=x+F.linear(y,g('self_attn.o_proj.weight'))
   z=self.rms(x,g('post_attention_layernorm.weight'))
   x=x+F.linear(F.silu(F.linear(z,g('mlp.gate_proj.weight')))*F.linear(z,g('mlp.up_proj.weight')),g('mlp.down_proj.weight'))
  self.position+=n
  result=self.rms(x[-1],self.w['model.norm.weight'])
  return F.linear(result,self.embed)
 @torch.inference_mode()
 def generate(self,ids,max_new_tokens=24):
  require(1<=max_new_tokens<=96 and len(ids)+max_new_tokens<=1024,'generation bound')
  logits=self.forward(ids,reset=True);out=[]
  for i in range(max_new_tokens):
   token=int(logits.argmax().item());out.append(token)
   if token==2:break
   if i+1<max_new_tokens:logits=self.forward([token])
  return out

def chat(question,evidence):
 require(0<len(evidence)<=4 and all(len(x.encode())<=640 for x in evidence),'evidence bound')
 sys='Answer only from the provided evidence. If insufficient evidence, say unknown. Cite [E1], [E2].'
 ctx='\n'.join(f'[E{i}] {e}' for i,e in enumerate(evidence,1))
 return f'<|im_start|>system\n{sys}<|im_end|>\n<|im_start|>user\n{ctx}\nQuestion: {question}<|im_end|>\n<|im_start|>assistant\n'

if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--stage',type=Path,required=True);p.add_argument('--fingerprint',action='store_true');args=p.parse_args()
 torch.set_num_threads(3)
 model=ReaderModel(args.stage)
 if args.fingerprint:
  ans=model.forward([1,420,35,177],reset=True)
  print(json.dumps({'fingerprint':digest(ans.contiguous().numpy().tobytes()),'original_expected':ORIGINAL_LOGITS_SHA,'identical':digest(ans.contiguous().numpy().tobytes())==ORIGINAL_LOGITS_SHA,'top5':torch.topk(ans,5).indices.tolist()}))
