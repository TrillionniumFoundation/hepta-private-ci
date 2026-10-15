"""Original archived BF16 30-layer Llama-family Reader: bounded FP32 CPU research runtime.

Requires independently SHA-pinned ORIGINAL weights/tokenizer, and emits no task truth.
Candidate manual operator/tokenizer; NOT an official Transformers parity substitute.
"""
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
import json
import math
import regex

import torch
import torch.nn.functional as F
from safetensors import safe_open

WEIGHT_SHA='5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c'
TOKEN_SHA='9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c'
CONFIG_SHA='8eb740e8bbe4cff95ea7b4588d17a2432deb16e8075bc5828ff7ba9be94d982a'


def file_sha(p):
    h=sha256()
    with Path(p).open('rb') as f:
        for part in iter(lambda:f.read(1024*1024),b''):h.update(part)
    return h.hexdigest()

def check_original(root):
    root=Path(root)
    for name,expected in [('model.safetensors',WEIGHT_SHA),('tokenizer.json',TOKEN_SHA),('config.json',CONFIG_SHA)]:
        p=root/name
        if not p.is_file() or p.is_symlink() or file_sha(p)!=expected:raise ValueError('original Reader byte identity mismatch: '+name)
    return root


def bytes_to_unicode():
    bs=list(range(ord('!'),ord('~')+1))+list(range(ord('¡'),ord('¬')+1))+list(range(ord('®'),ord('ÿ')+1))
    cs=bs[:];n=0
    for b in range(256):
        if b not in bs:bs.append(b);cs.append(256+n);n+=1
    return dict(zip(bs,map(chr,cs)))

class OriginalCandidateBPE:
    pattern=regex.compile(r"'s|'t|'re|'ve|'m|'ll|'d| ?\p{L}+| ?\p{N}+| ?[^\s\p{L}\p{N}]+|\s+(?!\S)|\s+",regex.IGNORECASE)
    digit_pattern=regex.compile(r'(\p{N})')
    def __init__(self,root):
        self.root=check_original(root); j=json.loads((self.root/'tokenizer.json').read_bytes())
        if j['model']['type']!='BPE' or j['normalizer'] is not None:
            raise ValueError('original tokenizer model or normalization mismatch')
        self.vocab=j['model']['vocab'];self.inv={v:k for k,v in self.vocab.items()}
        self.ranks={tuple(p.split(' ',1)):i for i,p in enumerate(j['model']['merges'])}
        self.special={x['content']:x['id'] for x in j['added_tokens'] if x.get('special')}
        self.re_special=regex.compile('('+'|'.join(regex.escape(s) for s in sorted(self.special,key=len,reverse=True))+')')
        self.byte_enc=bytes_to_unicode();self.byte_dec={v:k for k,v in self.byte_enc.items()}
        if len(self.vocab)!=49152 or self.special.get('<|im_start|>')!=1 or self.special.get('<|im_end|>')!=2:raise ValueError('unreviewed tokenizer profile')
    @lru_cache(maxsize=15000)
    def _bpe(self,t):
        chunks=tuple(t)
        while len(chunks)>1:
            options=[(self.ranks[(a,b)],i) for i,(a,b) in enumerate(zip(chunks,chunks[1:])) if (a,b) in self.ranks]
            if not options:break
            _,i=min(options)
            chunks=chunks[:i]+(chunks[i]+chunks[i+1],)+chunks[i+2:]
        return chunks
    def encode(self,t):
        if not isinstance(t,str) or len(t.encode())>500_000:raise ValueError('invalid text length')
        out=[]
        for part in self.re_special.split(t):
            if not part:continue
            if part in self.special:out.append(self.special[part]);continue
            for q in self.digit_pattern.split(part):
                if not q:continue
                for phrase in self.pattern.findall(q):
                    b=''.join(self.byte_enc[v] for v in phrase.encode('utf-8'))
                    out.extend(self.vocab[piece] for piece in self._bpe(b))
        return out
    def decode(self,ids):
        buf=bytearray();out=[]
        for ident in ids:
            t=self.inv[ident]
            if t in self.special:
                if buf:out.append(buf.decode('utf-8',errors='replace'));buf=bytearray()
            else:
                buf.extend(self.byte_dec[x] for x in t)
        if buf:out.append(buf.decode('utf-8',errors='replace'))
        return ''.join(out)

