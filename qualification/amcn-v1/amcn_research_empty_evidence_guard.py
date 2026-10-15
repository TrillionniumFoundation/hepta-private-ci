"""Detached HNMF research pre-dispatch guard: empty evidence must not call Reader.

Prevents a specific original 20/20 observed failure mode (no-evidence prompts
answered rather than abstained). It does not change archived Reader answers,
authenticate a Source owner, establish evidence entailment, or grant FinalUse.
"""
from __future__ import annotations

from hashlib import sha256
import re

_SHA = re.compile(r'[0-9a-f]{64}\Z')
PROFILE = 'hepta.amcn.empty-evidence-predispatch.shadow.v1'
MAX_SOURCE_BYTES = 32768


def require(condition, why):
    if not condition:
        raise ValueError(why)


def admit_for_research(question: str, sources: list[dict], latest_by_id: dict,
                       *, scope: str, generation: str):
    """Return an *instruction* to dispatch or abstain; never execute a model.

    Source-record checking follows the existing immutable-revision/withdrawal
    contract. External owner signatures and currentness are still separately
    required; this function cannot authenticate the supplied latest snapshot.
    """
    require(isinstance(question,str) and bool(question.strip()) and 0 < len(question.encode('utf-8')) <= 8192,
            'bounded question required')
    require(isinstance(scope,str) and bool(scope) and isinstance(generation,str)
            and bool(generation) and isinstance(latest_by_id,dict),
            'bounded source context required')
    require(isinstance(sources,(list,tuple)) and len(sources)<=16,
            'hard final evidence-window cap exceeded')
    ids=[]
    for e in sources:
        require(isinstance(e,dict) and set(e)=={
            'source_id','source_root','scope','generation','revision',
            'text','content_sha256','revoked'}, 'exact immutable evidence contract required')
        require(all(isinstance(e[k],str) and e[k] and len(e[k])<=256 for k in
                    ('source_id','source_root','scope','generation'))
                and type(e['revision']) is int and e['revision']>0
                and isinstance(e['text'],str) and bool(e['text'].strip())
                and len(e['text'].encode('utf-8'))<=MAX_SOURCE_BYTES
                and isinstance(e['content_sha256'],str)
                and _SHA.fullmatch(e['content_sha256']) is not None
                and e['content_sha256']==sha256(e['text'].encode('utf-8')).hexdigest()
                and e['scope']==scope and e['generation']==generation
                and e['revoked'] is False, 'revoked/foreign/modified source')
        sid=e['source_id']
        require(sid not in ids,'repeated source reference')
        current=latest_by_id.get(sid)
        require(isinstance(current,dict) and all(current.get(k)==e[k] for k in
                    ('source_id','source_root','scope','generation','revision',
                     'content_sha256','revoked')) and current.get('revoked') is False,
                'source owner frontier withdrawn, stale or changed')
        ids.append(sid)
    if not ids:
        return {'profile':PROFILE, 'decision':'abstain_without_model',
                'literal_answer':'unknown', 'reader_calls':0,'reader_input_tokens':0,
                'reader_output_tokens':0,'cited_source_ids':[],
                'source_owner_independently_authenticated':False,
                'independent_semantic_correctness':None,
                'new_reader_task_success_claim':False,'production_accepted':False}
    return {'profile':PROFILE,'decision':'candidate_dispatch_requires_external_owner_and_reader',
            'source_ids':ids,'reader_calls':0,'model_not_yet_invoked':True,
            'source_owner_independently_authenticated':False,
            'independent_semantic_correctness':None,
            'new_reader_task_success_claim':False,'production_accepted':False}
