// Pure contract and negative tests for physical source-only A/C/D ranking.
import {sourceOnlyControls, independentEvidenceScore} from "./memory_source_graph_controls.mjs";
function exercise(sourceOnlyControls,independentEvidenceScore){
 const eq=(a,b)=>{if(JSON.stringify(a)!==JSON.stringify(b))throw Error("difference")};
 const fail=(f,label)=>{let threw=false;try{f()}catch(e){threw=true}if(!threw)throw Error("expected rejection: "+label)};
 const names=["conv-30","conv-41","conv-26","conv-44","conv-47","conv-42","conv-48","conv-43","conv-49","conv-50"];
 const original=names.map(g=>({sample_id:g,conversation:{
  speaker_a:"Ada",speaker_b:"Ben",session_1_date_time:"3 May 2023",
  session_1:[{dia_id:"D1:1",speaker:"Ada",text:"I planted oak trees near the library yesterday."},
             {dia_id:"D1:2",speaker:"Ben",text:"The oak trees were planted on Tuesday."}],
  session_2_date_time:"4 May 2023",
  session_2:[{dia_id:"D2:1",speaker:"Ben",text:"Use blue chalk to paint the tree."}]},
  qa:[{question:"When did Ada plant the oak trees?",category:2,answer:"Tuesday",evidence:["D1:1","D1:2"]},
      {question:"Which rocket did Ada launch?",category:5,answer:"not mentioned",evidence:[]}]
 }));
 const split={evaluation:["conv-47","conv-42","conv-48","conv-43","conv-49","conv-50"]};
 const predictions=sourceOnlyControls(original,split);
 if(predictions.predictions.length!==36||predictions.arms.join("")!=="ACD")throw Error("synthetic matched census");
 for(const arm of predictions.arms)if(!predictions.predictions.some(r=>r.arm===arm&&r.selected_source_ids.length))throw Error("missing executed arm");
 const report=independentEvidenceScore(original,predictions,split);
 if(report.results.A.planned_questions!==12||report.results.A.adversarial!==6||
    report.all_arms_A_to_I_complete!==false||report.whole_answer_scored!==false||
    report.authority!=="SHADOW_ONLY/DENY_ALL/HOLD_NO_GO")throw Error("falsified synthetic metrics");
 const changed=JSON.parse(JSON.stringify(original));changed[4].qa[0].answer="LEAK";
 changed[4].qa[0].category=5;changed[4].qa[0].evidence=["bogus"];
 eq(sourceOnlyControls(changed,split),predictions);
 const dup=JSON.parse(JSON.stringify(predictions));
 dup.predictions[0].query_id=dup.predictions[3].query_id;
 fail(()=>independentEvidenceScore(original,dup,split),"duplicate query");
 const missing=JSON.parse(JSON.stringify(predictions));
 missing.predictions.pop();
 fail(()=>independentEvidenceScore(original,missing,split),"missing query");
 const context=JSON.parse(JSON.stringify(predictions));
 context.predictions[0].context_bytes+=17;
 fail(()=>independentEvidenceScore(original,context,split),"context ledger");
 const forged=JSON.parse(JSON.stringify(predictions));
 forged.predictions[0].selected_source_ids=["D999:1"];
 fail(()=>independentEvidenceScore(original,forged,split),"foreign source");
 const bad=JSON.parse(JSON.stringify(original));
 bad[0].conversation.session_1.push({...bad[0].conversation.session_1[0]});
 fail(()=>sourceOnlyControls(bad,split),"duplicate source");
 const long=JSON.parse(JSON.stringify(original));
 long[4].conversation.session_1[0].text="长".repeat(1700);
 const bounded=sourceOnlyControls(long,split);
 if(bounded.predictions.some(x=>x.context_bytes>4096||x.selected_source_ids.length>8))throw Error("context bound exceeded");
 return {tests:9,source_groups:10,fixture_predictions:predictions.predictions.length,authority:report.authority};
}
const result=exercise(sourceOnlyControls,independentEvidenceScore);
console.log(JSON.stringify(result));
