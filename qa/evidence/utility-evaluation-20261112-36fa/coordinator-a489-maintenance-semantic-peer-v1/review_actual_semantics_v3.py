"""Second pure audit: exact fix splices and scoped formatter-token changes.
No project imports, original gates, Rust execution, source/ref writes, or H.
"""
import collections
import difflib
import json
from pathlib import Path
from lexical_primitives import ident, lex, changed_sequences
from item_primitives import groups, inventories
HERE = Path(__file__).resolve().parent
SRC = HERE / "source-images"
PREFIX = "codex-rs/hepta-agentd/src/"
FIXES = []

def add(name, category, before, after):
    FIXES.append({"path":PREFIX+name,"category":category,"before":before,"after":after})

add("cell_q24_training_shared_readback_support_tests.rs","same_standard_method_reference",
    ".unwrap_or_else(|error| error.into_inner());",
    ".unwrap_or_else(std::sync::PoisonError::into_inner);")
add("circuit_evaluated_same_host_sc_connections_tests.rs","identity_anyhow_error_conversion_removed",
    "return Err(anyhow::Error::from(error)\n                        .context(format!(\"original T channel cleanup: {cleanup:?}\")));",
    "return Err(error\n                        .context(format!(\"original T channel cleanup: {cleanup:?}\")));")
add("circuit_evaluated_same_host_sc_support_tests.rs","short_circuit_let_chain_cleanup",
    "if let Some(mut task) = self.task.take() {\n            if let Err(error) = task.stop().await {\n                errors.push(error.to_string());\n            }\n        }",
    "if let Some(mut task) = self.task.take()\n            && let Err(error) = task.stop().await {\n                errors.push(error.to_string());\n            }")
add("circuit_evaluated_same_host_sc_support_tests.rs","short_circuit_let_chain_cleanup",
    "if let Some(fixture) = self.fixture.take() {\n            if let Err(error) = (*fixture).finish().await {\n                errors.push(error.to_string());\n            }\n        }",
    "if let Some(fixture) = self.fixture.take()\n            && let Err(error) = (*fixture).finish().await {\n                errors.push(error.to_string());\n            }")
add("circuit_evaluated_version_local_readback_tests.rs","short_circuit_let_chain_join_cleanup",
    """if let Some(task) = task.take() {
        if !consumed_join {
            task.abort();
            match task.await {
                Ok(_) => {}
                Err(error) if error.is_cancelled() => {}
                Err(error) => cleanup_error = Some(anyhow::anyhow!("local read join: {error}")),
            }
        }
    }""",
    """if let Some(task) = task.take()
        && !consumed_join {
            task.abort();
            match task.await {
                Ok(_) => {}
                Err(error) if error.is_cancelled() => {}
                Err(error) => cleanup_error = Some(anyhow::anyhow!("local read join: {error}")),
            }
        }""")
for name in ("circuit_evaluated_version_next_use_readback_tests.rs","circuit_evaluated_version_shared_export_tests.rs"):
    add(name,"short_circuit_let_chain_cleanup",
        "if let Some(fixture) = self.fixture.take() {\n            if let Err(error) = (*fixture).finish().await {\n                failures.push(error.to_string());\n            }\n        }",
        "if let Some(fixture) = self.fixture.take()\n            && let Err(error) = (*fixture).finish().await {\n                failures.push(error.to_string());\n            }")
add("circuit_evaluated_version_next_use_readback_tests.rs","boolean_assertion_equivalence",
    "observed.load(Ordering::Acquire) == !already_expired",
    "observed.load(Ordering::Acquire) != already_expired")
for name in ("trainer","evaluator"):
    add("circuit_evaluated_version_shared_readback_tests.rs","same_standard_method_reference",
        f"self.{name}_peer.take().map(|thread| thread.join())",
        f"self.{name}_peer.take().map(std::thread::JoinHandle::join)")
add("circuit_learning_local_read.rs","cfg_test_only_short_circuit_pause",
    "if response.is_ok() {\n                if let Some(terminal) = &terminal {\n                    terminal.pause_after_original_response(deadline)?;\n                }\n            }",
    "if response.is_ok()\n                && let Some(terminal) = &terminal {\n                    terminal.pause_after_original_response(deadline)?;\n                }")
for name,var in (("circuit_resident_candidate_first_material_tests.rs","added"),
                 ("circuit_resident_candidate_provider_material_control_tests.rs","changed_payload")):
    add(name,"last_use_owned_json_move",f"let mut {var} = base.clone();",f"let mut {var} = base;")
    add(name,"last_use_owned_byte_vector_move","let mut trailing = raw.clone();","let mut trailing = raw;")
