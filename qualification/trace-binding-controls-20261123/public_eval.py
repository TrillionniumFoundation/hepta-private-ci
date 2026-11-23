"""Separate source annotation, isolated inference and regrading of an external prompt."""
import argparse
import hashlib
import json
from pathlib import Path

from cell import ARMS, dump_new, file_sha, read


def prepare(source, labels, model, out):
    out.mkdir(exist_ok=False)
    rows=read(source/"private.json")
    reasons=dict(line.split(" ",1) for line in labels.read_text().splitlines())
    assert set(rows)==set(reasons) and len(rows)==60
    audit=[{"id":k,"url":r["url"],"body_sha256":r["body_sha256"],"scope":reasons[k]} for k,r in rows.items()]
    record=rows["18205390"]
    # The contiguous passage contains two mentions of the factor, and requires
    # a named sink. Preserve the verbatim prose input. Only its hash is published.
    query=record["paragraphs"][0]
    prompts=[{"id":"18205390","query":query}]
    dump_new(out/"prompts.json",prompts)
    dump_new(out/"selection.json",dict(eligibility=audit,question=record["url"],original_author=record["owner"],
             source_license=record["license"],passage_index=0,
             passage_sha256=hashlib.sha256(query.encode()).hexdigest(),numerical=[99,99,999999999],
             required_file="Blank.txt",stdout_only_matches=0))
    dump_new(out/"commitment.json",dict(model=file_sha(model),prompts=file_sha(out/"prompts.json"),
             selection=file_sha(out/"selection.json")))


def summarize(source, out):
    commitment=read(source/"commitment.json")
    selection=read(source/"selection.json")
    assert file_sha(source/"selection.json")==commitment["selection"]
    factor,low,high=selection["numerical"]
    expected_count=high//factor - (low-1)//factor
    # Each supported emitted script is a single range/filter with at most 300
    # distinct outputs. A positive result would require full independent validation.
    results={}
    for a in ARMS:
        r=read(source/(a+".json"))
        assert r["prompts"]==commitment["prompts"] and r["model"]==commitment["model"]
        assert r["net_before"]==r["net_after"]=={"lo":[0,0]}
        acts=r["predictions"]["18205390"]
        from ast import parse, Call, Name, Constant, walk
        count=0
        if acts:
            assert len(acts)==4
            loops=[n for n in walk(parse(acts[1])) if isinstance(n,Call) and isinstance(n.func,Name) and n.func.id=="range"]
            loop,=loops
            assert all(isinstance(v,Constant) and type(v.value) is int and 0<=v.value<=300 for v in loop.args)
            count=len(range(*(v.value for v in loop.args)))
        assert count < expected_count
        results[a]={"abstained":not acts,"actions":acts,"max_possible_outputs":count,
                    "numeric_pass":False,"named_file_delivered":False}
    dump_new(out,dict(source_questions=60,eligible_numerical=1,eligible_stdout_only=0,
                      expected_items=expected_count,arms=results))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("mode",choices=("prepare","score"))
    parser.add_argument("paths",nargs="+",type=Path)
    a=parser.parse_args()
    (prepare if a.mode=="prepare" else summarize)(*a.paths)
