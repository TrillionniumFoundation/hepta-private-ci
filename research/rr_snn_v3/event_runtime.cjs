"use strict";
/* Finite marked CTMC with deterministic refractory and one-cycle obligations.
 * No Brownian/global-optimum/production claim. Hooks get current observations only.
 * Stops do not split hazard/trace/statistic anchors: exact same-RNG replay.
 */
const RRMarkedEvents = (() => {
  const check=(ok,msg)=>{if(!ok) throw new Error(msg);};
  const clone=x=>JSON.parse(JSON.stringify(x));
  const finite=x=>Number.isFinite(x);
  const integer=x=>Number.isSafeInteger(x)&&x>=0;
  const exactKeys=(x,keys)=>check(x&&Object.keys(x).sort().join("|")===keys.split(" ").sort().join("|"),"unknown/missing fields");
  const freeze=x=>{if(x&&typeof x==="object"){Object.values(x).forEach(freeze);Object.freeze(x);}return x;};
  const priority={shock:0,refill:1,control:2,input:2};
  const rngAlgorithm="lcg32-avalanche-seed-v1";
  function seedWord(seed) {
    let x=(seed+0x9e3779b9)>>>0;
    x=Math.imul(x^(x>>>16),0x85ebca6b);
    x=Math.imul(x^(x>>>13),0xc2b2ae35);
    return (x^(x>>>16))>>>0;
  }
  function configValid(c) {
    exactKeys(c,"identity evidence channels resetState refractory traceTau pulseDebit budgetCap horizon maxRecords");
    check(typeof c.identity==="string"&&c.identity.length>0&&c.identity.length<=128,"identity");
    check(Array.isArray(c.evidence)&&c.evidence.length>0&&c.evidence.length<=16&&c.evidence.every(x=>finite(x)&&Math.abs(x)<=1e6),"evidence grid");
    check(integer(c.resetState)&&c.resetState<c.evidence.length,"reset state");
    check(finite(c.refractory)&&c.refractory>=0&&c.refractory<=1e6&&finite(c.traceTau)&&c.traceTau>0&&c.traceTau<=1e9,"time constants");
    check(integer(c.pulseDebit)&&c.pulseDebit>0&&integer(c.budgetCap)&&c.budgetCap>=c.pulseDebit&&c.budgetCap<=1e6,"budget config");
    check(finite(c.horizon)&&c.horizon>0&&c.horizon<=1e6&&integer(c.maxRecords)&&c.maxRecords>0&&c.maxRecords<=100000,"work/time bounds");
    check(Array.isArray(c.channels)&&c.channels.length>0&&c.channels.length<=64,"channel count");
    const ids=new Set();
    for(const h of c.channels) {
      exactKeys(h,"id from to rate spike");
      check(typeof h.id==="string"&&h.id.length>0&&!ids.has(h.id),"channel id");ids.add(h.id);
      check(integer(h.from)&&integer(h.to)&&h.from<c.evidence.length&&h.to<c.evidence.length,"channel states");
      check(finite(h.rate)&&h.rate>=0&&h.rate<=1e6&&typeof h.spike==="boolean","channel rate/mark");
      check(h.spike?h.to===c.resetState:h.from!==h.to,"marked reset or ordinary jump");
    }
  }
  function ratesValid(r,c) {
    check(Array.isArray(r)&&r.length===c.channels.length&&r.every(x=>finite(x)&&x>=0&&x<=1e6),"held rates");
  }
  function eventValid(e,c) {
    check(e&&Object.hasOwn(priority,e.type)&&finite(e.time)&&e.time>=0&&e.time<=c.horizon,"external event");
    exactKeys(e,"time type "+(e.type==="control"?"rates":e.type==="input"?"data":"amount"));
    if(e.type==="control") ratesValid(e.rates,c);
    else if(e.type==="input") check(Array.isArray(e.data)&&e.data.length<=64&&e.data.every(finite),"input data");
    else check(integer(e.amount)&&e.amount<=c.budgetCap,"resource amount");
  }
  function obligationValid(o,c) {
    exactKeys(o,"id deadline renewDebit renewLoss emitDebit emitValue status");
    check(typeof o.id==="string"&&o.id.length>0&&finite(o.deadline)&&o.deadline>=0&&o.deadline<=c.horizon,"obligation identity/time");
    check(integer(o.renewDebit)&&integer(o.emitDebit)&&o.renewDebit<=c.budgetCap&&o.emitDebit<=c.budgetCap,"obligation debit");
    check(finite(o.renewLoss)&&o.renewLoss>=0&&o.renewLoss<=1e12&&finite(o.emitValue)&&o.emitValue>=0&&o.emitValue<=1e6,"obligation utility");
    check(["live","retained","resolved"].includes(o.status),"obligation status");
  }
  const compare=(a,b)=>a.time-b.time||priority[a.type]-priority[b.type]||a.seq-b.seq;
  function engine(config,state,api,hooks={}) {
    configValid(config);check(api&&typeof api.deadlineChoices==="function","continuation operator");
    check(hooks&&Object.keys(hooks).every(k=>["continuation","input"].includes(k))&&
      Object.values(hooks).every(x=>typeof x==="function"),"hooks");
    const c=clone(config),s=clone(state),n=c.channels.length;
    const live=()=>!s.aborted;
    const guard=()=>check(live(),"runtime aborted; restore prior checkpoint");
    const rng=()=>{s.rng.word=(Math.imul(s.rng.word,1664525)+1013904223)>>>0;s.rng.draws++;return (s.rng.word+.5)/4294967296;};
    const exp=()=>-Math.log(rng());
    const traceAt=t=>s.trace.value*Math.exp(-(t-s.trace.time)/c.traceTau);
    function observation(at=s.now) {
      return freeze({time:at,stateIndex:s.stateIndex,evidence:c.evidence[s.stateIndex],budget:s.budget,
        refractoryRemaining:Math.max(0,(s.refUntil===null?at:s.refUntil)-at),trace:traceAt(at),
        spikeCount:s.spikeCount,obligations:clone(s.obligations)});
    }
    function eligible() {
      const blocked=s.refUntil!==null&&s.refUntil>s.clock.at;
      return c.channels.map(h=>!blocked&&h.from===s.stateIndex&&(!h.spike||s.budget>=c.pulseDebit)?1:0);
    }
    const activeRates=()=>eligible().map((e,j)=>e*s.rates[j]);
    function stochasticTime() {
      const a=activeRates().reduce((x,y)=>x+y,0);
      return a>0?Math.max(s.now,s.clock.at+s.clock.remaining/a):Infinity;
    }
    function nextEventTime() {
      guard();if(s.now>=c.horizon) return null;
      const deadline=Math.min(Infinity,...s.obligations.filter(o=>o.status==="live").map(o=>o.deadline));
      return Math.min(c.horizon,s.cursor<s.queue.length?s.queue[s.cursor].time:Infinity,
        deadline,s.refUntil===null?Infinity:s.refUntil,stochasticTime());
    }
    function commitTo(t,hit=false) {
      const dt=t-s.clock.at,e=eligible(),reg=s.regimes[s.regimes.length-1];
      check(finite(dt)&&dt>=0,"clock moved backwards");
      e.forEach((x,j)=>{reg.exposure[j]+=x*dt;});
      const total=e.reduce((a,x,j)=>a+x*s.rates[j],0);
      s.clock.remaining=hit?0:Math.max(0,s.clock.remaining-total*dt);
      s.clock.at=t;s.now=t;reg.end=t;
    }
    function record(entry) {
      check(s.log.length<c.maxRecords,"record/work cap");
      const row={time:s.now,...entry};s.log.push(row);
      if(row.spike) s.pulses.push({time:s.now,kind:row.type,channel:row.channel===undefined?null:row.channel});
    }
    function pulse() {
      s.trace={time:s.now,value:traceAt(s.now)+1};s.spikeCount++;
      s.stateIndex=c.resetState;s.refUntil=c.refractory>0?s.now+c.refractory:null;
    }
    function setRates(r,forceNew=false) {
      ratesValid(r,c);
      if(!forceNew&&r.every((x,j)=>x===s.rates[j])) return;
      s.rates=r.slice();
      s.regimes.push({id:s.regimes.length,start:s.now,end:s.now,rates:r.slice(),exposure:Array(n).fill(0),counts:Array(n).fill(0)});
    }
    function external(e) {
      if(e.type==="shock") {const removed=Math.min(s.budget,e.amount);s.budget-=removed;s.ledger.removed+=removed;}
      else if(e.type==="refill") {const added=Math.min(c.budgetCap-s.budget,e.amount);s.budget+=added;s.ledger.added+=added;}
      else if(e.type==="control") setRates(e.rates);
      else if(hooks.input) setRates(hooks.input(observation(),freeze(e.data.slice())),true);
      record({type:e.type,seq:e.seq,budget:s.budget,regime:s.regimes.length-1});
    }
    function deadlines() {
      const due=s.obligations.filter(o=>o.status==="live"&&o.deadline===s.now);
      if(!due.length) return;
      const canEmit=s.refUntil===null||s.refUntil<=s.now,base=observation();
      const post=next=>{
        const obs=clone(base);obs.budget=next.budget;
        if(next.emitCount) {obs.stateIndex=c.resetState;obs.evidence=c.evidence[c.resetState];
          obs.trace+=1;obs.spikeCount++;obs.refractoryRemaining=c.refractory;}
        obs.obligations=s.obligations.map(o=>{
          const j=due.findIndex(d=>d.id===o.id);if(j<0) return clone(o);
          return {...o,status:(next.renewedMask&(1<<j))?"retained":"resolved",
            deadline:(next.renewedMask&(1<<j))?c.horizon:o.deadline};
        });return freeze(obs);
      };
      const all=api.deadlineChoices({budget:s.budget,evidence:base.evidence,resetEvidence:c.evidence[c.resetState],
        legs:due.map(o=>({renewDebit:o.renewDebit,emitDebit:o.emitDebit+c.pulseDebit,
          renewLoss:o.renewLoss,emitReward:o.emitValue*base.evidence})),
        continuation:next=>next.emitCount>1||(!canEmit&&next.emitCount)?0:(hooks.continuation?hooks.continuation(post(next)):0)});
      const choices=all.choices.filter(a=>a.next.emitCount<=1&&(canEmit||a.next.emitCount===0));
      const best=choices.reduce((a,b)=>b.value>a.value?b:a),next=post(best.next);
      check(finite(best.value)&&finite(best.loss)&&finite(best.emittedReward),"deadline value overflow");
      s.budget=next.budget;s.obligations=clone(next.obligations);
      s.ledger.spentPulse+=best.next.emitCount*c.pulseDebit;
      s.ledger.spentDeadline+=best.charge-best.next.emitCount*c.pulseDebit;
      s.utility.loss+=best.loss;s.utility.emitted+=best.emittedReward;
      if(best.next.emitCount) pulse();
      record({type:"deadline",due:due.map(o=>o.id),actions:best.actions,charge:best.charge,
        loss:best.loss,reward:best.emittedReward,value:best.value,spike:best.next.emitCount===1,budget:s.budget});
    }
    function stochastic() {
      const rates=activeRates(),a=rates.reduce((x,y)=>x+y,0);if(a===0) return;
      let draw=rng()*a,j=0;while(j<rates.length-1&&draw>=rates[j]) {draw-=rates[j];j++;}
      check(rates[j]>0,"selected zero rate");
      const h=c.channels[j],from=s.stateIndex;s.regimes[s.regimes.length-1].counts[j]++;
      if(h.spike) {s.budget-=c.pulseDebit;s.ledger.spentPulse+=c.pulseDebit;pulse();}
      else s.stateIndex=h.to;
      record({type:"jump",channel:h.id,channelIndex:j,from,to:s.stateIndex,rate:rates[j],
        regime:s.regimes.length-1,spike:h.spike,budget:s.budget});
      s.clock.remaining=exp();
    }
    function runUntil(target) {
      guard();check(finite(target)&&target>=s.now&&target<=c.horizon,"run target");
      try {
        for(let steps=0;;steps++) {
          check(steps<=c.maxRecords,"event work cap");
          const t=nextEventTime();
          if(t===null||t>target||t===c.horizon) {s.now=target;break;}
          const hit=stochasticTime()===t;commitTo(t,hit);
          while(s.cursor<s.queue.length&&s.queue[s.cursor].time===t) external(s.queue[s.cursor++]);
          deadlines();
          if(s.refUntil!==null&&s.refUntil<=t) {s.refUntil=null;record({type:"release",budget:s.budget});}
          if(s.clock.remaining===0) stochastic();
        }
      } catch(e) {s.aborted=true;throw e;}
      return observation();
    }
    function enqueue(event) {
      guard();eventValid(event,c);check(event.time>s.now,"enqueue requires strictly future time");
      check(s.queue.length<4096,"queue cap");
      const e={...clone(event),seq:s.nextSeq++};s.queue.push(e);s.queue.sort(compare);return e.seq;
    }
    function statistics() {
      guard();const regimes=clone(s.regimes),last=regimes[regimes.length-1],dt=s.now-s.clock.at;
      eligible().forEach((x,j)=>{last.exposure[j]+=x*dt;});last.end=s.now;
      let hazard=0,eventLogRate=0,events=0;
      for(const r of regimes) for(let j=0;j<n;j++) {
        hazard+=r.rates[j]*r.exposure[j];events+=r.counts[j];
        if(r.counts[j]) eventLogRate+=r.counts[j]*Math.log(r.rates[j]);
      }
      return {regimes,hazard,eventLogRate,logLikelihood:eventLogRate-hazard,
        stochasticEvents:events,physicalPulses:s.spikeCount,censoredUntil:s.now};
    }
    function snapshot() {guard();return {schema:"rrsnn.marked-events.v1",config:clone(c),state:clone(s)};}
    function pulsesSince(cursor=0) {
      guard();check(integer(cursor)&&cursor<=s.pulses.length,"pulse cursor");
      return {cursor:s.pulses.length,pulses:clone(s.pulses.slice(cursor))};
    }
    return {runUntil,nextEventTime,enqueue,observe:observation,statistics,snapshot,pulsesSince};
  }
  function create(config,initial,api,hooks={}) {
    configValid(config);exactKeys(initial,"stateIndex budget seed obligations events");
    const c=clone(config),n=c.channels.length;
    check(integer(initial.stateIndex)&&initial.stateIndex<c.evidence.length&&integer(initial.budget)&&initial.budget<=c.budgetCap,"initial state");
    check(integer(initial.seed)&&initial.seed<=0xffffffff,"seed");
    check(Array.isArray(initial.obligations)&&initial.obligations.length<=8&&new Set(initial.obligations.map(o=>o.id)).size===initial.obligations.length,"obligations");
    initial.obligations.forEach(o=>{obligationValid(o,c);check(o.status==="live"&&o.deadline<c.horizon,"initial obligation");});
    check(Array.isArray(initial.events)&&initial.events.length<=4096,"events");
    initial.events.forEach(e=>eventValid(e,c));
    const word=(Math.imul(seedWord(initial.seed),1664525)+1013904223)>>>0;
    const rates=c.channels.map(h=>h.rate);
    const state={now:0,stateIndex:initial.stateIndex,budget:initial.budget,refUntil:null,
      trace:{time:0,value:0},spikeCount:0,rng:{word,draws:1},
      clock:{at:0,remaining:-Math.log((word+.5)/4294967296)},rates,
      regimes:[{id:0,start:0,end:0,rates:rates.slice(),exposure:Array(n).fill(0),counts:Array(n).fill(0)}],
      obligations:clone(initial.obligations),queue:initial.events.map((e,i)=>({...clone(e),seq:i})).sort(compare),
      cursor:0,nextSeq:initial.events.length,ledger:{initial:initial.budget,spentPulse:0,spentDeadline:0,removed:0,added:0},
      utility:{emitted:0,loss:0},log:[],pulses:[],aborted:false};
    return engine(c,state,api,hooks);
  }
  function restore(cp,api,hooks={},expectedIdentity) {
    exactKeys(cp,"schema config state");check(cp.schema==="rrsnn.marked-events.v1","checkpoint schema");
    configValid(cp.config);check(typeof expectedIdentity==="string"&&cp.config.identity===expectedIdentity,"checkpoint identity");
    const c=cp.config,s=cp.state,n=c.channels.length;
    exactKeys(s,"now stateIndex budget refUntil trace spikeCount rng clock rates regimes obligations queue cursor nextSeq ledger utility log pulses aborted");
    check(s.aborted===false&&finite(s.now)&&s.now>=0&&s.now<=c.horizon,"checkpoint time/status");
    check(integer(s.stateIndex)&&s.stateIndex<c.evidence.length&&integer(s.budget)&&s.budget<=c.budgetCap,"checkpoint state");
    check(s.refUntil===null||(finite(s.refUntil)&&s.refUntil>=s.now),"checkpoint refractory");
    exactKeys(s.trace,"time value");check(finite(s.trace.time)&&s.trace.time>=0&&s.trace.time<=s.now&&finite(s.trace.value)&&s.trace.value>=0,"checkpoint trace");
    exactKeys(s.rng,"word draws");check(integer(s.rng.word)&&s.rng.word<=0xffffffff&&integer(s.rng.draws)&&s.rng.draws>=1,"checkpoint rng");
    exactKeys(s.clock,"at remaining");check(finite(s.clock.at)&&s.clock.at>=0&&s.clock.at<=s.now&&finite(s.clock.remaining)&&s.clock.remaining>=0,"checkpoint hazard");
    ratesValid(s.rates,c);check(Array.isArray(s.regimes)&&s.regimes.length>0&&s.regimes.length<=c.maxRecords+1,"checkpoint regimes");
    for(let i=0;i<s.regimes.length;i++) {
      const r=s.regimes[i];exactKeys(r,"id start end rates exposure counts");ratesValid(r.rates,c);
      check(r.id===i&&finite(r.start)&&finite(r.end)&&r.start>=0&&r.end>=r.start&&r.end<=s.now,"checkpoint regime time");
      check(r.exposure.length===n&&r.exposure.every(x=>finite(x)&&x>=0)&&r.counts.length===n&&r.counts.every(integer),"checkpoint exposure/count");
      check(r.counts.every((v,j)=>v===0||r.rates[j]>0),"checkpoint count at zero rate");
    }
    check(JSON.stringify(s.rates)===JSON.stringify(s.regimes[s.regimes.length-1].rates),"checkpoint held regime");
    check(Array.isArray(s.queue)&&s.queue.length<=4096&&integer(s.cursor)&&s.cursor<=s.queue.length&&integer(s.nextSeq),"checkpoint queue");
    const seqs=new Set();s.queue.forEach((e,i)=>{
      const {seq,...event}=e;eventValid(event,c);check(integer(seq)&&seq<s.nextSeq&&!seqs.has(seq),"checkpoint event sequence");seqs.add(seq);
      check(!i||compare(s.queue[i-1],e)<=0,"checkpoint queue order");
      check(i<s.cursor?e.time<=s.now:e.time>=s.now,"checkpoint event cursor");
    });
    check(Array.isArray(s.obligations)&&s.obligations.length<=8&&new Set(s.obligations.map(o=>o.id)).size===s.obligations.length,"checkpoint obligations");
    s.obligations.forEach(o=>{obligationValid(o,c);check(o.status!=="live"||o.deadline>=s.now,"stale obligation");});
    exactKeys(s.ledger,"initial spentPulse spentDeadline removed added");
    check(Object.values(s.ledger).every(integer)&&s.budget===s.ledger.initial+s.ledger.added-s.ledger.removed-s.ledger.spentPulse-s.ledger.spentDeadline,"checkpoint budget ledger");
    exactKeys(s.utility,"emitted loss");check(Object.values(s.utility).every(finite)&&s.utility.loss>=0,"checkpoint utility");
    check(integer(s.spikeCount)&&Array.isArray(s.log)&&s.log.length<=c.maxRecords&&Array.isArray(s.pulses)&&s.pulses.length===s.spikeCount,"checkpoint logs");
    s.pulses.forEach(p=>exactKeys(p,"time kind channel"));
    check(s.pulses.every((p,i)=>finite(p.time)&&p.time>=0&&p.time<=s.now&&(!i||p.time>=s.pulses[i-1].time)),"checkpoint pulse times");
    const seenCounts=s.regimes.map(()=>Array(n).fill(0)),expectedPulses=[];
    let eventState=null,traceValue=0,traceTime=0;
    for(let i=0;i<s.log.length;i++) {
      const r=s.log[i];
      check(r&&finite(r.time)&&r.time>=0&&r.time<=s.now&&(!i||r.time>=s.log[i-1].time)&&integer(r.budget)&&r.budget<=c.budgetCap,"checkpoint log time/budget");
      if(r.type==="jump") {
        exactKeys(r,"time type channel channelIndex from to rate regime spike budget");
        check(integer(r.channelIndex)&&r.channelIndex<n&&integer(r.regime)&&r.regime<s.regimes.length,"checkpoint jump indices");
        const h=c.channels[r.channelIndex];
        check(r.channel===h.id&&r.from===h.from&&r.to===h.to&&r.spike===h.spike&&r.rate>0&&r.rate===s.regimes[r.regime].rates[r.channelIndex],"checkpoint jump channel");
        seenCounts[r.regime][r.channelIndex]++;eventState=r.to;
      } else if(r.type==="deadline") {
        exactKeys(r,"time type due actions charge loss reward value spike budget");
        check(Array.isArray(r.due)&&r.due.length>0&&r.due.length<=8&&r.due.every(id=>s.obligations.some(o=>o.id===id)),"checkpoint deadline ids");
        check(typeof r.actions==="string"&&r.actions.length===r.due.length&&/^[DRE]+$/.test(r.actions)&&integer(r.charge)&&finite(r.loss)&&r.loss>=0&&finite(r.reward)&&finite(r.value),"checkpoint deadline action");
        check(typeof r.spike==="boolean"&&Number(r.spike)===[...r.actions].filter(a=>a==="E").length,"checkpoint deadline pulse");
        if(r.spike) eventState=c.resetState;
      } else if(r.type==="release") exactKeys(r,"time type budget");
      else {
        exactKeys(r,"time type seq budget regime");
        check(Object.hasOwn(priority,r.type)&&integer(r.seq)&&s.queue.some(e=>e.seq===r.seq&&e.type===r.type&&e.time===r.time),"checkpoint external record");
        check(integer(r.regime)&&r.regime<s.regimes.length,"checkpoint regime record");
      }
      if(r.spike) {
        expectedPulses.push({time:r.time,kind:r.type,channel:r.channel===undefined?null:r.channel});
        traceValue=traceValue*Math.exp(-(r.time-traceTime)/c.traceTau)+1;traceTime=r.time;
      }
    }
    check(expectedPulses.length===s.pulses.length&&expectedPulses.every((p,i)=>
      p.time===s.pulses[i].time&&p.kind===s.pulses[i].kind&&p.channel===s.pulses[i].channel)&&
      s.ledger.spentPulse===s.spikeCount*c.pulseDebit,"checkpoint pulse accounting");
    check(s.trace.value===traceValue&&s.trace.time===traceTime&&(eventState===null||eventState===s.stateIndex),"checkpoint trace/state");
    check(s.regimes.every((r,i)=>JSON.stringify(r.counts)===JSON.stringify(seenCounts[i])),"checkpoint event counts");
    const last=s.regimes[s.regimes.length-1];
    check(last.end===s.clock.at&&last.start<=s.clock.at&&s.regimes.every((r,i)=>!i||r.start===s.regimes[i-1].end),"checkpoint regime continuity");
    const blocked=s.refUntil!==null&&s.refUntil>s.clock.at;
    const rate=c.channels.reduce((a,h,j)=>a+(!blocked&&h.from===s.stateIndex&&(!h.spike||s.budget>=c.pulseDebit)?s.rates[j]:0),0);
    check(s.clock.remaining+1e-12*Math.max(1,s.clock.remaining)>=rate*(s.now-s.clock.at),"stale residual hazard");
    const runtime=engine(c,s,api,hooks),next=runtime.nextEventTime();
    check(next===null||next>=s.now,"checkpoint next event");return runtime;
  }
  return {create,restore,rngAlgorithm};
})();
if(typeof module!=="undefined") module.exports=RRMarkedEvents;