add("circuit_resident_candidate_provider_publication_support_tests.rs","short_circuit_let_chain_cleanup",
    "if let Some(stages) = self.stages.take() {\n            if let Err(error) = stages.finish().await {\n                errors.push(error.to_string());\n            }\n        }",
    "if let Some(stages) = self.stages.take()\n            && let Err(error) = stages.finish().await {\n                errors.push(error.to_string());\n            }")
for noun,expr in (("panel","panel.finish()"),("peers","peers.finish_shared()"),("original","(*original).finish().await")):
    field={"panel":"panel","peers":"training_peers","original":"original"}[noun]
    add("circuit_resident_candidate_provider_stage_support_tests.rs","short_circuit_let_chain_cleanup",
        f"if let Some({noun}) = self.{field}.take() {{\n            if let Err(error) = {expr} {{\n                errors.push(error.to_string());\n            }}\n        }}",
        f"if let Some({noun}) = self.{field}.take()\n            && let Err(error) = {expr} {{\n                errors.push(error.to_string());\n            }}")

def image(stage,side,path):
    return (SRC/stage/side/path).read_text()

def macro_items(text):
    tok,_=lex(text); pairs,_=groups(tok); found=[]
    for i,t in enumerate(tok):
        if t[1]!="!" or i==0 or tok[i-1][0]!="identifier" or tok[i-1][1] in {"if","while","return","match","let","else","yield"}: continue
        if i+1>=len(tok) or tok[i+1][1] not in ("(","[","{"): continue
        start=i-1
        while start>=2 and tok[start-1][1]=="::" and tok[start-2][0]=="identifier":
            start-=2
        end=pairs[i+1]
        found.append({"name":"".join(x[1] for x in tok[start:i]),"tokens":[x[:2] for x in tok[i+1:end+1]]})
    return found

def declared_functions(text):
    tok,_=lex(text);pairs,depth=groups(tok);found=[]
    for i,t in enumerate(tok):
        if t[0]!="identifier" or t[1]!="fn" or i+1>=len(tok) or tok[i+1][0]!="identifier":continue
        end=i+2
        while end<len(tok):
            if depth[end]==depth[i] and tok[end][1] in ("{",";"):break
            end+=1
        assert end<len(tok),(tok[i+1],end)
        found.append({"name":tok[i+1][1],"header":[x[:2] for x in tok[i:end]],
                      "has_body":tok[end][1]=="{"})
    return found