class OriginalCandidateLlama:
    """Frozen archived model, true tensors and PyTorch operators, no HF numerical parity."""
    def __init__(self,root):
        root=check_original(root)
        c=json.loads((root/'config.json').read_text())
        if not (c['num_hidden_layers']==30 and c['hidden_size']==576 and c['num_attention_heads']==9 and c['num_key_value_heads']==3 and c['tie_word_embeddings'] is True):raise ValueError('unsupported original model')
        with safe_open(str(root/'model.safetensors'),framework='pt',device='cpu') as f:
            self.weights={key:f.get_tensor(key).float() for key in f.keys()}
        if len(self.weights)!=272:raise ValueError('original tensors modified')
        self.rope_theta=c['rope_theta'];self.eps=c['rms_norm_eps'];self.embedding=self.weights['model.embed_tokens.weight']
        self.cache=None;self.pos=0;self.calls=0
    def _rms(self,x,w):return x*torch.rsqrt(x.square().mean(-1,keepdim=True)+self.eps)*w
    def _rotate(self,v):
        lo,hi=v.chunk(2,-1);return torch.cat((-hi,lo),-1)
    @torch.inference_mode()
    def forward(self,ids,*,reset=False):
        if reset:self.cache=[None]*30;self.pos=0
        if self.cache is None or not ids or any(type(i)!=int or i<0 or i>=49152 for i in ids):raise ValueError('invalid input tokens')
        n=len(ids);start=self.pos
        if start+n>1024:raise ValueError('context budget exceeded, no clipping')
        x=self.embedding[torch.tensor(ids)];h=9;kv=3;d=64
        indexes=torch.arange(start,start+n,dtype=torch.float32)
        freqs=torch.outer(indexes,self.rope_theta**(-torch.arange(0,d,2,dtype=torch.float32)/d))
        cos=torch.cat((freqs.cos(),freqs.cos()),-1).unsqueeze(0)
        sin=torch.cat((freqs.sin(),freqs.sin()),-1).unsqueeze(0)
        for i in range(30):
            p=f'model.layers.{i}.';g=lambda k:self.weights[p+k]
            z=self._rms(x,g('input_layernorm.weight'))
            q=F.linear(z,g('self_attn.q_proj.weight')).reshape(n,h,d).transpose(0,1)
            k=F.linear(z,g('self_attn.k_proj.weight')).reshape(n,kv,d).transpose(0,1)
            v=F.linear(z,g('self_attn.v_proj.weight')).reshape(n,kv,d).transpose(0,1)
            q=q*cos+self._rotate(q)*sin;k=k*cos+self._rotate(k)*sin
            if self.cache[i] is not None:
                oldk,oldv=self.cache[i];k=torch.cat((oldk,k),-2);v=torch.cat((oldv,v),-2)
            self.cache[i]=(k,v)
            kk=k.repeat_interleave(h//kv,dim=0);vv=v.repeat_interleave(h//kv,dim=0)
            logits=q@kk.transpose(-1,-2)/math.sqrt(d)
            if n>1:
                qi=torch.arange(start,start+n).unsqueeze(1);kj=torch.arange(start+n).unsqueeze(0)
                logits=logits.masked_fill(kj>qi,float('-inf'))
            out=(logits.softmax(-1)@vv).transpose(0,1).contiguous().reshape(n,h*d)
            x=x+F.linear(out,g('self_attn.o_proj.weight'))
            z=self._rms(x,g('post_attention_layernorm.weight'))
            x=x+F.linear(F.silu(F.linear(z,g('mlp.gate_proj.weight')))*F.linear(z,g('mlp.up_proj.weight')),g('mlp.down_proj.weight'))
        self.pos+=n;self.calls+=1
        return F.linear(self._rms(x[-1],self.weights['model.norm.weight']),self.embedding)
    @torch.inference_mode()
    def generate(self,ids,max_tokens=18):
        if type(max_tokens)!=int or not 1<=max_tokens<=32:raise ValueError('output cap')
        scores=self.forward(ids,reset=True);out=[]
        for _ in range(max_tokens):
            next_id=int(scores.argmax());out.append(next_id)
            if next_id==2:break
            scores=self.forward([next_id])
        return out
