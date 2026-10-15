"""Experimental *original-weights* MiniLM dense+BM25 LoCoMo retrieval floor.

Three strict phases: prepare the source-only snapshot without labels, rank
with physical original MiniLM weights but NO publisher gold, then separately
score original Reader answers against frozen publisher labels. This is not the
official Hugging Face tokenizer/encoder parity, not strong hybrid RAG, not
Head/graph learning, not 9-arm evidence, and cannot promote any MemoryCell.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import time
import unicodedata

import torch
from torch.nn import functional as F
from safetensors import safe_open

from amcn_original_locomo_trial import (
    CORPUS_SHA256, PROFILE as READER_PROFILE, bm25, conversation_sources,
    canonical, open_pinned, sealed_write, sha,
)
from amcn_original_text_reader import file_sha

PROFILE = 'hepta.amcn.original-locomo-minilm-dense-bm25.floor.shadow.v1'
ORIGINAL_MINILM_SHA = '53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db'
ORIGINAL_VOCAB_SHA = '07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3'
ORIGINAL_TOKENIZER_SHA = 'be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037'
ORIGINAL_READER_SHA = '5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c'
MAX_SEQ = 128
WORD = re.compile(r'\w+', re.UNICODE)


def bare_wordpiece(text, vocab):
    """Experimental BERT-cased-lower WordPiece; official HF parity NOT shown."""
    text = ''.join(c for c in unicodedata.normalize('NFD', text.lower())
                   if not unicodedata.combining(c) and unicodedata.category(c) != 'Cc')
    tokens = []
    word = ''
    for char in text + ' ':
        cat = unicodedata.category(char)
        if char.isspace() or cat[0] in ('P', 'S'):
            if word:
                tokens.append(word)
                word = ''
            if not char.isspace():
                tokens.append(char)
        else:
            word += char
    pieces = [101]
    for w in tokens:
        if len(w) > 100:
            pieces.append(100)
            continue
        if w in vocab:
            pieces.append(vocab[w])
            continue
        start, found = 0, []
        while start < len(w):
            end = len(w)
            part = None
            while end > start:
                sub = ('##' if start else '') + w[start:end]
                if sub in vocab:
                    part = vocab[sub]
                    break
                end -= 1
            if part is None:
                found = [100]
                break
            found.append(part)
            start = end
        pieces.extend(found)
    pieces.append(102)
    if len(pieces) > MAX_SEQ:
        raise ValueError('original context exceeds frozen MiniLM budget; no source truncation')
    return pieces


class OriginalMiniLMBert:
    """True archived checkpoint, FP32 PyTorch BERT, no HF parity claim."""

    def __init__(self, root):
        root = Path(root)
        model, vocabfile, tokenizer = (root/'model.safetensors', root/'vocab.txt',
                                        root/'tokenizer.json')
        for p, want in [(model, ORIGINAL_MINILM_SHA), (vocabfile, ORIGINAL_VOCAB_SHA),
                        (tokenizer, ORIGINAL_TOKENIZER_SHA)]:
            if not p.is_file() or p.is_symlink() or file_sha(p) != want:
                raise ValueError('original MiniLM weight/tokenizer material changed')
        self.vocab = {k.strip():i for i,k in enumerate(vocabfile.read_text().splitlines())}
        if len(self.vocab) != 30522 or any(self.vocab[t] != i for t,i in
                                           {'[PAD]':0,'[UNK]':100,'[CLS]':101,'[SEP]':102}.items()):
            raise ValueError('wrong original WordPiece vocabulary')
        self.config = json.loads((root/'config.json').read_bytes())
        self.weights = {}
        with safe_open(str(model), framework='pt', device='cpu') as f:
            for key in f.keys():
                self.weights[key] = f.get_tensor(key).to(dtype=torch.float32)
        self.calls = 0
        self.count_tokens = 0

    def token_ids(self, text):
        return bare_wordpiece(text, self.vocab)

    def encode(self, texts, *, batch=16):
        if not isinstance(texts,list) or not texts or len(texts) > 8192:
            raise ValueError('bounded original physical encoder corpus')
        rows = [self.token_ids(s) for s in texts]
        self.count_tokens += sum(map(len,rows))
        outputs = []
        torch.set_num_threads(2)
        with torch.inference_mode():
            for start in range(0,len(rows),batch):
                group = rows[start:start+batch]
                n = max(map(len,group))
                ids = torch.tensor([r+[0]*(n-len(r)) for r in group],dtype=torch.long)
                valid = ids.ne(0)
                x = self._bert_forward(ids, valid)
                # SentenceTransformer-style masked mean pooling: diagnostic only.
                pooled = (x * valid.unsqueeze(-1)).sum(1)/valid.sum(1,keepdim=True)
                outputs.append(F.normalize(pooled,dim=-1).cpu())
                self.calls += 1
        return torch.cat(outputs)

    def _bert_forward(self, ids, valid):
        g = self.weights.__getitem__
        batch,n = ids.shape
        cfg = self.config
        h = int(cfg['hidden_size'])
        heads = int(cfg['num_attention_heads'])
        norm = lambda x,w,b: F.layer_norm(x,(h,),weight=w,bias=b,eps=cfg['layer_norm_eps'])
        x = g('embeddings.word_embeddings.weight')[ids]
        x = x + g('embeddings.position_embeddings.weight')[None,:n,:]
        x = x + g('embeddings.token_type_embeddings.weight')[None,0,None,:]
        x = norm(x,g('embeddings.LayerNorm.weight'),g('embeddings.LayerNorm.bias'))
        mask = (~valid).unsqueeze(1).unsqueeze(2)
        for i in range(int(cfg['num_hidden_layers'])):
            pre = f'encoder.layer.{i}.'
            a = pre+'attention.self.'
            q,k,v = (F.linear(x,g(a+t+'.weight'),g(a+t+'.bias'))
                     .reshape(batch,n,heads,h//heads).transpose(1,2)
                     for t in ('query','key','value'))
            logits = q @ k.transpose(-1,-2) / math.sqrt(h//heads)
            logits = logits.masked_fill(mask,-1e4)
            y = (logits.softmax(-1) @ v).transpose(1,2).reshape(batch,n,h)
            w = pre+'attention.output.'
            y = F.linear(y,g(w+'dense.weight'),g(w+'dense.bias'))
            x = norm(x+y,g(w+'LayerNorm.weight'),g(w+'LayerNorm.bias'))
            w = pre+'intermediate.dense.'
            y = F.gelu(F.linear(x,g(w+'weight'),g(w+'bias')))
            w = pre+'output.'
            y = F.linear(y,g(w+'dense.weight'),g(w+'dense.bias'))
            x = norm(x+y,g(w+'LayerNorm.weight'),g(w+'LayerNorm.bias'))
        return x


def prepare_source_only(original_root, existing_public, expected_public_sha, output):
    public = open_pinned(existing_public,expected_public_sha)
    if (set(public)!={'schema','original_dataset_sha256','top_k','cases',
                     'training_labels_or_publisher_gold_present',
                     'original_calendar_future_windows'}
        or public.get('schema') != READER_PROFILE+'.public.v1'
        or public.get('original_dataset_sha256') != CORPUS_SHA256
        or public.get('training_labels_or_publisher_gold_present') is not False
        or public.get('original_calendar_future_windows')!=0):
        raise ValueError('wrong original LoCoMo source-first baseline')
    if (not isinstance(public['cases'],list) or not 1<=len(public['cases'])<=24
        or type(public['top_k']) is not int or not 1<=public['top_k']<=8):
        raise ValueError('unbounded original public case/source budget')
    seen_cases=set()
    for case in public['cases']:
        if not isinstance(case,dict) or set(case)!={'case_id','family','question',
                            'source_ids','passages','question_sha256'}:
            raise ValueError('original public query contains extra/gold fields')
        if (case['case_id'] in seen_cases or not isinstance(case['question'],str)
            or sha256(case['question'].encode()).hexdigest()!=case['question_sha256']):
            raise ValueError('duplicate or changed source-first question')
        seen_cases.add(case['case_id'])
    root = Path(original_root)
    if file_sha(root/'locomo.json') != CORPUS_SHA256:
        raise ValueError('source corpus pin mismatch')
    original = json.loads((root/'locomo.json').read_bytes())
    samples = {str(s['sample_id']):s for s in original}
    inventory = {}
    for case in public['cases']:
        fam = case['family']
        if fam not in inventory:
            if fam not in samples:
                raise ValueError('family absent in original corpus')
            inventory[fam] = conversation_sources(samples[fam])
        if len({x['id'] for x in inventory[fam]}) != len(inventory[fam]):
            raise ValueError('original source id collision')
        re_rank = bm25(case['question'],inventory[fam])[:public['top_k']]
        if [x['id'] for x in re_rank] != case['source_ids'] or [x['text'] for x in re_rank] != case['passages']:
            raise ValueError('frozen original BM25 lexical baseline mismatch')
    packet={'schema':PROFILE+'.source-only.v1',
            'original_dataset_sha256':CORPUS_SHA256,
            'baseline_public_file_sha256':expected_public_sha,
            'baseline_public_payload_sha256':sha(public),
            'full_source_corpus':inventory,
            'cases':public['cases'],'gold_fields_not_exported':True,
            'actual_future_calendar_windows':0,'production_accepted':False}
    sealed_write(output,packet)
    return {'source_file_sha256':file_sha(Path(output)),
            'families':len(inventory),'unique_sources':sum(map(len,inventory.values()))}


def rank_hybrid(source_path,external_source_sha,encoder_root,output_public,output_receipt,
                *, dense_weight=0.5):
    src=open_pinned(source_path,external_source_sha,maximum=8*1024*1024)
    if set(src)!={'schema','original_dataset_sha256','baseline_public_file_sha256',
                 'baseline_public_payload_sha256','full_source_corpus','cases',
                 'gold_fields_not_exported','actual_future_calendar_windows','production_accepted'}:
        raise ValueError('source-only source packet has forbidden extra fields')
    if src['schema']!=PROFILE+'.source-only.v1' or src['gold_fields_not_exported'] is not True or src['production_accepted'] is not False:
        raise ValueError('source packet may contain publisher gold')
    seen_cases=set()
    for case in src['cases']:
        if (not isinstance(case,dict) or set(case)!={'case_id','family','question',
                                 'source_ids','passages','question_sha256'}
            or case['case_id'] in seen_cases or case['family'] not in src['full_source_corpus']
            or sha256(case['question'].encode()).hexdigest()!=case['question_sha256']):
            raise ValueError('source-only case smuggled gold or changed original query')
        seen_cases.add(case['case_id'])
        if (not isinstance(case['source_ids'],list) or not 1<=len(case['source_ids'])<=8
            or len(set(case['source_ids']))!=len(case['source_ids'])
            or len(case['passages'])!=len(case['source_ids'])):
            raise ValueError('source-first final budget or evidence collision')
    for fam,docs in src['full_source_corpus'].items():
        if not isinstance(docs,list) or not 1<=len(docs)<=8192:
            raise ValueError('unbounded original source roster')
        for d in docs:
            if (not isinstance(d,dict) or set(d)!={'id','root','text'}
                or d['root']!=fam or not isinstance(d['text'],str)
                or len(d['text'].encode())>640):
                raise ValueError('gold-bearing or invalid source roster')
    if type(dense_weight) is not float or dense_weight!=0.5:
        raise ValueError('frozen prior shared 50/50 mixing policy required')
    if Path(output_public).exists() or Path(output_receipt).exists():
        raise ValueError('create-only hybrid outputs')
    model=OriginalMiniLMBert(encoder_root)
    begin=time.monotonic()
    family_vectors={}
    original_sources=src['full_source_corpus']
    for fam,docs in original_sources.items():
        if not 1<=len(docs)<=8192 or len({d['id'] for d in docs})!=len(docs):
            raise ValueError('corrupt original source family inventory')
        family_vectors[fam]=model.encode([x['text'] for x in docs])
    report=[];new_cases=[]
    for case in src['cases']:
        docs=original_sources[case['family']]
        question=case['question']
        # Reconstruct full-corpus original BM25 distribution before labels.
        terms=set(WORD.findall(question.casefold()))
        bags=[Counter(WORD.findall(z['text'].casefold())) for z in docs]
        n=len(docs);average=max(1,sum(sum(b.values()) for b in bags)/n)
        df={w:sum(w in b for b in bags) for w in terms}
        bm=[]
        for bag in bags:
            L=sum(bag.values());v=0.
            for w in terms:
                tf=bag[w]
                if tf:
                    v+=math.log(1+(n-df[w]+0.5)/(df[w]+0.5))*tf*2.2/(tf+1.2*(0.25+0.75*L/average))
            bm.append(v)
        legacy=sorted(range(n), key=lambda idx:(-bm[idx],docs[idx]['id']))[:len(case['source_ids'])]
        if [docs[i]['id'] for i in legacy]!=case['source_ids']:
            raise ValueError('BM25 source-ranking drift')
        q=model.encode([question])[0]
        dense=(family_vectors[case['family']] @ q).tolist()
        bmmax=max(bm)
        # Per-question deterministic normalization; zero BM25 goes to zero.
        normalized=[v/bmmax if bmmax>0 else 0.0 for v in bm]
        mixed=[(1-dense_weight)*b+dense_weight*(d+1)/2 for b,d in zip(normalized,dense)]
        winners=sorted(range(n), key=lambda idx:(-mixed[idx],docs[idx]['id']))[:len(case['source_ids'])]
        selected=[docs[i] for i in winners]
        new_cases.append({**case,'source_ids':[z['id'] for z in selected],
                          'passages':[z['text'] for z in selected]})
        report.append({'case_id':case['case_id'],'family':case['family'],
                       'lexical_original_ids':case['source_ids'],
                       'hybrid_source_ids':[z['id'] for z in selected],
                       'lexical_vs_hybrid_overlap':len(set(case['source_ids']) & set(z['id'] for z in selected)),
                       'top_bm25':round(float(bmmax),6),
                       'top_cosine':round(float(max(dense)),6)})
    out={'schema':READER_PROFILE+'.public.v1','original_dataset_sha256':CORPUS_SHA256,
         'top_k':len(new_cases[0]['source_ids']),'cases':new_cases,
         'training_labels_or_publisher_gold_present':False,
         'original_calendar_future_windows':0}
    receipt={'schema':PROFILE+'.original-mixing-physical-diagnostic.v1',
             'input_source_file_sha256':external_source_sha,
             'source_snapshot_sha256':sha(src),
             'original_encoder_safetensors_sha256':ORIGINAL_MINILM_SHA,
             'original_encoder_vocab_sha256':ORIGINAL_VOCAB_SHA,
             'original_encoder_tokenizer_sha256':ORIGINAL_TOKENIZER_SHA,
             'official_hf_encoder_forward_parity_verified':False,
             'official_hf_wordpiece_parity_verified':False,
             'physical_pretrained_embedding_calls':model.calls,
             'total_original_encoder_tokens':model.count_tokens,
             'physical_wall_seconds':time.monotonic()-begin,
             'frozen_dense_weight':dense_weight,
             'original_question_count':len(report),
             'cases':report,
             'hybrid_public_payload_sha256':sha(out),
             'publisher_gold_read_during_rank':False,
             'real_strong_hybrid_rag_comparator':False,
             'typed_head_updated':False,'graph_weights_updated':False,
             'independent_future_calendar_windows':0,'production_accepted':False}
    sealed_write(output_public,out)
    sealed_write(output_receipt,receipt)
    return {'hybrid_public_sha256':file_sha(Path(output_public)),
            'retrieval_receipt_sha256':file_sha(Path(output_receipt)),
            'changed_question_evidence':sum(c['lexical_original_ids']!=c['hybrid_source_ids'] for c in report)}


def score_paired(original_public,original_public_sha,original_answers,original_answers_sha,
                 hybrid_public,hybrid_public_sha,hybrid_answers,hybrid_answers_sha,
                 withheld,withheld_sha,hybrid_retrieval_receipt,hybrid_receipt_sha,output):
    old_plan=open_pinned(original_public,original_public_sha)
    old=open_pinned(original_answers,original_answers_sha)
    new_plan=open_pinned(hybrid_public,hybrid_public_sha)
    new=open_pinned(hybrid_answers,hybrid_answers_sha)
    withheld=open_pinned(withheld,withheld_sha)
    retrieval=open_pinned(hybrid_retrieval_receipt,hybrid_receipt_sha)
    for record,plan in [(old,old_plan),(new,new_plan)]:
        if (record.get('schema')!=READER_PROFILE+'.raw-model-answers.v1'
            or record['public_payload_sha256']!=sha(plan)
            or record['model_answers_generated']!=len(plan['cases'])
            or record['gold_opened_during_model_execution'] is not False
            or record.get('production_accepted') is not False
            or record.get('nine_cell_arms') is not False
            or record.get('strong_hybrid_rag') is not False):
            raise ValueError('answer provenance/plan mismatch')
    if withheld.get('public_payload_sha256')!=sha(old_plan) or retrieval.get('hybrid_public_payload_sha256')!=sha(new_plan):
        raise ValueError('publisher target or hybrid receipt source binding changed')
    if (old.get('original_reader_model_sha256')!=ORIGINAL_READER_SHA
        or old.get('original_reader_model_sha256')!=new.get('original_reader_model_sha256')
        or old.get('original_reader_tokenizer_sha256')!=new.get('original_reader_tokenizer_sha256')
        or old.get('original_reader_tokenizer_sha256')!='9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c'):
        raise ValueError('different Reader/model/tokenizer material in paired experiment')
    if old_plan.get('top_k') != new_plan.get('top_k') or old_plan['top_k']!=3:
        raise ValueError('unmatched final evidence count')
    if retrieval.get('official_hf_encoder_forward_parity_verified') is not False or retrieval.get('publisher_gold_read_during_rank') is not False:
        raise ValueError('incorrect external eligibility')
    oldq={x['case_id']:x for x in old_plan['cases']};newq={x['case_id']:x for x in new_plan['cases']}
    olds={x['case_id']:x for x in old['cases']};news={x['case_id']:x for x in new['cases']}
    labels={x['case_id']:x for x in withheld['gold_cases']}
    if not all(len(d)==len(oldq) for d in (oldq,newq,olds,news,labels)) or not set(oldq)==set(newq)==set(olds)==set(news)==set(labels):
        raise ValueError('incomplete/duplicated original case census')
    outcomes=[]
    for key in sorted(oldq):
        q1,q2=oldq[key],newq[key]
        a,b=olds[key],news[key]
        gold=labels[key]
        if (q1['family']!=q2['family'] or q1['question_sha256']!=q2['question_sha256']
            or q1['family']!=gold['family'] or a['family']!=q1['family'] or b['family']!=q1['family']):
            raise ValueError('question/family ID switched across originals')
        if (a['output_tokens']>24 or b['output_tokens']>24 or
            type(a['input_tokens']) is not int or type(b['input_tokens']) is not int):
            raise ValueError('original matched generation token ceiling changed')
        if (a['source_ids']!=q1['source_ids'] or b['source_ids']!=q2['source_ids']
            or any(z['raw_answer_sha256']!=sha256(z['raw_answer'].encode()).hexdigest() for z in (a,b))):
            raise ValueError('original answers or exact delivered evidence edited')
        support=set(gold['publisher_evidence'])
        outcomes.append({'case_id_sha256':sha256(key.encode()).hexdigest(),
                         'family':gold['family'],
                         'original_support_covered_at_3':bool(support & set(a['source_ids'])),
                         'hybrid_support_covered_at_3':bool(support & set(b['source_ids'])),
                         'original_exact_answer':a['raw_answer'].strip().casefold()==gold['publisher_answer'].strip().casefold(),
                         'hybrid_exact_answer':b['raw_answer'].strip().casefold()==gold['publisher_answer'].strip().casefold(),
                         'original_ceiling':a['reached_output_ceiling'],
                         'hybrid_ceiling':b['reached_output_ceiling']})
    result={'schema':PROFILE+'.paired-publisher-weak-post-seal-score.v1',
            'source_legacy_original_answers_sha256':original_answers_sha,
            'source_hybrid_original_answers_sha256':hybrid_answers_sha,
            'heldout_publisher_label_file_sha256':withheld_sha,
            'actual_original_pretrained_dense_mixing':True,
            'official_hf_model_or_tokenizer_parity_verified':False,
            'questions':len(outcomes),'independent_source_families_upper_bound':len({x['family'] for x in outcomes}),
            'original_support_covered_at_k':sum(x['original_support_covered_at_3'] for x in outcomes),
            'hybrid_support_covered_at_k':sum(x['hybrid_support_covered_at_3'] for x in outcomes),
            'original_reader_input_tokens':sum(x['input_tokens'] for x in old['cases']),
            'hybrid_reader_input_tokens':sum(x['input_tokens'] for x in new['cases']),
            'exact_total_input_compute_budget_matched':(sum(x['input_tokens'] for x in old['cases'])==sum(x['input_tokens'] for x in new['cases'])),
            'same_final_source_slots_and_output_ceiling':True,
            'original_literal_match':sum(x['original_exact_answer'] for x in outcomes),
            'hybrid_literal_match':sum(x['hybrid_exact_answer'] for x in outcomes),
            'per_question':outcomes,'independent_semantic_success':None,
            'real_strong_hybrid_rag_e2e_gain':None,
            'typed_cell_gain':None,'learned_graph_gain':None,
            'new_future_calendar_windows':0,'production_accepted':False}
    sealed_write(output,result)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='operation',required=True)
    x=sub.add_parser('prepare')
    x.add_argument('--original-root',type=Path,required=True);x.add_argument('--original-public',type=Path,required=True)
    x.add_argument('--original-public-sha256',required=True);x.add_argument('--output',type=Path,required=True)
    x=sub.add_parser('rank')
    x.add_argument('--source',type=Path,required=True);x.add_argument('--source-sha256',required=True)
    x.add_argument('--encoder',type=Path,required=True);x.add_argument('--output-public',type=Path,required=True)
    x.add_argument('--output-receipt',type=Path,required=True)
    x=sub.add_parser('score')
    fields=['original_public','original_answers','hybrid_public','hybrid_answers','withheld','hybrid_retrieval_receipt']
    for f in fields:
        x.add_argument('--'+f.replace('_','-'),type=Path,required=True)
        x.add_argument('--'+f.replace('_','-')+'-sha256',required=True)
    x.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.operation=='prepare':report=prepare_source_only(a.original_root,a.original_public,a.original_public_sha256,a.output)
    elif a.operation=='rank':report=rank_hybrid(a.source,a.source_sha256,a.encoder,a.output_public,a.output_receipt)
    else:report=score_paired(*(v for f in fields for v in (getattr(a,f),getattr(a,f+'_sha256'))),a.output)
    print(json.dumps(report,sort_keys=True,allow_nan=False))


if __name__=='__main__':
    main()