def main():
    base_report=json.loads((HERE/"ACTUAL_TRANSITION_BYTE_AND_TOKEN_REVIEW.json").read_bytes())
    paths=[x["path"] for x in base_report["lexical_review"] if x["stage"]=="fix.after"]
    fix_proof=[]
    assert len(FIXES)==19
    for path in paths:
        old=image("fix.after","before",path); new=image("fix.after","after",path)
        transformed=old
        pairs=[x for x in FIXES if x["path"]==path]
        assert pairs
        for p in pairs:
            assert transformed.count(p["before"])==1,(path,p["category"],"old occurrence")
            transformed=transformed.replace(p["before"],p["after"],1)
        assert transformed==new,("unaccounted fix bytes",path)
        reversed_text=new
        for p in reversed(pairs):
            assert reversed_text.count(p["after"])==1,(path,p["category"],"new occurrence")
            reversed_text=reversed_text.replace(p["after"],p["before"],1)
        assert reversed_text==old,("inverse differs",path)
        fix_proof.append({"path":path,"splice_count":len(pairs),"categories":[p["category"] for p in pairs],
                          "forward_and_inverse_complete_file_equal":True,
                          "before":ident(old.encode()),"after":ident(new.encode())})
    fmt_proof=[]; all_residuals=[]
    for row in base_report["lexical_review"]:
        if row["stage"]!="fmt.after":continue
        path=row["path"]; old=image("fmt.after","before",path);new=image("fmt.after","after",path)
        a,au,am,aur,amr,ac=inventories(old);b,bu,bm,bur,bmr,bc=inventories(new)
        assert collections.Counter(au)==collections.Counter(bu),("use inventory",path)
        assert collections.Counter(am)==collections.Counter(bm),("module inventory",path)
        assert [x[:2] for x in ac]==[x[:2] for x in bc]
        changes=changed_sequences(a,b)
        slim=[]
        for c in changes:
            ar,br=c["before_range"],c["after_range"]
            aa=a[ar[0]:ar[1]];bb=b[br[0]:br[1]]
            rec={"op":c["op"],"before":[x[1] for x in aa],"after":[x[1] for x in bb],
                 "before_context":" ".join(x[1] for x in a[max(0,ar[0]-24):min(len(a),ar[1]+24)]),
                 "after_context":" ".join(x[1] for x in b[max(0,br[0]-24):min(len(b),br[1]+24)])}
            if (rec["before"],rec["after"]) in [([],[","]),([","],[])]:
                rec["classification"]="comma_requires_context"
            else:
                rec["classification"]="other_requires_context"
            slim.append(rec);all_residuals.append({"path":path,**rec})
        macro_before=macro_items(old);macro_after=macro_items(new)
        assert macro_before==macro_after,("formatter macro-token change",path)
        fmt_proof.append({"path":path,"use_inventory_equal":True,"module_inventory_equal":True,
                          "comments_exact_equal":True,"literal_sequence_exact_equal":True,
                          "macro_invocation_count":len(macro_before),"all_macro_token_trees_exactly_equal":True,
                          "use_items_before":aur,"use_items_after":bur,
                          "full_tokens_equal":row["non_whitespace_token_sequences_equal"],
                          "remaining_token_changes":slim})
    final_proof=[]
    macro_diffs=[]
    for row in base_report["stage_lineage"]:
        path=row["path"];old=image("final","before",path);new=image("final","after",path)
        a=declared_functions(old);b=declared_functions(new)
        assert [(x["name"],x["has_body"]) for x in a]==[(x["name"],x["has_body"]) for x in b],("function inventory",path)
        header_changes=[{"name":x["name"],"before":x["header"],"after":y["header"]} for x,y in zip(a,b) if x!=y]
        attrs=[]
        for text in (old,new):
            tok,_=lex(text);pairs,_=groups(tok);items=[]
            for i,t in enumerate(tok):
                if t[1]=="#" and i+1<len(tok) and tok[i+1][1]=="[":
                    items.append([x[:2] for x in tok[i:pairs[i+1]+1]])
            attrs.append(items)
        assert attrs[0]==attrs[1],("attributes changed",path)
        am=macro_items(old);bm=macro_items(new)
        assert [x["name"] for x in am]==[x["name"] for x in bm],("macro inventory changed",path)
        changes=[]
        for i,(x,y) in enumerate(zip(am,bm)):
            if x!=y:
                changes.append({"ordinal":i,"name":x["name"],"before":x["tokens"],"after":y["tokens"]})
        if changes: macro_diffs.append({"path":path,"changes":changes})
        final_proof.append({"path":path,"function_count":len(a),"all_function_headers_exact_token_equal":a==b,"header_changes":header_changes,
                            "attributes_exact_token_equal":True,"attribute_count":len(attrs[0]),
                            "function_names":[x["name"] for x in a],
                            "macro_count":len(am),"macro_names_sequence_equal":True,
                            "changed_macros":len(changes)})
    assert len(macro_diffs)==1 and macro_diffs[0]["path"].endswith("circuit_evaluated_version_next_use_readback_tests.rs")
    assert len(macro_diffs[0]["changes"])==1 and macro_diffs[0]["changes"][0]["name"]=="anyhow::ensure"
    table=[{"observed":observed,"already_expired":expired,
            "before":observed==(not expired),"after":observed!=expired}
           for observed in (False,True) for expired in (False,True)]
    assert all(x["before"]==x["after"] for x in table)
    result={"format":"hepta-main41e-independent-scoped-semantic-byte-proof-v1",
            "limits":"Pure byte and lexical audit; not a Rust compiler, runtime test or qualification result.",
            "fix_exact_splices":fix_proof,"fix_splice_total":len(FIXES),
            "fix_categories":dict(collections.Counter(x["category"] for x in FIXES)),
            "fmt":fmt_proof,"final_function_and_macro_inventory":final_proof,
            "only_changed_assertion_macro":macro_diffs,"boolean_truth_table":table,
            "frozen_lexical_diagnostic":ident((HERE/"ACTUAL_TRANSITION_BYTE_AND_TOKEN_REVIEW.json").read_bytes()),
            "script":ident(Path(__file__).read_bytes()),"item_helpers":ident((HERE/"item_primitives.py").read_bytes())}
    raw=(json.dumps(result,sort_keys=True,indent=2)+"\n").encode()
    out=HERE/"SCOPED_SEMANTIC_BYTE_PROOF.v3.json"
    with out.open("xb") as f:f.write(raw)
    print(json.dumps({"proof":ident(raw),"fix_count":len(FIXES),"categories":result["fix_categories"],
                      "fmt_residuals_noncomma":[x for x in all_residuals if x["classification"]!="comma_requires_context"],
                      "fmt_comma_residual_count":sum(x["classification"]=="comma_requires_context" for x in all_residuals),
                      "methods":sum(x["function_count"] for x in final_proof),
                      "macro_invocations":sum(x["macro_count"] for x in final_proof),
                      "macro_differences":len(macro_diffs)},indent=2))
if __name__=="__main__":
    main()

