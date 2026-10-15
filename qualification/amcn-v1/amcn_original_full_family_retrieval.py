"""Label-blind ORIGINAL LoCoMo all-family frozen Encoder retrieval study.

Research/DENY_ALL, not strong hybrid RAG, independent future windows or
whole-task success. The rank phase accepts only source-only packets and
physically executes the archived MiniLM; the score phase opens publisher-weak
targets *after* create-only predictions are sealed. No production writer.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from math import isfinite, log
from pathlib import Path
import re
import time

import numpy as np

from amcn_original_locomo_trial import (CORPUS_SHA256, conversation_sources,
    sealed_write, open_pinned, sha, bm25)
from amcn_original_hybrid_floor import OriginalMiniLMBert, ORIGINAL_MINILM_SHA
from amcn_original_text_reader import file_sha

PROFILE = 'hepta.amcn.original-locomo-ten-family-frozen-minilm-retrieval.shadow.v1'
SPLITS = {'conv-26':'train','conv-30':'train','conv-41':'train',
          'conv-42':'train','conv-43':'train','conv-44':'train',
          'conv-47':'select','conv-48':'select',
          'conv-49':'retrospective_heldout_a','conv-50':'retrospective_heldout_b'}
ARMS = ('bm25','dense_original_minilm','bm25_dense_half','rrf_60')
MAX_K = 16
SUPPORT_RE = re.compile(r'D(\d+):0*(\d+)', re.IGNORECASE)


def _source_alias(text):
    match = SUPPORT_RE.fullmatch(text.strip())
    return f'D{int(match.group(1))}:{int(match.group(2))}' if match else None


def split_publisher_support(raw):
    """Decompose compound ORIGINAL publisher strings without inventing links."""
    if not isinstance(raw, list) or len(raw) > 128:
        raise ValueError('invalid publisher original evidence list')
    entries=[]; unresolved=[]
    for item in raw:
        if not isinstance(item,str) or len(item)>2048:
            raise ValueError('unknown original publisher citation')
        matches=list(SUPPORT_RE.finditer(item))
        if not matches:
            unresolved.append(item)
        else:
            for match in matches:
                entries.append(f'D{int(match.group(1))}:{int(match.group(2))}')
            if SUPPORT_RE.sub('',item).strip(' ;,\t\r\n'):
                unresolved.append(item)
    return sorted(set(entries)), unresolved


def prepare(corpus_root, public_out, withheld_out):
    original=Path(corpus_root)/'locomo.json'
    if file_sha(original)!=CORPUS_SHA256:
        raise ValueError('original publisher dataset SHA mismatch')
    data=json.loads(original.read_bytes())
    if not isinstance(data,list) or len(data)!=len(SPLITS):
        raise ValueError('original independent family count drift')
    cases=[]; sources={}; targets=[]
    for sample in data:
        family=str(sample['sample_id'])
        if family not in SPLITS or family in sources:
            raise ValueError('unknown/duplicated original family')
        src=conversation_sources(sample)
        # Do not place annotations, categories, answer or support in PUBLIC.
        normalized={x['id']:_source_alias(x['id']) for x in src}
        if None in normalized.values() or len(set(normalized.values()))!=len(src):
            raise ValueError('unresolvable original dialogue identity')
        sources[family]=src
        for qi,q in enumerate(sample['qa']):
            question=q.get('question')
            if type(question) is not str or not question or len(question)>512:
                raise ValueError('original question length/source drift')
            case_id=f'{family}:{qi}'
            cases.append({'case_id':case_id,'family':family,'split':SPLITS[family],
                          'question':question, 'question_sha256':sha256(question.encode()).hexdigest()})
            support,unresolved=split_publisher_support(q.get('evidence',[]))
            targets.append({'case_id':case_id,'family':family,
                            'publisher_support':support,'unresolved_citation_strings':unresolved})
    pub={'schema':PROFILE+'.source-only.v1','dataset_sha256':CORPUS_SHA256,
         'source_families':sources,'cases':cases,'split_by_family':SPLITS,
         'publisher_targets_not_included':True,'calendar_future_windows':0,
         'production_accepted':False}
    gold={'schema':PROFILE+'.publisher-weak-targets.v1','public_payload_sha256':sha(pub),
          'cases':targets,'independent_human_entailment':False,
          'calendar_future_windows':0}
    sealed_write(public_out,pub)
    sealed_write(withheld_out,gold)
    return {'sources':sum(len(x) for x in sources.values()),'questions':len(cases),
            'families':len(sources),'source_sha256':file_sha(public_out),
            'withheld_sha256':file_sha(withheld_out)}


class SourceFirstBM25Index:
    """Exact original BM25 formula with term counts indexed ONCE per family.

    Reproduces Unicode word-tokenization and source-ID tie-break.
    Does not inspect QA targets, date truth, Reader answers or publisher gold.
    """
    WORD = re.compile(r'\w+', re.UNICODE)

    def __init__(self, sources):
        self.ids=[row['id'] for row in sources]
        if len(set(self.ids))!=len(self.ids) or not self.ids:
            raise ValueError('duplicate BM25 source identities')
        self.n=len(sources)
        self.lengths=np.empty(self.n, dtype=np.float64)
        postings=defaultdict(list)
        for i,row in enumerate(sources):
            counts=Counter(self.WORD.findall(row['text'].casefold()))
            self.lengths[i]=sum(counts.values())
            for tok,tf in counts.items():
                postings[tok].append((i,tf))
        self.avg=max(1.0,float(self.lengths.mean()))
        self.postings={tok:(np.array([i for i,tf in vals],dtype=np.int64),
                            np.array([tf for i,tf in vals],dtype=np.float64))
                       for tok,vals in postings.items()}

    def rank(self,question):
        arr=np.zeros(self.n,dtype=np.float64)
        for tok in set(self.WORD.findall(question.casefold())):
            if tok not in self.postings:
                continue
            idx,tf=self.postings[tok]
            df=len(idx)
            term_idf=log(1+(self.n-df+0.5)/(df+0.5))
            denom=tf+1.2*(0.25+0.75*self.lengths[idx]/self.avg)
            arr[idx]+=term_idf*(2.2*tf/denom)
        return sorted(self.ids,key=lambda sid:(-arr[self._position[sid]],sid))

    @property
    def _position(self):
        # cached lazily after first access; convert once instead of per rank
        if not hasattr(self,'_index_by_id'):
            self._index_by_id={sid:i for i,sid in enumerate(self.ids)}
        return self._index_by_id


def _ranks(values, ordered_ids):
    return sorted(range(len(ordered_ids)), key=lambda j:(-float(values[j]),ordered_ids[j]))


def rank(public_file,public_sha,encoder_root,out_file,*,batch=32):
    if Path(out_file).exists() or Path(out_file).is_symlink():
        raise ValueError('create-only frozen model predictions')
    p=open_pinned(public_file,public_sha,maximum=12*1024*1024)
    if (set(p)!={'schema','dataset_sha256','source_families','cases',
                'split_by_family','publisher_targets_not_included',
                'calendar_future_windows','production_accepted'} or
            p['schema']!=PROFILE+'.source-only.v1' or
            p['dataset_sha256']!=CORPUS_SHA256 or
            p['publisher_targets_not_included'] is not True or
            p['calendar_future_windows']!=0 or p['production_accepted'] is not False or
            p['split_by_family']!=SPLITS or set(p['source_families'])!=set(SPLITS)):
        raise ValueError('gold-bearing or changed original source cohort')
    questions=p['cases'];groups=defaultdict(list)
    if not isinstance(questions,list) or not 1000<=len(questions)<=2200:
        raise ValueError('missing original complete question census')
    seen=set()
    for case in questions:
        if set(case)!={'case_id','family','split','question','question_sha256'}:
            raise ValueError('gold-bearing extra original question field')
        if case['case_id'] in seen or case['family'] not in SPLITS or case['split']!=SPLITS[case['family']]:
            raise ValueError('duplicated/foreign question/source family')
        seen.add(case['case_id'])
        if sha256(case['question'].encode()).hexdigest()!=case['question_sha256']:
            raise ValueError('question changed after original seal')
        groups[case['family']].append(case)
    if set(groups)!=set(SPLITS):
        raise ValueError('no original family omitted')
    start=time.perf_counter()
    encoder=OriginalMiniLMBert(encoder_root)
    result=[]
    count_sources=0
    # Gold/QA answers never cross this function's arguments or process.
    for family, rows in sorted(groups.items()):
        sources=p['source_families'][family]
        if not isinstance(sources,list) or not 1<=len(sources)<=1000:
            raise ValueError('missing bounded original sources')
        ids=[s['id'] for s in sources]
        if len(set(ids))!=len(ids) or any(set(s)!={'id','root','text'} or s['root']!=family for s in sources):
            raise ValueError('foreign/duplicate evidence root')
        count_sources+=len(sources)
        print('ENCODER family',family,'source count',len(sources),'questions',len(rows),flush=True)
        source_vectors=encoder.encode([s['text'] for s in sources],batch=batch).numpy()
        question_vectors=encoder.encode([q['question'] for q in rows],batch=batch).numpy()
        dense_matrix=question_vectors @ source_vectors.T
        index=SourceFirstBM25Index(sources)
        for qi,case in enumerate(rows):
            base=index.rank(case['question'])
            bmpos={sid:j for j,sid in enumerate(base)}
            scores=dense_matrix[qi]
            dense_idx=_ranks(scores,ids)
            dense=[ids[j] for j in dense_idx]
            denpos={sid:j for j,sid in enumerate(dense)}
            # Precommitted, label-free rank aggregation. NOT trained RAG.
            half=sorted(ids,key=lambda sid:(-(1-bmpos[sid]/max(1,len(ids)-1))*0.5
                                            -(1-denpos[sid]/max(1,len(ids)-1))*0.5,sid))
            rrf=sorted(ids,key=lambda sid:(-(1/(60+1+bmpos[sid])+1/(60+1+denpos[sid])),sid))
            selections=dict(zip(ARMS,(base[:MAX_K],dense[:MAX_K],half[:MAX_K],rrf[:MAX_K])))
            result.append({'case_id':case['case_id'],'family':family,'split':case['split'],
                           'question_sha256':case['question_sha256'],
                           'ranked_source_ids':selections})
        print('FINISHED family',family,'processed',len(rows),'encoder_calls',encoder.calls,flush=True)
    if len(result)!=len(questions):
        raise ValueError('partial physical original pretrained prediction census')
    obj={'schema':PROFILE+'.sealed-retrieval.v1','original_public_file_sha256':public_sha,
         'original_public_payload_sha256':sha(p),
         'original_encoder_sha256':ORIGINAL_MINILM_SHA,
         'frozen_retrieval_arms':list(ARMS),'final_top_k':MAX_K,
         'case_predictions':result,'original_source_count':count_sources,
         'original_query_count':len(result),
         'original_encoder_calls':encoder.calls,
         'original_encoder_token_positions':encoder.count_tokens,
         'original_encoder_wall_seconds':time.perf_counter()-start,
         'real_original_pretrained_forward':True,
         'official_hf_tokenizer_model_parity_proven':False,
         'training_or_publisher_gold_accessed':False,
         'independent_future_calendar_windows':0,'production_accepted':False}
    sealed_write(out_file,obj)
    return {'prediction_sha256':file_sha(out_file),'original_encoder_calls':encoder.calls,
            'original_encoder_token_positions':encoder.count_tokens,
            'cases':len(result),'families':len(groups)}


def score(source_file,source_sha,original_predictions,orig_pred_sha,
          withheld_file,withheld_sha,output_file):
    public=open_pinned(source_file,source_sha,maximum=12*1024*1024)
    pred=open_pinned(original_predictions,orig_pred_sha,maximum=12*1024*1024)
    gold=open_pinned(withheld_file,withheld_sha,maximum=12*1024*1024)
    if (pred.get('schema')!=PROFILE+'.sealed-retrieval.v1' or
        gold.get('schema')!=PROFILE+'.publisher-weak-targets.v1' or
        pred.get('original_public_file_sha256')!=source_sha or
        pred.get('original_public_payload_sha256')!=sha(public) or
        gold.get('public_payload_sha256')!=sha(public) or
        pred.get('training_or_publisher_gold_accessed') is not False or
        pred.get('real_original_pretrained_forward') is not True or
        pred.get('original_encoder_sha256')!=ORIGINAL_MINILM_SHA or
        pred.get('official_hf_tokenizer_model_parity_proven') is not False or
        pred.get('original_query_count')!=len(public['cases']) or
        pred.get('frozen_retrieval_arms')!=list(ARMS) or
        pred.get('final_top_k')!=MAX_K):
        raise ValueError('missing original physical retrieval/source-gold isolation')
    originals={x['case_id']:x for x in public['cases']}
    withheld={x['case_id']:x for x in gold['cases']}
    predicts={x['case_id']:x for x in pred['case_predictions']}
    if len(originals)!=len(withheld) or len(predicts)!=len(originals) or set(originals)!=set(withheld)!=set(predicts):
        raise ValueError('incomplete original question denominator')
    sources={family:{s['id']:_source_alias(s['id']) for s in src}
             for family,src in public['source_families'].items()}
    details=[];splits=defaultdict(lambda:defaultdict(list));families=defaultdict(lambda:defaultdict(list))
    for case_id,orig in originals.items():
        case=predicts[case_id];targets=withheld[case_id]
        if (case['family']!=orig['family'] or case['split']!=orig['split'] or
            case['question_sha256']!=orig['question_sha256'] or
            targets['family']!=orig['family'] or
            set(case['ranked_source_ids'])!=set(ARMS)):
            raise ValueError('source/family/arm switched after prediction seal')
        support=set(targets['publisher_support'])
        for arm in ARMS:
            top=case['ranked_source_ids'][arm]
            if not isinstance(top,list) or len(top)!=MAX_K or len(top)!=len(set(top)):
                raise ValueError('missing/duplicated original output list')
            if any(sid not in sources[orig['family']] for sid in top):
                raise ValueError('foreign original source identity in model rank')
            normalized=[sources[orig['family']][sid] for sid in top]
            if None in normalized:raise ValueError('uncanonical original cited dialogue identity')
            rank=next((i+1 for i,k in enumerate(normalized) if k in support),None)
            row={'hit1':int(rank==1),'hit3':int(rank is not None and rank<=3),
                 'hit8':int(rank is not None and rank<=8),'hit16':int(rank is not None),
                 'mrr16':1/rank if rank else 0.,
                 'all3':int(bool(support) and support <= set(normalized[:3])),
                 'all8':int(bool(support) and support <= set(normalized[:8])),
                 'all16':int(bool(support) and support <= set(normalized)),
                 'any_original_weak_label_in_corpus':int(bool(support & set(sources[orig['family']].values())))}
            splits[orig['split']][arm].append(row)
            families[orig['family']][arm].append(row)
        details.append({'case_id_sha256':sha256(case_id.encode()).hexdigest(),
                        'family':orig['family'],'split':orig['split'],
                        'unresolved_publisher_annotations':len(targets['unresolved_citation_strings']),
                        'publisher_cited_source_count':len(support)})
    metrics=('hit1','hit3','hit8','hit16','mrr16','all3','all8','all16')
    def summarise(rows):
        return {'questions':len(rows),
                **{m:round(sum(r[m] for r in rows),9) for m in metrics},
                'mrr16_mean':round(sum(r['mrr16'] for r in rows)/len(rows),9),
                'no_registered_support_in_corpus':sum(r['any_original_weak_label_in_corpus']==0 for r in rows)}
    report={
        'schema':PROFILE+'.post-seal-publisher-weak-evaluation.v1',
        'original_source_sha256':source_sha,
        'original_predictions_sha256':orig_pred_sha,
        'publisher_labels_sha256':withheld_sha,
        'real_original_pretrained_encoder_forward':True,
        'official_hf_parity_qualified':False,
        'independent_semantic_task_success':None,
        'original_reader_answers_new':0,
        'strict_equal_compute_work_budget':False,
        'retrospective_future_partitions_are_calendar_future':False,
        'source_families_upper_bound':len(SPLITS),
        'complete_original_questions':len(originals),
        'original_source_turns':pred['original_source_count'],
        'physical_miniLM_encoder_calls':pred['original_encoder_calls'],
        'physical_miniLM_token_positions':pred['original_encoder_token_positions'],
        'per_family':{f:{arm:summarise(rows) for arm,rows in arms.items()} for f,arms in sorted(families.items())},
        'per_partition':{s:{arm:summarise(rows) for arm,rows in arms.items()} for s,arms in sorted(splits.items())},
        'publisher_annotations_with_unresolved_strings':sum(x['unresolved_publisher_annotations']>0 for x in details),
        'scoring_does_not_authenticate_original_publisher_labels':True,
        'three_axis_memory_cell_conclusions':None,
        'production_accepted':False,
    }
    sealed_write(output_file,report)
    return report


def main():
    parser=argparse.ArgumentParser()
    command=parser.add_subparsers(dest='phase',required=True)
    p=command.add_parser('prepare');p.add_argument('--archive-root',type=Path,required=True)
    p.add_argument('--public',type=Path,required=True);p.add_argument('--withheld',type=Path,required=True)
    p=command.add_parser('rank');p.add_argument('--public',type=Path,required=True)
    p.add_argument('--public-sha',required=True);p.add_argument('--encoder',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--batch',type=int,default=32)
    p=command.add_parser('score');p.add_argument('--public',type=Path,required=True)
    p.add_argument('--public-sha',required=True);p.add_argument('--ranked',type=Path,required=True)
    p.add_argument('--ranked-sha',required=True);p.add_argument('--withheld',type=Path,required=True)
    p.add_argument('--withheld-sha',required=True);p.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.phase=='prepare':res=prepare(args.archive_root,args.public,args.withheld)
    elif args.phase=='rank':res=rank(args.public,args.public_sha,args.encoder,args.output,batch=args.batch)
    else:res=score(args.public,args.public_sha,args.ranked,args.ranked_sha,args.withheld,args.withheld_sha,args.output)
    print(json.dumps(res,sort_keys=True))
if __name__=='__main__':main()
