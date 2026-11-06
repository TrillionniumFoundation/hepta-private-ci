"""Static observations over actual snapshot bytes. No Rust/compiler/project imports."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path

from source_compare import (macro_oracles, pin, python_ast_readback, read_tar, require,
                            rust_tokens, top_level_declarations)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def attributes(tokens):
    rows=[]; i=0
    while i<len(tokens)-1:
        start=i
        if tokens[i]=="#":
            j=i+1
            if tokens[j]=="!":j+=1
            if j<len(tokens) and tokens[j]=="[":
                level=1;j+=1
                while j<len(tokens) and level:
                    if tokens[j]=="[":level+=1
                    elif tokens[j]=="]":level-=1
                    j+=1
                require(level==0,"attribute unbalanced")
                rows.append(tuple(tokens[start:j]));i=j;continue
        i+=1
    return rows


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();out=args.output
    root=Path.cwd()
    archives=root/'native-validation-results/source53-finalization-archives'
    def source(label):
        raw=(archives/label/(label+'.tar.gz')).read_bytes()
        contents,_=read_tar(raw)
        return {k[7:]:v for k,v in contents.items() if k.startswith('source/')},pin(raw)
    before,before_pin=source('tested-pre-fix-source');after,after_pin=source('final-post-format-source')
    lexical_path=Path(__file__).parent/'PATCH-LEXICAL-OBSERVATIONS.json'
    lexical_raw=lexical_path.read_bytes();lexical=json.loads(lexical_raw)
    listed={x['path']:x for x in lexical['files']}
    changed=sorted(p for p in before if before[p]!=after[p])
    require(set(changed)==set(listed),'actual source changes vs original lexical observations')
    results=[];comma_count=0;block_count=0;decl_deltas=0;declaration_paths=[];block_paths=[]
    for path in changed:
        previous=listed[path]
        require(pin(before[path])==previous['before'] and pin(after[path])==previous['after_derived_from_original_patch'],
                'actual final source differs from reviewed patch result')
        if path.endswith('.py'):
            result=python_ast_readback(before[path],after[path]);require(result['ast_equal'],'Python AST changed')
            results.append({'path':path,'language':'Python',**result});continue
        old,new=rust_tokens(before[path]),rust_tokens(after[path])
        old_decls,old_body=top_level_declarations(old);new_decls,new_body=top_level_declarations(new)
        require(collections.Counter(old_decls)==collections.Counter(new_decls),'declaration or attached attribute changed: '+path)
        decl_reordered=old_decls!=new_decls
        if decl_reordered:declaration_paths.append(path)
        require(collections.Counter(attributes(old))==collections.Counter(attributes(new)), 'cfg/test/ignore attribute changed: '+path)
        # This is a supporting lexical check, not an AST semantic equivalence claim.
        significant_old=[x for x in old_body if x not in (',',';','{','}')]
        significant_new=[x for x in new_body if x not in (',',';','{','}')]
        require(significant_old==significant_new,'ordered identifiers/literals/operators changed outside declarations: '+path)
        macros_old=macro_oracles(old);macros_new=macro_oracles(new)
        require(macros_old==macros_new,'assert/panic macro oracle tokens changed: '+path)
        comma,block,non_punctuation=0,0,0
        for delta in previous['review']['deltas']:
            tokens=delta['before']+delta['after']
            if set(tokens)<=set([',']):
                require(max(len(delta['before']),len(delta['after']))==1,'multiple comma change')
                require(delta['old_context_after'][0] in (')',']','}'),'comma not adjacent to closing delimiter')
                comma+=1
            elif set(tokens)<=set([',',';','{','}']):block+=1
            else:non_punctuation+=1
        require(non_punctuation==0 or decl_reordered,'nonpunctuation diff not isolated to declaration reorder')
        if block:block_paths.append(path)
        comma_count+=comma;block_count+=block;decl_deltas+=non_punctuation
        results.append({'path':path,'language':'Rust','exact_noncomment_token_equality':old==new,
                        'literal_identifier_operator_order_outside_declarations_preserved':True,
                        'all_top_level_declarations_and_attached_attributes_multiset_equal':True,
                        'declarations_reordered':decl_reordered,
                        'declaration_count':len(old_decls),'declaration_bundle_multiset_sha256':digest(sorted(old_decls)),
                        'all_attributes_multiset_equal':True,'attributes_count':len(attributes(old)),
                        'protected_macro_count':len(macros_old),'protected_macro_names':dict(collections.Counter(x['name'] for x in macros_old)),
                        'protected_macro_tokens_equal_modulo_commas':True,'protected_macro_digest':digest(macros_old),
                        'trailing_comma_only_deltas':comma,'block_or_semicolon_deltas_for_manual_review':block,
                        'declaration_reorder_lexical_deltas':non_punctuation})
    # Manual classifications are tied to the complete stored token deltas and exact original patch.
    manual={
      'codex-rs/core/tests/suite/multi_agent_resume.rs':'Adds a tail-expression block around the same with_context closure format! expression; no new statement or return change.',
      'codex-rs/hepta-agentd/src/authority_host_checkpoint_material_worker.rs':'Removes a single tail-expression block from the Verify match arm and uses its required arm comma; the identical await/map chain is retained.',
      'codex-rs/hepta-agentd/src/circuit_cell.rs':'Wraps the identical return finish(...) match arm in a block; the added semicolon follows return and does not discard a former tail value.',
      'codex-rs/hepta-agentd/src/deployment_text.rs':'Wraps the identical return Err(...) match arm in a block; added semicolon follows return, retaining the same error branch.',
      'codex-rs/hepta-agentd/src/intelligence_product_runner.rs':'Wraps the same Err(...) tail expression in a match-arm block; no terminating semicolon is introduced on its value.',
      'codex-rs/hepta-agentd/src/learning_iteration_runtime_tests.rs':'Adds tail-expression blocks to two map_or closures and Experience/Evaluation construction arms; the downstream error arm keeps the same return Err(...) with a semicolon inside its new block.'
    }
    require(set(block_paths)==set(manual),'unexpected manual block scope')
    expected_declarations={
      'codex-rs/hepta-agentd/src/lib.rs','codex-rs/hepta-automation/src/circuit_store_tests.rs',
      'codex-rs/hepta-automation/src/lib.rs','codex-rs/hepta-infer-worker-host/src/native_app_server.rs',
      'codex-rs/hepta-intelligence/src/plasticity_product_tests.rs',
      'codex-rs/hepta-learning-artifacts/src/learning_iteration_test_support.rs',
      'codex-rs/hepta-neuron/src/cell_inference_tests.rs','codex-rs/hepta-neuron/src/cell_journal_tests.rs',
      'codex-rs/hepta-neuron/src/lib.rs'}
    require(set(declaration_paths)==expected_declarations,'unexpected module/import reorder scope')
    report={'schema':'hepta.source53-finalization-independent-static-difference-review.v1',
      'status':'STATIC_READBACK_NO_ASSERTION_BUDGET_RETRY_FILTER_WEAKENING_FOUND',
      'actual_tested_archive':before_pin,'actual_final_archive':after_pin,
      'original_patch_derived_lexical_observations':{'path':str(lexical_path),**pin(lexical_raw)},
      'actual_final_snapshot_bytes_now_match_all_prior_lexical_inputs':True,
      'changed_files':len(changed),'rust_files':sum(p.endswith('.rs') for p in changed),'python_files':sum(p.endswith('.py') for p in changed),
      'unchanged_source_files':len(before)-len(changed),
      'exact_Rust_noncomment_token_files':sum(x.get('exact_noncomment_token_equality') is True for x in results),
      'python_AST_equal_files':sum(x.get('ast_equal') is True for x in results),
      'Rust_lexical_changes':{'trailing_comma_adjacent_to_closing_delimiter':comma_count,
                            'brace_semicolon_deltas':block_count,'declaration_reorder_deltas':decl_deltas},
      'top_level_module_use_bundles_attributes_preserved':declaration_paths,
      'manual_block_tail_and_return_review':manual,
      'protected_macro_count_in_changed_Rust':sum(x.get('protected_macro_count',0) for x in results),
      'files':results,
      'limits':['Rust analysis is a custom lexical scan plus complete changed-token/context review, not a Rust AST/compiler proof.',
                'Comma normalization is limited supporting evidence; all 279 comma edits were independently identified as adjacent to closing delimiters in the original patch.',
                'The 20 brace/semicolon edits were manually reviewed in six files as unchanged tail expressions or explicit returns.',
                'Import/module reorder keeps exact declarations plus attached attributes; no assertion/expression/literal changes are attributed to that reorder.',
                'Python comparison parses ASTs only and does not import or run either script.',
                'No Rust, metadata, test, fix or format command was rerun. R31 test qualification remains on the tested tree; the final formatted tree is not claimed tested.'],
      'post_fix_or_format_tests_executed':False,'qualification_transferred_to_mutated_tree':False,
      'science':'HOLD','diagnostic_only':True,'behavior_repair_claimed':False}
    raw=(json.dumps(report,indent=2,ensure_ascii=False)+'\n').encode()
    with out.open('xb') as f:f.write(raw)
    print(json.dumps({'path':str(out),**pin(raw),'rust_files':report['rust_files'],'python_AST_equal':report['python_AST_equal_files'],
                      'protected_macros':report['protected_macro_count_in_changed_Rust'],'classifications':report['Rust_lexical_changes']}))


if __name__=='__main__':main()
