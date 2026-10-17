"""SHA-bound local SmolLM-135M CPU reference for source-only G9 research.

Independent native Torch implementation of standard Llama attention/FFN + GPT-2 byte-BPE.
Not an upstream Transformers/tokenizers parity certificate, native Hepta product port,
or authority to execute effects. No raw source/target labels enter the reader API.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
from functools import lru_cache

SOURCE_SHA = {
    'model.safetensors':'5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c',
    'tokenizer.json':'9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c',
    'config.json':'8eb740e8bbe4cff95ea7b4588d17a2432deb16e8075bc5828ff7ba9be94d982a',
}
MAX_PROMPT_TOKENS = 1024
MAX_OUTPUT_TOKENS = 24


def verify_material(root: Path) -> None:
    for f, expected in SOURCE_SHA.items():
        p=Path(root)/f
        if not p.is_file() or p.is_symlink() or p.stat().st_size > 500_000_000:
            raise ValueError('missing/unsafe reader material: '+f)
        if hashlib.sha256(p.read_bytes()).hexdigest() != expected:
            raise ValueError('original reader material SHA mismatch: '+f)


def _bytes_to_unicode():
    bs=list(range(ord('!'),ord('~')+1))+list(range(ord('¡'),ord('¬')+1))+list(range(ord('®'),ord('ÿ')+1))
    cs=bs[:];n=0
    for b in range(256):
        if b not in bs:
            bs.append(b);cs.append(256+n);n+=1
    return {b:chr(c) for b,c in zip(bs,cs)}


class ByteBPE:
    """Bounded, deterministic pure-Python GPT-2 byte BPE; parity unverified."""
    def __init__(self,path):
        import regex
        self.regexmod=regex
        spec=json.loads(Path(path).read_text())
        if spec['model']['type']!='BPE' or spec['normalizer'] is not None:
            raise ValueError('unsupported original tokenizer profile')
        self.vocab=spec['model']['vocab']
        self.ranks={tuple(pair.split(' ')):i for i,pair in enumerate(spec['model']['merges'])}
        self.bytes=_bytes_to_unicode()
        self.inverse={v:k for k,v in self.bytes.items()}
        self.regex=regex.compile(r"'(?:s|t|re|ve|m|ll|d)| ?\p{L}+| ?\p{N}+| ?[^\s\p{L}\p{N}]+|\s+(?!\S)|\s+")

    @lru_cache(maxsize=8192)
    def _bpe(self,s):
        parts=tuple(s)
        while len(parts)>1:
            cand=[(self.ranks.get((a,b),float('inf')),i) for i,(a,b) in enumerate(zip(parts,parts[1:]))]
            rank,i=min(cand)
            if math.isinf(rank):break
            parts=parts[:i]+(parts[i]+parts[i+1],)+parts[i+2:]
        return tuple(self.vocab[token] for token in parts)

    def encode(self,text):
        if type(text) is not str or len(text.encode('utf8'))>32_768:
            raise ValueError('invalid bounded tokenizer input')
        out=[]
        # Digits pre-tokenizer splits Unicode numeric characters before ByteLevel.
        for chunk in self.regexmod.split(r'(\p{Nd})',text):
            if not chunk:continue
            for m in self.regex.finditer(chunk):
                sym=''.join(self.bytes[x] for x in m.group().encode('utf8'))
                out.extend(self._bpe(sym))
        return out

    def decode(self,ids):
        inv={v:k for k,v in self.vocab.items()}
        try:
            charstream=''.join(inv[i] for i in ids)
            return bytes(self.inverse[c] for c in charstream).decode('utf8',errors='replace')
        except KeyError as e:
            raise ValueError('unknown token id') from e


class NativeSmolLM135:
    def __init__(self,root:Path):
        verify_material(root)
        import torch
        from safetensors import safe_open
        torch.set_num_threads(4)
        self.torch=torch
        with safe_open(str(Path(root)/'model.safetensors'),framework='pt',device='cpu') as s:
            self.w={k:s.get_tensor(k).float().contiguous() for k in s.keys()}
        self.cfg=json.loads((Path(root)/'config.json').read_text())
        if (self.cfg['hidden_size'],self.cfg['num_hidden_layers'],self.cfg['num_attention_heads'],self.cfg['num_key_value_heads'],self.cfg['vocab_size']) != (576,30,9,3,49152):
            raise ValueError('unregistered 135M model dimensions')
        self.calls=0
        self.prefills=0
        self.tok=ByteBPE(Path(root)/'tokenizer.json')
        self.head_dim=64
        self.n_head=9
        self.n_kv=3
        self.emb=self.w['model.embed_tokens.weight']
        self.cache=[]
        self.pos=0

    def _rms(self,x,w):
        return x*self.torch.rsqrt(x.square().mean(-1,keepdim=True)+1e-5)*w

    def _rope(self,x,offset):
        t=self.torch
        n=x.shape[-2]
        inv=1./(100000.**(t.arange(0,64,2,dtype=t.float32)/64))
        angle=t.outer(t.arange(offset,offset+n,dtype=t.float32),inv)
        c=t.cos(angle).reshape(1,n,32);s=t.sin(angle).reshape(1,n,32)
        # Llama rotary half (not GPT-J even/odd): x[:, :, :32], x[:, :, 32:]
        left,right=x[...,:32],x[...,32:]
        return t.cat([left*c-right*s,right*c+left*s],dim=-1)

    def _pass(self,ids,append):
        t=self.torch
        if len(ids)==0 or len(ids)>MAX_PROMPT_TOKENS:
            raise ValueError('invalid bound for one forward')
        offset=self.pos if append else 0
        x=self.emb[t.tensor(ids,dtype=t.long)]
        cache_next=[]
        for i in range(30):
            p=f'model.layers.{i}.';w=self.w.__getitem__
            h=self._rms(x,w(p+'input_layernorm.weight'))
            q=t.nn.functional.linear(h,w(p+'self_attn.q_proj.weight')).reshape(-1,9,64).transpose(0,1)
            k=t.nn.functional.linear(h,w(p+'self_attn.k_proj.weight')).reshape(-1,3,64).transpose(0,1)
            v=t.nn.functional.linear(h,w(p+'self_attn.v_proj.weight')).reshape(-1,3,64).transpose(0,1)
            q=self._rope(q,offset);k=self._rope(k,offset)
            if append:
                ka=t.cat([self.cache[i][0],k],dim=1)
                va=t.cat([self.cache[i][1],v],dim=1)
            else:
                ka,va=k,v
            cache_next.append((ka,va))
            ka=ka.repeat_interleave(3,dim=0);va=va.repeat_interleave(3,dim=0)
            attn=q@ka.transpose(-1,-2)*(1/math.sqrt(64))
            if len(ids)>1:
                # no future for prefill (or multi-token append); single step needs none
                qi=t.arange(offset,offset+len(ids)).view(-1,1)
                kj=t.arange(offset+len(ids) if not append else ka.shape[-2]).view(1,-1)
                attn=attn.masked_fill(kj>qi,-1e9)
            a=(attn.softmax(-1)@va).transpose(0,1).reshape(-1,576)
            x=x+t.nn.functional.linear(a,w(p+'self_attn.o_proj.weight'))
            h=self._rms(x,w(p+'post_attention_layernorm.weight'))
            a=t.nn.functional.linear(h,w(p+'mlp.gate_proj.weight'))
            b=t.nn.functional.linear(h,w(p+'mlp.up_proj.weight'))
            x=x+t.nn.functional.linear(t.nn.functional.silu(a)*b,w(p+'mlp.down_proj.weight'))
        self.cache=cache_next
        self.pos=offset+len(ids)
        x=self._rms(x[-1],self.w['model.norm.weight'])
        self.calls+=1
        return x@self.emb.T

    def logits(self,ids):
        self.cache=[];self.pos=0;self.prefills+=1
        with self.torch.inference_mode():return self._pass(ids,False)

    def next_step(self,token):
        with self.torch.inference_mode():return self._pass([token],True)

    def generate_chat(self,system:str,user:str,max_tokens=16):
        # Only trusted scaffolding creates role tokens; document text cannot mint one.
        if type(system) is not str or type(user) is not str:
            raise ValueError('typed chat input required')
        tokens=([1]+self.tok.encode('system\n'+system)+[2]
                +[1]+self.tok.encode('user\n'+user)+[2]
                +[1]+self.tok.encode('assistant\n'))
        return self._decode_greedy(tokens,max_tokens)

    def _decode_greedy(self,tokens,max_tokens):
        if type(max_tokens) is not int or not 1<=max_tokens<=MAX_OUTPUT_TOKENS:
            raise ValueError('invalid output budget')
        if len(tokens)>MAX_PROMPT_TOKENS-max_tokens:
            raise ValueError('reader prompt over declared budget')
        generated=[];started_calls=self.calls;logits=self.logits(tokens)
        for _ in range(max_tokens):
            token=int(logits.argmax())
            if token==2:break
            generated.append(token)
            if len(generated)==max_tokens:break
            logits=self.next_step(token)
        return {'text':self.tok.decode(generated),'input_tokens':len(tokens),
                'generated_tokens':len(generated),'prefill_count':1,
                'root_forwards':self.calls-started_calls,'ids':generated}

    def generate(self,prompt,max_tokens=16):
        return self._decode_greedy(self.tok.encode(prompt),max_tokens)
