"""Manual FP32 reader path for SHA-locked archived BF16 135M Llama.

This independently reproduced operator path is not official HF tokenizer/operator
parity. One original weight snapshot is reused for all physical requests.
"""
from functools import lru_cache
from hashlib import sha256
import json
import math
from pathlib import Path
import regex
import torch
import torch.nn.functional as F
from safetensors import safe_open

WEIGHTS = '5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c'
TOKENIZER = '9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c'
CONFIG = '8eb740e8bbe4cff95ea7b4588d17a2432deb16e8075bc5828ff7ba9be94d982a'


def file_sha(p):
    h = sha256()
    with Path(p).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def verify(root):
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        raise ValueError('original 135M material missing')
    for name, wanted in (('model.safetensors', WEIGHTS), ('tokenizer.json', TOKENIZER), ('config.json', CONFIG)):
        f = root / name
        if not f.is_file() or f.is_symlink() or file_sha(f) != wanted:
            raise ValueError('original Reader byte identity mismatch: ' + name)
    return root


def byte_unicode():
    bs = list(range(ord('!'),ord('~')+1)) + list(range(ord('¡'),ord('¬')+1)) + list(range(ord('®'),ord('ÿ')+1))
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b);cs.append(256+n);n += 1
    return dict(zip(bs,map(chr,cs)))


class BPE:
    pattern = regex.compile(r"'s|'t|'re|'ve|'m|'ll|'d| ?\p{L}+| ?\p{N}+| ?[^\s\p{L}\p{N}]+|\s+(?!\S)|\s+",regex.IGNORECASE)
    numeric = regex.compile(r'(\p{N})')

    def __init__(self, root):
        root = verify(root)
        obj=json.loads((root/'tokenizer.json').read_bytes())
        if obj['model']['type'] != 'BPE' or obj['normalizer'] is not None:
            raise ValueError('unknown original tokenizer')
        self.vocab=obj['model']['vocab']
        self.inverse={v:k for k,v in self.vocab.items()}
        self.ranks={tuple(s.split(' ',1)):i for i,s in enumerate(obj['model']['merges'])}
        self.special={x['content']:x['id'] for x in obj['added_tokens'] if x.get('special')}
        self.splitter=regex.compile('('+'|'.join(regex.escape(s) for s in sorted(self.special,key=len,reverse=True))+')')
        self.encoder=byte_unicode();self.decoder={v:k for k,v in self.encoder.items()}
        if len(self.vocab)!=49152 or self.special.get('<|im_start|>')!=1 or self.special.get('<|im_end|>')!=2:
            raise ValueError('unreviewed tokenizer')

    @lru_cache(maxsize=15000)
    def bpe(self, word):
        parts=tuple(word)
        while len(parts)>1:
            candidates=[(self.ranks[(a,b)],i) for i,(a,b) in enumerate(zip(parts,parts[1:])) if (a,b) in self.ranks]
            if not candidates:break
            _,i=min(candidates)
            parts=parts[:i]+(parts[i]+parts[i+1],)+parts[i+2:]
        return parts

    def encode(self,text):
        if not isinstance(text,str) or len(text.encode())>500000:raise ValueError('input too large')
        out=[]
        for part in self.splitter.split(text):
            if not part:continue
            if part in self.special:
                out.append(self.special[part]);continue
            for q in self.numeric.split(part):
                if not q:continue
                for segment in self.pattern.findall(q):
                    encoded=''.join(self.encoder[b] for b in segment.encode('utf-8'))
                    out.extend(self.vocab[s] for s in self.bpe(encoded))
        return out

    def decode(self,ids):
        data=bytearray();out=[]
        for idx in ids:
            t=self.inverse[idx]
            if t in self.special:
                if data:
                    out.append(data.decode('utf-8',errors='replace'))
                    data=bytearray()
            else:
                data.extend(self.decoder[ch] for ch in t)
        if data:out.append(data.decode('utf-8',errors='replace'))
        return ''.join(out)


