// Research-only A/C/D source evidence probe. Gold never reaches retrieval.
// Only source text, timestamps and speakers enter ranking; labels are scorer-only.
// No Reader, dense Encoder, trained Head or qualified claim is produced.
import fs from "node:fs";
import crypto from "node:crypto";
import {pathToFileURL} from "node:url";

export function sourceOnlyControls(raw, partitions) {
  const N = 8, MAX_BYTES = 4096, MAX_SEEDS = 24;
  const STOP = new Set("a an and are as at be been but by can could did do does for from had has have how i if in is it its me my of on or our she should that the their them there they this to was were what when where which who why will with would you your".split(" "));
  const terms = s => (String(s).normalize("NFKC").toLowerCase().match(/[a-z0-9]+/g) || []).filter(w=>w.length>1&&!STOP.has(w));
  function project(input) {
    if (!Array.isArray(input) || input.length!==10) throw Error("expected 10 original conversation groups");
    const projected = [];
    for (const group of input) {
      const c=group.conversation, docs=[];
      const ss=Object.keys(c).filter(k=>/^session_[0-9]+$/.test(k)).sort((a,b)=>Number(a.slice(8))-Number(b.slice(8)));
      for(const session of ss) {
        const stamp=c[session+"_date_time"];
        for(const t of c[session]) {
          if(![t.dia_id,t.speaker,t.text,stamp].every(x=>typeof x==="string")) throw Error("invalid source turn");
          const frame=`[${t.dia_id} | ${session} | ${stamp} | ${t.speaker}]\n${t.text}\n`;
          docs.push({id:t.dia_id,session,text:`${t.speaker} ${stamp}\n${t.text}`,frame});
        }
      }
      if(new Set(docs.map(x=>x.id)).size!==docs.length)throw Error("duplicate source IDs");
      projected.push({group:group.sample_id,docs,queries:group.qa.map((q,i)=>({id:group.sample_id+":qa:"+String(i).padStart(4,"0"),text:q.question}))});
    }
    if(new Set(projected.map(x=>x.group)).size!==10)throw Error("duplicate group");
    // Gold/category/evidence/answers are excluded from all retrieval inputs.
    return projected;
  }
  function index(docs) {
    const postings=new Map(),termsByDoc=[],sizes=[];
    for(let i=0;i<docs.length;i++){
      const ts=terms(docs[i].text),freq=new Map();
      for(const t of ts)freq.set(t,(freq.get(t)||0)+1);
      sizes.push(ts.length); termsByDoc.push(freq);
      for(const [t,tf] of freq) {
        if(!postings.has(t))postings.set(t,[]);
        postings.get(t).push([i,tf]);
      }
    }
    const avg=sizes.reduce((a,b)=>a+b,0)/Math.max(1,docs.length);
    const idf=t=>Math.log(1+(docs.length-(postings.get(t)||[]).length+0.5)/((postings.get(t)||[]).length+0.5));
    const edges=Array.from({length:docs.length},()=>new Map());
    function add(a,b,w){
      if(a===b)return;
      edges[a].set(b,Math.max(edges[a].get(b)||0,w));
      edges[b].set(a,Math.max(edges[b].get(a)||0,w));
    }
    const previous=new Map();
    for(let i=0;i<docs.length;i++){
      const before=previous.get(docs[i].session);
      if(before!==undefined)add(before,i,1);
      previous.set(docs[i].session,i);
    }
    for(let i=0;i<docs.length;i++){
      const candidates=new Map();
      for(const t of termsByDoc[i].keys()){
        if(t.length<4)continue;
        const posting=postings.get(t);
        if(posting.length<2||posting.length>32)continue;
        for(const [j] of posting){
          if(j===i)continue;
          candidates.set(j,(candidates.get(j)||0)+idf(t));
        }
      }
      const top=[...candidates].sort((a,b)=>b[1]-a[1]||a[0]-b[0]).slice(0,4);
      for(const [j,w]of top)add(i,j,0.3+Math.min(1,w/12));
    }
    const bounded=edges.map(e=>[...e].sort((a,b)=>b[1]-a[1]||a[0]-b[0]).slice(0,8));
    return {docs,postings,termsByDoc,sizes,avg,idf,edges:bounded,
      undirectedEdges:edges.reduce((s,e)=>s+e.size,0)/2};
  }
  function rankBM25(ix,qtext) {
    const q=[...new Set(terms(qtext))].slice(0,64),score=new Map();
    for(const t of q){
      const rows=ix.postings.get(t)||[],idf=ix.idf(t);
      for(const [i,tf]of rows){
        const denominator=tf+1.2*(0.25+0.75*ix.sizes[i]/(ix.avg||1));
        score.set(i,(score.get(i)||0)+idf*tf*2.2/denominator);
      }
    }
    return [...score].sort((a,b)=>b[1]-a[1]||a[0]-b[0]).slice(0,256);
  }
  function orderA(rank) {return rank.map(r=>r[0]);}
  function orderC(ix,rank) {
    const scores=new Map(),peak=rank[0]?.[1]||1;
    function inc(i,w){scores.set(i,(scores.get(i)||0)+w);}
    for(const [i,s]of rank)inc(i,0.40*s/peak);
    for(const [i,s]of rank.slice(0,MAX_SEEDS)){
      const w=s/peak;inc(i,w);
      for(const [j,edge]of ix.edges[i]){
        inc(j,0.42*w*edge);
        for(const [k,second]of ix.edges[j])if(k!==i)inc(k,0.16*w*edge*second);
      }
    }
    return [...scores].sort((a,b)=>b[1]-a[1]||a[0]-b[0]).map(x=>x[0]);
  }
  function orderArmD(ix,rank,qtext) {
    const scores=new Map(),peak=rank[0]?.[1]||1;
    const episodic=/\b(when|before|after|during|first|last|date|time|month|year)\b/i.test(qtext);
    const procedural=/\b(how|steps|method|fix|solve|recipe|process)\b/i.test(qtext);
    function inc(i,w){scores.set(i,(scores.get(i)||0)+w);}
    for(const [i,s]of rank)inc(i,0.5*s/peak);
    for(const [i,s]of rank.slice(0,MAX_SEEDS)){
      const w=s/peak;inc(i,w);
      for(let step of [-2,-1,1,2]){
        const j=i+step;
        if(j>=0&&j<ix.docs.length&&ix.docs[i].session===ix.docs[j].session)inc(j, (episodic?0.55:0.27)*w/Math.abs(step));
      }
      if(procedural){
        for(const [j,edge]of ix.edges[i]){
          if(/\b(try|use|make|build|step|fix|test|run|change|plan)\b/i.test(ix.docs[j].text)) inc(j,.27*w*edge);
        }
      }else if(!episodic){
        for(const [j,edge]of ix.edges[i])inc(j,.23*w*edge);
      }
    }
    return [...scores].sort((a,b)=>b[1]-a[1]||a[0]-b[0]).map(x=>x[0]);
  }
  function pack(ix,order) {
    const ids=[],seen=new Set();let bytes=0;
    for(const i of order){
      if(seen.has(i)||i<0||i>=ix.docs.length)continue;
      seen.add(i);
      const size=new TextEncoder().encode(ix.docs[i].frame).length;
      if(bytes+size>MAX_BYTES)continue;
      bytes+=size;ids.push(ix.docs[i].id);
      if(ids.length>=N)break;
    }
    return {ids,context_bytes:bytes};
  }
  const projectPublic=project(raw);
  const need=new Set(partitions.evaluation), results=[],meta={};
  for(const g of projectPublic){
    if(!need.has(g.group))continue;
    const ix=index(g.docs);
    meta[g.group]={turns:g.docs.length,graph_edges:ix.undirectedEdges,queries:g.queries.length};
    for(const q of g.queries){
      const ranks=rankBM25(ix,q.text);
      for(const [arm,ord] of [["A",orderA(ranks)],["C",orderC(ix,ranks)],["D",orderArmD(ix,ranks,q.text)]]){
        const packed=pack(ix,ord);
        results.push({arm,group:g.group,query_id:q.id,selected_source_ids:packed.ids,context_bytes:packed.context_bytes});
      }
    }
  }
  return {schema:"hepta.memory.source-graph-controls.predictions.v1",source_groups:meta,models_executed:false,
    only_source_text_used:true,arms:["A","C","D"],budget:{turns:N,utf8_bytes:MAX_BYTES},predictions:results};
}

