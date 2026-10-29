"use strict";
/*
 * Positive-delay event network. The coordinator advances to actual next events.
 * No clock grid is introduced. Unit private queues/clocks remain owner state;
 * a neuron receives only inputs delivered to it at the specified time.
 */
const RRDelayedNetwork = (() => {
  const check=(ok,msg)=>{if(!ok)throw new Error(msg);};
  const copy=x=>JSON.parse(JSON.stringify(x));
  const ordered=x=>Array.isArray(x)?x.map(ordered):x&&typeof x==="object"?
    Object.fromEntries(Object.keys(x).sort().map(k=>[k,ordered(x[k])])):x;
  const same=(a,b)=>JSON.stringify(ordered(a))===JSON.stringify(ordered(b));
  function coordinate(units,edges,encode,{identity,horizon,maxSteps=100000,restored=null}={}) {
    check(Array.isArray(units)&&units.length>0&&units.length<=64,"network unit cap");
    check(Number.isFinite(horizon)&&horizon>0,"network horizon");
    check(typeof identity==="string"&&identity.length>0&&identity.length<=256,"network identity");
    check(Number.isSafeInteger(maxSteps)&&maxSteps>0&&maxSteps<=1e6,"network work cap");
    check(typeof encode==="function","missing synapse encoder");
    check(Array.isArray(edges)&&edges.length<=4096,"network edge cap");
    for(const e of edges) {
      check(e&&Number.isSafeInteger(e.from)&&Number.isSafeInteger(e.to)&&
        e.from>=0&&e.from<units.length&&e.to>=0&&e.to<units.length,
        "invalid synapse endpoint");
      check(Number.isFinite(e.delay)&&e.delay>0,"axonal delay must be strictly positive");
    }
    const graph=copy(edges);
    let time=units[0].observe().time,steps=0,cursors=units.map(()=>0),pulses=[],poisoned=false;
    check(units.every(u=>u.observe().time===time),"unit clock mismatch");
    if(restored) {
      check(JSON.stringify(Object.keys(restored).sort())===
        JSON.stringify(["schema","identity","horizon","time","steps","maxSteps","edges","cursors","pulses","units"].sort()),
        "unknown network checkpoint fields");
      check(restored.schema==="rr-delayed-network-1"&&restored.identity===identity,
        "network checkpoint identity");
      check(same(restored.edges,graph),"network graph mismatch");
      check(restored.time===time&&restored.horizon===horizon&&restored.cursors.length===units.length&&restored.units.length===units.length,"network restore clocks");
      check(Number.isSafeInteger(restored.steps)&&restored.steps>=0&&restored.steps<=maxSteps&&
        restored.maxSteps===maxSteps,"network step counter mismatch");
      const expected=[];
      for(let i=0;i<units.length;i++) {
        const history=units[i].pulsesSince(0);
        check(restored.cursors[i]===history.cursor,"network pulse cursor corruption");
        history.pulses.forEach((pulse,ordinal)=>expected.push({from:i,ordinal,pulse:copy(pulse)}));
      }
      expected.sort((a,b)=>a.pulse.time-b.pulse.time||a.from-b.from||a.ordinal-b.ordinal);
      check(same(expected,restored.pulses),"network pulse history corruption");
      cursors=copy(restored.cursors);pulses=copy(restored.pulses);steps=restored.steps;
    }
    function collect() {
      // Batch every pulse at this global timestamp before delivering any future input.
      const emitted=[];
      for(let from=0;from<units.length;from++) {
        const fresh=units[from].pulsesSince(cursors[from]);
        for(const pulse of fresh.pulses) {
          const ordinal=cursors[from]++;
          emitted.push({from,ordinal,pulse:copy(pulse)});
        }
        check(cursors[from]===fresh.cursor,"pulse cursor mismatch");
      }
      emitted.sort((a,b)=>a.pulse.time-b.pulse.time||a.from-b.from||a.ordinal-b.ordinal);
      for(const item of emitted) {
        pulses.push(item);
        for(let k=0;k<graph.length;k++)if(graph[k].from===item.from) {
          const e=graph[k],at=item.pulse.time+e.delay;
          check(Number.isFinite(at)&&at>time,"delivery time lost floating-point resolution");
          if(at>horizon)continue; // No delivery is observed beyond the fixed experiment horizon.
          const event=encode(copy(e),copy(item),at,k);
          check(event&&event.time===at,"encoder changed delivery time");
          units[e.to].enqueue(event);
        }
      }
    }
    function runUntil(end) {
      check(!poisoned,"network stopped after partial failure");
      check(Number.isFinite(end)&&end>=time&&end<=horizon,"invalid network horizon");
      try {
      // Initial same-time external events may be pending, even if end equals now.
      while(true) {
        const next=Math.min(...units.map(u=>u.nextEventTime()??Infinity));
        check(next>=time,"network event clock went backwards");
        const at=Math.min(next,end);
        for(const u of units)u.runUntil(at);
        time=at;collect();if(next<=end)steps++;
        check(steps<=maxSteps,"network event work cap exceeded");
        if(at===end)return observe();
        check(units.every(u=>(u.nextEventTime()??Infinity)>at),"network made no event progress");
      }
      } catch(error) { poisoned=true;throw error; }
    }
    function observe() {
      return {time,units:units.map(u=>u.observe()),pulseCount:pulses.length};
    }
    function snapshot() {
      check(!poisoned,"cannot checkpoint a partially failed network");
      return {schema:"rr-delayed-network-1",identity,horizon,time,steps,maxSteps,
        edges:copy(graph),cursors:copy(cursors),pulses:copy(pulses),
        units:units.map(u=>u.snapshot())};
    }
    return {runUntil,observe,snapshot,pulses:()=>copy(pulses),
      statistics:()=>units.map(u=>u.statistics())};
  }
  /*
   * For held log-linear channel rates q=exp(theta.features), complete-path NLL
   * is sum(q*exposure-count*log(q)); count/exposure include final censoring.
   * The statistics already account for refractory/budget-disabled hazards.
   */
  function likelihood(theta,records,l2=0) {
    check(Array.isArray(theta)&&theta.length>0&&theta.every(Number.isFinite),"invalid weights");
    check(Array.isArray(records)&&records.length>0,"missing path records");
    check(Number.isFinite(l2)&&l2>=0,"invalid regularizer");
    let loss=.5*l2*theta.reduce((s,w)=>s+w*w,0),gradient=theta.map(w=>l2*w);
    for(const r of records) {
      check(r&&Array.isArray(r.features)&&r.features.length===theta.length&&
        r.features.every(Number.isFinite)&&Number.isFinite(r.exposure)&&r.exposure>=0&&
        Number.isSafeInteger(r.count)&&r.count>=0,"invalid complete path record");
      check(r.exposure>0||r.count===0,"positive event count without exposure");
      const logRate=theta.reduce((s,w,j)=>s+w*r.features[j],0);
      check(logRate>=-40&&logRate<=40,"declared log-rate domain");
      const hazard=Math.exp(logRate)*r.exposure;
      loss+=hazard-r.count*logRate;
      for(let j=0;j<theta.length;j++)gradient[j]+=(hazard-r.count)*r.features[j];
    }
    check(Number.isFinite(loss)&&gradient.every(Number.isFinite),"nonfinite path objective or gradient");
    return {loss,gradient};
  }
  function fit(initial,records,{steps=300,learningRate=.03,l2=.01}={}) {
    check(Number.isSafeInteger(steps)&&steps>0&&steps<=10000,"optimizer work cap");
    check(Number.isFinite(learningRate)&&learningRate>0&&learningRate<=1,"learning rate");
    const theta=initial.slice(),m=theta.map(()=>0),v=theta.map(()=>0),history=[];
    for(let k=1;k<=steps;k++) {
      const r=likelihood(theta,records,l2);
      if(k===1||k%50===0||k===steps)history.push({updates:k-1,loss:r.loss});
      for(let j=0;j<theta.length;j++) {
        const g=r.gradient[j]/records.length;
        m[j]=.9*m[j]+.1*g;v[j]=.999*v[j]+.001*g*g;
        theta[j]-=learningRate*(m[j]/(1-.9**k))/(Math.sqrt(v[j]/(1-.999**k))+1e-8);
      }
    }
    return {theta,history,final:likelihood(theta,records,l2)};
  }
  function diagnostic(M,C,weights,seed,restored=null,override=null) {
    check(Array.isArray(weights)&&weights.length===2&&weights.every(row=>
      Array.isArray(row)&&row.length===5&&row.every(Number.isFinite)),"diagnostic weights");
    check(Number.isInteger(seed)&&seed>0&&seed<4294967296,"diagnostic seed");
    const scenario=override?copy(override):{maturity:seed%2===0?[1,3]:[2,2],
      shock:Math.floor(seed/2)%2===0?2:0,pressureMode:"full"};
    check(JSON.stringify(Object.keys(scenario).sort())===JSON.stringify(["maturity","pressureMode","shock"])&&
      ["full","mean"].includes(scenario.pressureMode)&&[0,2].includes(scenario.shock)&&
      Array.isArray(scenario.maturity)&&scenario.maturity.length===2&&
      scenario.maturity.every(x=>Number.isFinite(x)&&x>0&&x<4),"invalid diagnostic scenario");
    const {maturity,shock,pressureMode}=scenario;
    // Short routing label; full weights/scenario are separately checked on restore.
    // This label is not an authentication digest.
    let label=2166136261;
    for(const ch of JSON.stringify([weights,maturity,shock,pressureMode]))
      label=Math.imul(label^ch.charCodeAt(0),16777619)>>>0;
    const identity="RRN1:"+label.toString(16).padStart(8,"0");
    const baseFeatures=[1,0,0,0,0],dot=(w,f)=>w.reduce((s,x,j)=>s+x*f[j],0);
    let features=[[[...baseFeatures]],[[...baseFeatures]]];
    if(restored) {
      check(JSON.stringify(Object.keys(restored).sort())===
        JSON.stringify(["schema","seed","weights","features","network","scenario"].sort()),"unknown diagnostic checkpoint fields");
      check(restored.schema==="rr-network-diagnostic-1"&&restored.seed===seed&&
        JSON.stringify(restored.weights)===JSON.stringify(weights)&&
        same(restored.scenario,scenario),"diagnostic restore identity");
      check(Array.isArray(restored.features)&&restored.features.length===2&&restored.features.every(rows=>
        Array.isArray(rows)&&rows.length>0&&rows.length<=20000&&rows.every(f=>
          Array.isArray(f)&&f.length===5&&f.every(Number.isFinite))),"invalid restored feature history");
      features=copy(restored.features);
    }
    const units=weights.map((w,i)=>{
      const hooks={
        input:(obs,data)=>{
          check(Array.isArray(data)&&data.length===2&&data.every(Number.isFinite),"diagnostic input");
          const live=obs.obligations.filter(x=>x.status==="live");
          const totalCost=live.reduce((sum,o)=>sum+o.renewDebit+o.renewLoss,0);
          const mean=live.length?live.reduce((sum,o)=>sum+o.deadline,0)/live.length:0;
          const pressure=(pressureMode==="mean"?totalCost*Math.exp(-Math.max(0,mean-obs.time)):
            live.reduce((sum,o)=>sum+(o.renewDebit+o.renewLoss)*
              Math.exp(-Math.max(0,o.deadline-obs.time)),0))/(1+obs.budget);
          const f=[1,data[0],data[1],Math.tanh(obs.trace),pressure];
          features[i].push(f);
          return [3,Math.exp(dot(w,f))];
        },
        // Explicit value proxy, independent of learned rates. Actual renewable
        // obligations and utility charges remain in the event runtime.
        continuation:post=>.2*post.budget+
          1.2*post.obligations.filter(o=>o.status==="retained").length
      };
      const config={identity:identity+":unit"+i,evidence:[0,1],
        channels:[{id:"up",from:0,to:1,rate:3,spike:false},
          {id:"pulse",from:1,to:0,rate:Math.exp(dot(w,baseFeatures)),spike:true}],
        resetState:0,refractory:.05,traceTau:.6,pulseDebit:1,budgetCap:8,
        horizon:4,maxRecords:20000};
      if(restored) {
        check(same(restored.network.units[i].config,config),"restored physical config drift");
        return M.restore(restored.network.units[i],C,hooks,config.identity);
      }
      const initial={stateIndex:0,budget:6,seed:(seed^(i?0x9e3779b9:0))>>>0,
        obligations:maturity.map((deadline,j)=>({id:"memory"+j,deadline,renewDebit:1,
          renewLoss:.15,emitDebit:1,emitValue:.4,status:"live"})),
        events:[{time:0,type:"input",data:[0,0]},
          ...[.5,1.5,2.5,3.5].map((time,j)=>({time,type:"input",data:[j%2===0?.5:-.5,0]})),
          {time:1.5,type:"shock",amount:shock},{time:2.5,type:"refill",amount:1}]};
      return M.create(config,initial,C,hooks);
    });
    const encode=(edge,item,at)=>({time:at,type:"input",data:[0,1]});
    const net=coordinate(units,[{from:0,to:1,delay:.1},{from:1,to:0,delay:.15}],encode,
      {identity,horizon:4,maxSteps:10000,restored:restored?.network??null});
    function records() {
      return units.map((unit,i)=>{
        const regimes=unit.statistics().regimes;
        check(regimes.length===features[i].length,"input feature/statistical regime mismatch");
        return regimes.map((r,j)=>{
          const f=features[i][j];
          check(Math.abs(Math.log(r.rates[1])-dot(weights[i],f))<1e-10,
            "path feature/rate binding mismatch");
          return {features:copy(f),exposure:r.exposure[1],count:r.counts[1]};
        });
      });
    }
    if(restored)records();
    return {runUntil:net.runUntil,observe:net.observe,pulses:net.pulses,
      statistics:net.statistics,records,
      snapshot:()=>({schema:"rr-network-diagnostic-1",seed,weights:copy(weights),scenario:copy(scenario),
        features:copy(features),network:net.snapshot()})};
  }
  return {coordinate,likelihood,fit,diagnostic};
})();
if(typeof module!=="undefined")module.exports=RRDelayedNetwork;