class Llama135M:
    def __init__(self,root):
        root=verify(root); config=json.loads((root/'config.json').read_text())
        if not (config['num_hidden_layers']==30 and config['hidden_size']==576
                and config['num_attention_heads']==9 and config['num_key_value_heads']==3
                and config['tie_word_embeddings'] is True):
            raise ValueError('incompatible Reader tensor config')
        with safe_open(str(root/'model.safetensors'),framework='pt',device='cpu') as f:
            self.w={k:f.get_tensor(k).float() for k in f.keys()}
        if len(self.w)!=272:raise ValueError('unexpected original tensor count')
        self.theta=config['rope_theta'];self.eps=config['rms_norm_eps'];self.embed=self.w['model.embed_tokens.weight'];self.calls=0
        self.cache=None;self.pos=0

    def rms(self,x,w):return x*torch.rsqrt(x.square().mean(-1,keepdim=True)+self.eps)*w

    @staticmethod
    def rotate(x):
        a,b=x.chunk(2,-1)
        return torch.cat((-b,a),-1)

    @torch.inference_mode()
    def forward(self,ids,reset=False):
        if reset:self.cache=[None]*30;self.pos=0
        if self.cache is None or not ids or any(type(i)!=int or not 0<=i<49152 for i in ids):
            raise ValueError('invalid Reader token ids')
        n=len(ids);start=self.pos
        if start+n>1024:raise ValueError('reader context exhausted')
        x=self.embed[torch.tensor(ids)];h=9;kv=3;d=64
        positions=torch.arange(start,start+n,dtype=torch.float32)
        freqs=torch.outer(positions,self.theta**(-torch.arange(0,d,2,dtype=torch.float32)/d))
        cos=torch.cat((freqs.cos(),freqs.cos()),-1).unsqueeze(0)
        sin=torch.cat((freqs.sin(),freqs.sin()),-1).unsqueeze(0)
        for layer in range(30):
            p=f'model.layers.{layer}.'
            g=lambda s:self.w[p+s]
            a=self.rms(x,g('input_layernorm.weight'))
            q=F.linear(a,g('self_attn.q_proj.weight')).reshape(n,h,d).transpose(0,1)
            k=F.linear(a,g('self_attn.k_proj.weight')).reshape(n,kv,d).transpose(0,1)
            v=F.linear(a,g('self_attn.v_proj.weight')).reshape(n,kv,d).transpose(0,1)
            q=q*cos+self.rotate(q)*sin
            k=k*cos+self.rotate(k)*sin
            if self.cache[layer] is not None:
                oldk,oldv=self.cache[layer]
                k=torch.cat((oldk,k),-2);v=torch.cat((oldv,v),-2)
            self.cache[layer]=(k,v)
            key=k.repeat_interleave(h//kv,dim=0)
            value=v.repeat_interleave(h//kv,dim=0)
            logits=q@key.transpose(-1,-2)/math.sqrt(d)
            if n>1:
                qs=torch.arange(start,start+n).unsqueeze(1)
                ks=torch.arange(start+n).unsqueeze(0)
                logits=logits.masked_fill(ks>qs,float('-inf'))
            out=(logits.softmax(-1)@value).transpose(0,1).contiguous().reshape(n,h*d)
            x=x+F.linear(out,g('self_attn.o_proj.weight'))
            a=self.rms(x,g('post_attention_layernorm.weight'))
            x=x+F.linear(F.silu(F.linear(a,g('mlp.gate_proj.weight')))*F.linear(a,g('mlp.up_proj.weight')),g('mlp.down_proj.weight'))
        self.pos+=n;self.calls+=1
        return F.linear(self.rms(x[-1],self.w['model.norm.weight']),self.embed)

    @torch.inference_mode()
    def generate(self,ids,max_tokens=24):
        if type(max_tokens)!=int or not 1<=max_tokens<=32:raise ValueError('output cap')
        scores=self.forward(ids,reset=True);out=[]
        for _ in range(max_tokens):
            next_id=int(scores.argmax());out.append(next_id)
            if next_id==2:break
            scores=self.forward([next_id])
        return out
