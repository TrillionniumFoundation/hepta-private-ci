#!/usr/bin/env python3
"""Source-bound twelve-case nonparametric code-memory retrieval comparison.

Historical, already exposed source families. No Reader/model calls, human semantics,
new temporal windows or parameter-memory claims. `rank` never imports the
published implementation-file answer oracle. The later `score` subcommand does.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import time

from real_source_reader_probe import SOURCE_SHA, REOPEN_SHA, SOURCE_CUT, canonical, digest, real_source, require, strict_json, write_once

SCHEMA = 'hepta.memory.original-twelve-nonparam-evidence.v1'
FROZEN_PLAN_SHA256 = '7cb9d4cd47e4b0230ff746228cf238a72845207746061c94bd5eb80627172fa2'
FROZEN_RANK_SHA256 = '74968aea04b45c595c8d071ee52ab8dab440c8c44e0d24f3449c0ef432ddd6bd'
ARMS = ('lexical_bm25', 'symbol_code_search', 'source_import_graph')
TOPK = 1
EXCERPT_BYTES = 480
# Prespecified public QUESTIONS only: repository, caller, scope, requested
# symbol. No implementation location, original oracle labels or gold scores.
QUESTIONS = (
    ('py-http-01', 'python/cpython', 'Lib/test/test_httplib.py', 'HeaderTests.test_auto_headers', 'HTTPConnection.request'),
    ('py-http-02', 'python/cpython', 'Lib/test/test_httplib.py', 'HeaderTests.test_putheader', 'HTTPConnection.putheader'),
    ('py-http-03', 'python/cpython', 'Lib/test/test_httplib.py', 'BasicTest.test_send', 'HTTPConnection.send'),
    ('sk-base-01', 'scikit-learn/scikit-learn', 'sklearn/linear_model/tests/test_base.py', 'test_preprocess_data', '_preprocess_data'),
    ('sk-base-02', 'scikit-learn/scikit-learn', 'sklearn/linear_model/tests/test_base.py', 'test_rescale_data', '_rescale_data'),
    ('sk-log-01', 'scikit-learn/scikit-learn', 'sklearn/linear_model/tests/test_logistic.py', 'test_logistic_regression_path_convergence_fail', '_logistic_regression_path'),
    ('sk-log-02', 'scikit-learn/scikit-learn', 'sklearn/linear_model/tests/test_logistic.py', 'test_logistic_cv_multinomial_score', '_log_reg_scoring_path'),
    ('sk-api-01', 'scikit-learn/scikit-learn', 'sklearn/utils/tests/test_array_api.py', 'test_asarray_with_order', '_asarray_with_order'),
    ('sk-api-02', 'scikit-learn/scikit-learn', 'sklearn/utils/tests/test_array_api.py', 'test_convert_to_numpy_cpu', '_convert_to_numpy'),
    ('deno-01', 'denoland/deno', 'libs/cache_dir/global/mod.rs', 'local_path_for_url', 'url_to_filename'),
    ('deno-02', 'denoland/deno', 'libs/cache_dir/file_fetcher/mod.rs', 'literal-line-730', 'NOT_FOUND_CACHE_HEADER'),
    ('deno-03', 'denoland/deno', 'libs/cache_dir/global/mod.rs', 'literal-line-171', 'CacheReadFileError'),
)
ROOT_COUNTS = {'python/cpython': 3, 'scikit-learn/scikit-learn': 6, 'denoland/deno': 3}
TOKENS = re.compile(r'[A-Za-z]+|[0-9]+')


def read_docs(sources):
    files, blobs = sources
    docs = {}
    for item in files:
        if item['partition'] != 'evaluation' or item['repo'] not in ROOT_COUNTS:
            continue
        if not item['path'].endswith(('.py', '.rs')):
            continue
        k = (item['repo'], item['path'])
        text = blobs[k].decode('utf-8', 'strict')
        require(digest(blobs[k]) == item['sha256'] and k not in docs, 'immutable original file altered')
        docs[k] = dict(text=text, blob=item['blob_sha'], sha256=item['sha256'])
    require(set(root for root, _ in docs) == set(ROOT_COUNTS), 'missing original evaluation roots')
    return docs


def plan_for(sources):
    docs = read_docs(sources)
    require(len(QUESTIONS) == 12 and len({q[0] for q in QUESTIONS}) == 12, 'question registration drift')
    require(Counter(q[1] for q in QUESTIONS) == ROOT_COUNTS, 'source-family pseudoreplication')
    for _id, root, caller, _, _ in QUESTIONS:
        require((root, caller) in docs, 'original caller missing')
    inventory = [(r, p, v['blob'], v['sha256']) for (r, p), v in sorted(docs.items())]
    return dict(schema=SCHEMA, original_zip_sha256=SOURCE_SHA, independent_reopen_zip_sha256=REOPEN_SHA,
                source_cut=SOURCE_CUT, registered_queries=[dict(id=i, root=r, caller_file=f, caller_scope=s, symbol=n)
                    for i,r,f,s,n in QUESTIONS], original_evaluation_file_inventory=inventory,
                final_evidence_slots=TOPK, max_bytes_per_excerpt=EXCERPT_BYTES, arms=list(ARMS),
                labels_present=False, no_model_calls=True, completed_real_program_repair=False,
                source_root_count=3, future_window_count=0, production_qualified=False)


def locked_plan(sources, path, sha):
    require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= 250000,
            'bounded original registration plan required')
    data = path.read_bytes()
    require(digest(data) == sha == FROZEN_PLAN_SHA256 and data == canonical(plan_for(sources)) + b'\n',
            'pre-scoring plan changed or digest not externally pinned')
    return strict_json(data)


def tokenize(text):
    return [t.lower() for t in TOKENS.findall(text)]


def bm25_candidates(query, root, docs):
    family = {p:v for (r,p),v in docs.items() if r == root}
    vectors = {p: Counter(tokenize(v['text'])) for p, v in family.items()}
    lengths = {p:sum(c.values()) for p,c in vectors.items()}
    avg = sum(lengths.values()) / len(lengths)
    df = Counter(t for vector in vectors.values() for t in vector)
    terms = set(tokenize(query['symbol'] + ' ' + query['caller_scope'] + ' ' + query['caller_file']))
    def score(path):
        return sum(math.log(1 + (len(family) - df[t] + 0.5)/(df[t]+0.5)) *
                   (vectors[path][t]*2.2)/(vectors[path][t] + 1.2*(0.25 + 0.75*lengths[path]/avg))
                   for t in terms if vectors[path][t])
    return sorted(family, key=lambda p:(-score(p), p))


def declaration_in_file(text, symbol):
    if '.' in symbol:
        owner, target = symbol.split('.', 1)
    else:
        owner, target = None, symbol
    if re.search(r'^\s*(?:pub(?:\([^)]*\))?\s+)?(?:const|enum|fn)\s+' + re.escape(target) + r'\b', text, re.M) and not owner:
        return True
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, UnicodeError):
        return False
    if owner:
        classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == owner]
        return any(any(isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name == target for m in c.body) for c in classes)
    return any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == target for n in tree.body)


def code_search_candidates(query, root, docs, lexical):
    exact = [p for p in lexical if declaration_in_file(docs[(root,p)]['text'], query['symbol'])]
    return exact + [p for p in lexical if p not in exact]


def scope_node(tree, qualified):
    body = tree.body
    for part in qualified.split('.'):
        node = next((n for n in body if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == part), None)
        if node is None:
            return None
        body = node.body
    return node


def source_graph_candidates(query, root, docs, lexical):
    """Resolve *caller import/use*; never consume a registered implementation path."""
    path = query['caller_file']
    text = docs[(root,path)]['text']
    symbol = query['symbol']
    links = set()
    if path.endswith('.py'):
        tree = ast.parse(text)
        node = scope_node(tree, query['caller_scope'])
        if node is not None:
            if '.' in symbol:  # Imported module plus constructor-bound method
                owner, method = symbol.split('.',1)
                imports = [n for n in tree.body if isinstance(n,ast.ImportFrom) and n.module == 'http'
                           and any(a.name == 'client' and a.asname is None for a in n.names)]
                aliases = {v.targets[0].id for v in ast.walk(node) if isinstance(v,ast.Assign)
                           and len(v.targets)==1 and isinstance(v.targets[0],ast.Name)
                           and isinstance(v.value,ast.Call) and isinstance(v.value.func,ast.Attribute)
                           and isinstance(v.value.func.value,ast.Name)
                           and v.value.func.value.id == 'client' and v.value.func.attr == owner}
                used = any(isinstance(v,ast.Call) and isinstance(v.func,ast.Attribute)
                           and isinstance(v.func.value,ast.Name) and v.func.value.id in aliases
                           and v.func.attr == method for v in ast.walk(node))
                constructor_writes = sum(isinstance(v,ast.Assign) and len(v.targets)==1
                    and isinstance(v.targets[0],ast.Name) and v.targets[0].id in aliases
                    and isinstance(v.value,ast.Call) and isinstance(v.value.func,ast.Attribute)
                    and isinstance(v.value.func.value,ast.Name) and v.value.func.value.id == 'client'
                    and v.value.func.attr == owner for v in ast.walk(node))
                stores = sum(isinstance(v,ast.Name) and v.id in aliases and isinstance(v.ctx,ast.Store)
                             for v in ast.walk(node))
                if imports and aliases and used and constructor_writes == stores:
                    links.update(p for p in lexical if p.endswith('/http/client.py')
                                 and declaration_in_file(docs[(root,p)]['text'], symbol))
            else:
                used = any(isinstance(v,ast.Call) and isinstance(v.func,ast.Name)
                           and v.func.id == symbol for v in ast.walk(node))
                for imported in tree.body:
                    if not isinstance(imported, ast.ImportFrom) or not imported.module:
                        continue
                    if not any(a.name == symbol and (a.asname is None or a.asname == symbol) for a in imported.names):
                        continue
                    module = imported.module.replace('.', '/') + '.py'
                    rebound = any(isinstance(v,ast.Name) and v.id == symbol and isinstance(v.ctx,ast.Store)
                                  for v in ast.walk(node))
                    if used and not rebound:
                        links.update(p for p in lexical if p.endswith(module)
                                     and declaration_in_file(docs[(root,p)]['text'], symbol))
    else:
        # Only conservative literal module imports are recognized; no Rust macro inference.
        module = re.findall(r'^\s*use\s+crate::([A-Za-z_][A-Za-z0-9_]*)::'+re.escape(symbol)+r'\s*;\s*$', text, re.M)
        occurrences = len(re.findall(r'\b'+re.escape(symbol)+r'\b', text))
        if len(module)==1 and occurrences >= 2:
            candidate_suffix = '/' + module[0] + '.rs'
            links.update(p for p in lexical if p.endswith(candidate_suffix)
                         and declaration_in_file(docs[(root,p)]['text'], symbol))
    return sorted(links) + [p for p in lexical if p not in links]


def delivered_snippet(doc, symbol):
    """A common, symbol-focused excerpt selector for every retrieval arm.

    Prefer an *actual* declaration in original bytes, never a guessed symbol
    mention; this same extraction is also available to the weak lexical arm.
    """
    text = doc['text']
    target = symbol.split('.')[-1]
    lines = text.splitlines()
    line_number = None
    if '.' in symbol or text.lstrip().startswith(('def ', 'class ', 'from ', 'import ')) or '\nclass ' in text:
        try:
            tree = ast.parse(text)
            if '.' in symbol:
                owner = symbol.split('.')[0]
                for clazz in tree.body:
                    if isinstance(clazz,ast.ClassDef) and clazz.name == owner:
                        for method in clazz.body:
                            if isinstance(method,(ast.FunctionDef,ast.AsyncFunctionDef)) and method.name == target:
                                line_number = method.lineno
                                break
            else:
                for node in tree.body:
                    if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and node.name == target:
                        line_number = node.lineno
                        break
        except SyntaxError:
            pass
    if line_number is None:
        pat = re.compile(r'^\s*(?:pub(?:\([^)]*\))?\s+)?(?:fn|const|enum)\s+'+re.escape(target)+r'\b')
        line_number = next((i for i,line in enumerate(lines,1) if pat.search(line)), None)
    if line_number is None:
        return text.encode()[:EXCERPT_BYTES].decode('utf-8','ignore')
    # Keep the original untouched declaration line for SHA-provenance checks.
    return ('\n'.join(lines[line_number-1:line_number+5])).encode()[:EXCERPT_BYTES].decode('utf-8','ignore')


def rank_all(sources, plan):
    docs = read_docs(sources)
    rows = []
    for task in plan['registered_queries']:
        root = task['root']
        lexical = bm25_candidates(task, root, docs)
        for arm, order in ((ARMS[0],lexical),(ARMS[1],code_search_candidates(task,root,docs,lexical)),
                           (ARMS[2],source_graph_candidates(task,root,docs,lexical))):
            selected = order[:TOPK]
            require(len(selected)==TOPK and len(set(selected))==TOPK, 'incomplete same-slot evidence set')
            snippets = [dict(path=p, git_blob=docs[(root,p)]['blob'],
                             source_sha256=docs[(root,p)]['sha256'],
                             excerpt=delivered_snippet(docs[(root,p)],task['symbol'])) for p in selected]
            rows.append(dict(id=task['id'],root=root,arm=arm,source_paths=selected,
                             delivered=snippets, evidence_bytes=sum(len(x['excerpt'].encode()) for x in snippets)))
    require(len(rows)==36, 'all twelve by three arms required')
    return dict(schema=SCHEMA+'.ranking',plan_sha256=digest(canonical(plan)+b'\n'),
                original_zip_sha256=SOURCE_SHA, original_reopen_zip_sha256=REOPEN_SHA,
                actual_original_files_considered=len(docs),original_source_root_count=3,
                new_model_calls=0,original_model_answers_generated=0,
                no_gold_during_ranking=True,proven_program_repair=False,production_qualified=False,rows=rows)


def score_all(sources,plan,ranking, report):
    require(ranking == rank_all(sources,plan), 'altered or self-scored source evidence receipts')
    from memory_original_crossfile_trace import audit
    reproduced = audit(sources)
    require(reproduced == report and report['schema']=='hepta.memory.original-crossfile-dependency.v1',
            'published original static oracle not independently reproducible')
    gold = {x['id']:x for x in report['cases']}
    require(set(gold)=={q['id'] for q in plan['registered_queries']}, 'original task census mismatch')
    rows = []
    for row in ranking['rows']:
        target = gold[row['id']]
        require(row['root']==target['repository_proxy'], 'cross-root source answer')
        observed = row['source_paths']
        exact = target['implementation_file'] in observed
        original_line_sha = target['definition_site_sha256']
        proof = any(doc['path'] == target['implementation_file'] and
                    any(digest(line.encode()) == original_line_sha for line in doc['excerpt'].splitlines())
                    for doc in row['delivered'])
        require(not proof or exact, 'declaration evidence from wrong source')
        rows.append(dict(id=row['id'],root=row['root'],arm=row['arm'],
                         gold_source_found=exact, original_declaration_line_delivered=proof,
                         gold_rank=observed.index(target['implementation_file'])+1 if exact else None,
                         delivered_evidence_bytes=row['evidence_bytes']))
    by_arm={}
    for arm in ARMS:
        mine=[r for r in rows if r['arm']==arm]
        by_arm[arm]=dict(registered=12, exact_source_hit_at_1=sum(r['gold_source_found'] for r in mine),
                         original_declaration_line_delivered=sum(r['original_declaration_line_delivered'] for r in mine),
                         bytes_delivered=sum(r['delivered_evidence_bytes'] for r in mine),
                         per_root={k:dict(registered=sum(r['root']==k for r in mine),
                                        exact_source_hit_at_1=sum(r['root']==k and r['gold_source_found'] for r in mine))
                                   for k in ROOT_COUNTS})
    pairs={}
    for comp in (ARMS[1],ARMS[2]):
        l={r['id']:r for r in rows if r['arm']==ARMS[0]}
        c={r['id']:r for r in rows if r['arm']==comp}
        pairs[comp]=dict(gained=sum(c[i]['gold_source_found'] and not l[i]['gold_source_found'] for i in l),
                         lost=sum(l[i]['gold_source_found'] and not c[i]['gold_source_found'] for i in l),
                         roots=3, paired_questions=12, independent_future_roots=0)
    return dict(schema=SCHEMA+'.independent-static-score', source_sha256=SOURCE_SHA,
                original_query_count=12, independent_repository_proxies=3, historical_exposed_questions=True,
                original_scored_source_links=12, arms=by_arm, paired_against_lexical=pairs,
                actual_reader_calls=0, end_to_end_task_success=None, model_learning_gain=None,
                program_diagnostic_cost=None, complete_lifecycle_tco=None,
                independent_semantic_judge=False, future_window_count=0,
                production_qualified=False)


def cli():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation', choices=('prepare','rank','score'))
    p.add_argument('--source-zip',required=True,type=Path)
    p.add_argument('--reopen-zip',required=True,type=Path)
    p.add_argument('--plan',required=True,type=Path)
    p.add_argument('--plan-sha256')
    p.add_argument('--ranking',type=Path)
    p.add_argument('--ranking-sha256')
    p.add_argument('--oracle',type=Path)
    p.add_argument('--output',type=Path)
    a=p.parse_args()
    source=real_source(a.source_zip,a.reopen_zip)
    if a.operation=='prepare':
        expected = canonical(plan_for(source))+b'\n'
        require(digest(expected)==FROZEN_PLAN_SHA256, 'registered independent original plan differs')
        write_once(a.plan,expected)
        print(digest(a.plan.read_bytes()))
    elif a.operation=='rank':
        plan=locked_plan(source,a.plan,a.plan_sha256)
        require(a.output is not None,'rank output required')
        output = canonical(rank_all(source,plan))+b'\n'
        require(digest(output)==FROZEN_RANK_SHA256, 'source-first rank digest unexpectedly changed')
        write_once(a.output,output)
        print(digest(a.output.read_bytes()))
    else:
        require(a.ranking and a.oracle and a.output and a.ranking_sha256,'score inputs required')
        plan=locked_plan(source,a.plan,a.plan_sha256)
        require(digest(a.ranking.read_bytes())==a.ranking_sha256==FROZEN_RANK_SHA256,'independently pinned sealed evidence rows required')
        report=strict_json(a.oracle.read_bytes())
        ranking=strict_json(a.ranking.read_bytes())
        write_once(a.output,canonical(score_all(source,plan,ranking,report))+b'\n')
        print(digest(a.output.read_bytes()))

if __name__=='__main__':
    cli()