export function independentEvidenceScore(raw,predictionSet,partitions) {
  const gold=new Map(),sourceIds=new Map(),sourceFrames=new Map();
  if(JSON.stringify(predictionSet.arms)!==JSON.stringify(["A","C","D"]))throw Error("unexpected arms");
  for(const r of raw){
    const ids=new Set(),frames=new Map();
    for(const k of Object.keys(r.conversation).filter(k=>/^session_[0-9]+$/.test(k)))for(const t of r.conversation[k]){
      if(ids.has(t.dia_id))throw Error("duplicate source ID");
      ids.add(t.dia_id);
      frames.set(t.dia_id,`[${t.dia_id} | ${k} | ${r.conversation[k+"_date_time"]} | ${t.speaker}]\n${t.text}\n`);
    }
    sourceIds.set(r.sample_id,ids);sourceFrames.set(r.sample_id,frames);
    r.qa.forEach((q,i)=>gold.set(r.sample_id+":qa:"+String(i).padStart(4,"0"),{group:r.sample_id,category:q.category,evidence:q.evidence||[]}));
  }
  const results={};let complete=true;
  for(const arm of predictionSet.arms){
    const rows=predictionSet.predictions.filter(x=>x.arm===arm);
    let scorable=0,all=0,partial=0,adversarial=0,total=0,unresolved=0;
    const categories={}, groups={}, seen=new Set();
    const expected=new Set([...gold].filter(([qid,v])=>partitions.evaluation.includes(v.group)).map(([qid])=>qid));
    for(const r of rows){
      const g=gold.get(r.query_id);
      if(!g||g.group!==r.group||!expected.has(r.query_id)||seen.has(r.query_id))throw Error("missing/duplicate or mismatched row");
      seen.add(r.query_id);
      if(!Array.isArray(r.selected_source_ids)||r.selected_source_ids.length>8||
          new Set(r.selected_source_ids).size!==r.selected_source_ids.length||
          r.selected_source_ids.some(x=>!sourceIds.get(r.group).has(x)))throw Error("selected source scope mismatch");
      const exactBytes=r.selected_source_ids.reduce((n,id)=>n+new TextEncoder().encode(sourceFrames.get(r.group).get(id)).length,0);
      if(r.context_bytes!==exactBytes||exactBytes>4096)throw Error("forged/out-of-budget context bytes");
      total++;
      const cat=String(g.category);
      if(!categories[cat])categories[cat]={scorable:0,all:0,recall:0,adversarial:0};
      if(g.category===5){adversarial++;categories[cat].adversarial++;continue;}
      if(!g.evidence.length||g.evidence.some(x=>!sourceIds.get(r.group).has(x))){unresolved++;continue;}
      const selected=new Set(r.selected_source_ids),required=[...new Set(g.evidence)];
      const hits=required.filter(x=>selected.has(x)).length;
      const ratio=hits/required.length,yes=hits===required.length?1:0;
      scorable++;all+=yes;partial+=ratio;
      categories[cat].scorable++;categories[cat].all+=yes;categories[cat].recall+=ratio;
      if(!groups[r.group])groups[r.group]={scorable:0,all:0,recall:0};
      groups[r.group].scorable++;groups[r.group].all+=yes;groups[r.group].recall+=ratio;
    }
    if(total!==expected.size||seen.size!==expected.size)throw Error("partial query census");
    results[arm]={planned_questions:total,scorable,adversarial,unresolved,
      all_gold_support_recalled:all/scorable,mean_gold_support_recall:partial/scorable,
      group_macro_all_gold_support:partitions.evaluation.reduce((n,g)=>n+groups[g].all/groups[g].scorable,0)/partitions.evaluation.length,
      by_category:Object.fromEntries(Object.entries(categories).map(([k,v])=>[k,{...v,
        all_gold_support_rate:v.scorable?v.all/v.scorable:null,
        mean_support_recall:v.scorable?v.recall/v.scorable:null}])),
      by_group:Object.fromEntries(Object.entries(groups).map(([k,v])=>[k,{scorable:v.scorable,
        all_gold_support_recalled:v.all/v.scorable,mean_gold_support_recall:v.recall/v.scorable}]))};
  }
  const diffs={};
  for(const [a,b]of [["C","A"],["D","A"],["D","C"]]){
    diffs[a+"_minus_"+b]={group_macro_difference:results[a].group_macro_all_gold_support-results[b].group_macro_all_gold_support,
     whole_group_deltas:partitions.evaluation.map(g=>results[a].by_group[g].all_gold_support_recalled-results[b].by_group[g].all_gold_support_recalled)};
  }
  return {schema:"hepta.memory.source-graph-controls.audit.v1",historical_test_only:true,
    source_sha256:"79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4",
    all_arms_A_to_I_complete:false,whole_answer_scored:false,semantic_citations_verified:false,
    prospective_independence_verified:false,source_license:"CC-BY-NC-4.0",
    results,descriptive_contrasts:diffs,source_graph_meta:predictionSet.source_groups,
    authority:"SHADOW_ONLY/DENY_ALL/HOLD_NO_GO"};
}

if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href) {
const args=process.argv.slice(2);
if(args.length!==3)throw Error("usage: node memory_source_graph_controls.mjs ORIGINAL_LOCOMO.json OUT_PREDICTIONS.json OUT_AUDIT.json");
const bytes=fs.readFileSync(args[0]);
const expected="79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4";
if(crypto.createHash("sha256").update(bytes).digest("hex")!==expected)throw Error("original LoCoMo source pin mismatch");
const rows=JSON.parse(bytes.toString("utf8"));
const partitions={evaluation:["conv-47","conv-42","conv-48","conv-43","conv-49","conv-50"]};
const predictions=sourceOnlyControls(rows,partitions);
fs.writeFileSync(args[1],JSON.stringify(predictions)+"\n",{flag:"wx"});
const report=independentEvidenceScore(rows,predictions,partitions);
report.prediction_sha256=crypto.createHash("sha256").update(fs.readFileSync(args[1])).digest("hex");
fs.writeFileSync(args[2],JSON.stringify(report,null,2)+"\n",{flag:"wx"});
console.log(JSON.stringify({status:report.authority,census:report.results.A.planned_questions,arms:predictions.arms}));

}
