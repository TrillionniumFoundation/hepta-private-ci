"""Source-only NO-GO gate over original privately recounted 96 Reader attempts.

Exact checksum verifies a published *authored* aggregate. It is NOT an external
model-host signature; the private journal proof runs separately with original
SHA-pinned inputs and original ByteLevel Tokenizer installed on analysis host.
"""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
from pathlib import Path

PROFILE='hepta.amcn.original-reader-96-private-byte-recount.no-go.v1'
REPORT_SHA='13f6488f4d25bae2cbe61a08f4eba6cb23ab783f910416bace2f8bbb8e2875b6'
EXPECTED={
    'annotation':{'calls':48,'input_tokens':6371,'output_tokens':1059,
                  'answers_with_citation_tag':14,'citation_tag_count':14,
                  'citation_outside_delivered_evidence':0,
                  'zero_evidence_calls':12,'zero_evidence_nonabstentions':12,
                  'literal_abstention_observed':0},
    'verbatim':{'calls':32,'input_tokens':4285,'output_tokens':681,
                'answers_with_citation_tag':6,'citation_tag_count':6,
                'citation_outside_delivered_evidence':0,
                'zero_evidence_calls':8,'zero_evidence_nonabstentions':8,
                'literal_abstention_observed':0},
    'long':{'calls':16,'input_tokens':2691,'output_tokens':629,
            'answers_with_citation_tag':7,'citation_tag_count':10,
            'citation_outside_delivered_evidence':0},
}


def verify(report):
    if not isinstance(report,dict) or report.get('profile')!=PROFILE:
        raise ValueError('unknown original historical source receipt')
    if not (report.get('original_attempts_recounted')==96
            and report.get('original_24_to_64_greedy_prefix_pairs_verified')==16
            and report.get('no_evidence_calls')==20
            and report.get('no_evidence_nonabstaining_outputs')==20
            and report.get('no_evidence_literal_abstention_outputs')==0
            and report.get('original_model_sha256')==
                '5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c'
            and report.get('original_tokenizer_sha256')==
                '9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c'
            and report.get('all_success_status') is True):
        raise ValueError('original original Reader census or model material drift')
    got=report.get('cohort_stats')
    if not isinstance(got,dict) or set(got)!=set(EXPECTED):
        raise ValueError('incomplete original response cohorts')
    for cohort,values in EXPECTED.items():
        if not isinstance(got[cohort],dict) or any(got[cohort].get(k)!=v for k,v in values.items()):
            raise ValueError('original response/cost/citation/abstention drift')
    if not (sum(v['answers_with_citation_tag'] for v in got.values())==27
            and sum(v['citation_tag_count'] for v in got.values())==30):
        raise ValueError('citation syntax summary drift')
    negatives=('production_accepted','tokenizer_official_HF_parity_verified',
               'model_host_independent_attestation','memorycell_learning_gain_proven',
               'publisher_answers_or_raw_dialogue_uploaded')
    if any(report.get(x) is not False for x in negatives):
        raise ValueError('unverified model/owner/semantic admission asserted')
    if (report.get('independent_human_semantic_entailment') is not None or
            report.get('future_calendar_windows')!=0 or
            report.get('literal_abstention_is_not_semantic_certification') is not True):
        raise ValueError('promoted original citation syntax as semantic quality')
    return {'reader_no_evidence_nonabstentions':20,
            'original_matched_source_journal_claims':96,
            'greedy_prefix_claims':16,
            'original_response_citation_tagged':27,
            'citation_entailment_independently_judged':False,
            'empty_evidence_guard_recommended':True,
            'original_model_calls_externally_attested':False,
            'automatic_cell_split_or_finaluse':False,
            'production_accepted':False}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('source',type=Path)
    x=p.parse_args()
    if not x.source.is_file() or x.source.is_symlink() or sha256(x.source.read_bytes()).hexdigest()!=REPORT_SHA:
        raise ValueError('published original aggregate changed after external pin')
    print(json.dumps(verify(json.loads(x.source.read_bytes())),sort_keys=True))

if __name__=='__main__':main()
