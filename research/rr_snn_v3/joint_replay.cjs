/* Versioned research-only replay contract. No filesystem or authority is implied. */
"use strict";
const RRJointReplay = (() => {
  const SCHEMA = "rrsnn.joint-checkpoint.v1";
  const JOURNAL = "rrsnn.reference-journal.v1";
  const ZERO = "0".repeat(64);
  const MAX_BYTES = 8 * 1024 * 1024;
  const fail = (message) => { throw new Error(message); };
  const check = (condition, message) => { if (!condition) fail(message); };
  const copy = (value) => JSON.parse(canonical(value));
  const same = (a, b) => canonical(a) === canonical(b);
  function exact(value, names, label) {
    check(value && typeof value === "object" && !Array.isArray(value), label + ": object");
    check(Object.keys(value).sort().join("|") === names.slice().sort().join("|"), label + ": fields");
  }
  function canonical(value) {
    let nodes = 0;
    function visit(x, depth) {
      check(++nodes <= 200000 && depth <= 48, "JSON bounds");
      if (x === null || typeof x === "boolean") return JSON.stringify(x);
      if (typeof x === "number") {
        check(Number.isFinite(x) && !Object.is(x, -0), "nonfinite or negative-zero number");
        return JSON.stringify(x);
      }
      if (typeof x === "string") {
        check(x.length <= MAX_BYTES && !/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(x), "string bounds/UTF16");
        return JSON.stringify(x);
      }
      check(x && typeof x === "object", "non-JSON value");
      if (Array.isArray(x)) {
        check(x.length <= 100000 && Reflect.ownKeys(x).length === x.length + 1 &&
          Object.keys(x).every((k,i)=>k===String(i)) && Object.keys(x).length===x.length, "sparse/hidden array");
        for(let i=0;i<x.length;i++) check(Object.hasOwn(Object.getOwnPropertyDescriptor(x,String(i)),"value"),"array accessor");
        return "[" + x.map(y => visit(y, depth + 1)).join(",") + "]";
      }
      check(Object.getPrototypeOf(x) === Object.prototype || Object.getPrototypeOf(x) === null, "nonplain object");
      const keys = Object.keys(x).sort();
      check(Reflect.ownKeys(x).length === keys.length, "hidden fields");
      for (const k of keys) check(!Object.getOwnPropertyDescriptor(x, k).get && !Object.getOwnPropertyDescriptor(x, k).set, "accessor");
      return "{" + keys.map(k => visit(k, depth + 1) + ":" + visit(x[k], depth + 1)).join(",") + "}";
    }
    const result = visit(value, 0);
    check(result.length <= MAX_BYTES, "JSON code-unit bound");
    return result;
  }
  // SHA-256 over UTF-8, implemented without Node/WebCrypto dependencies.
  function sha256(text) {
    check(typeof text === "string" && text.length <= MAX_BYTES &&
      !/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(text), "hash input bound/UTF16");
    const bytes = [];
    for (const char of text) {
      const p = char.codePointAt(0);
      if (p < 128) bytes.push(p);
      else if (p < 2048) bytes.push(192 | p >> 6, 128 | p & 63);
      else if (p < 65536) bytes.push(224 | p >> 12, 128 | p >> 6 & 63, 128 | p & 63);
      else bytes.push(240 | p >> 18, 128 | p >> 12 & 63, 128 | p >> 6 & 63, 128 | p & 63);
    }
    const length = bytes.length * 8;
    bytes.push(128);
    while (bytes.length % 64 !== 56) bytes.push(0);
    for (let i = 7; i >= 0; --i) bytes.push(i >= 4 ? 0 : length >>> (8 * i) & 255);
    const K = [0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
      0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
      0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
      0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
      0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
      0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
      0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
      0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
    const H = [0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
    const rotr = (x,n) => x >>> n | x << (32-n);
    for (let offset = 0; offset < bytes.length; offset += 64) {
      const w = new Uint32Array(64);
      for (let i=0;i<16;i++) w[i]=(bytes[offset+4*i]<<24)|(bytes[offset+4*i+1]<<16)|(bytes[offset+4*i+2]<<8)|bytes[offset+4*i+3];
      for (let i=16;i<64;i++) {
        const x=w[i-15],y=w[i-2];
        w[i]=(w[i-16]+(rotr(x,7)^rotr(x,18)^(x>>>3))+w[i-7]+(rotr(y,17)^rotr(y,19)^(y>>>10)))>>>0;
      }
      let [a,b,c,d,e,f,g,h]=H;
      for (let i=0;i<64;i++) {
        const t1=(h+(rotr(e,6)^rotr(e,11)^rotr(e,25))+((e&f)^(~e&g))+K[i]+w[i])>>>0;
        const t2=((rotr(a,2)^rotr(a,13)^rotr(a,22))+((a&b)^(a&c)^(b&c)))>>>0;
        [h,g,f,e,d,c,b,a]=[g,f,e,(d+t1)>>>0,c,b,a,(t1+t2)>>>0];
      }
      [a,b,c,d,e,f,g,h].forEach((v,i)=>H[i]=(H[i]+v)>>>0);
    }
    return H.map(x=>x.toString(16).padStart(8,"0")).join("");
  }
  const digest = (domain, value) => sha256(domain + "\0" + canonical(value));
  const hash = value => check(typeof value === "string" && /^[0-9a-f]{64}$/.test(value), "invalid digest");
  const integer = (x, min, max, label) => check(Number.isSafeInteger(x) && x>=min && x<=max, label);
  const number = (x, min, max, label) => check(typeof x==="number" && Number.isFinite(x) && x>=min && x<=max, label);
  const id = x => check(typeof x==="string" && /^[A-Za-z0-9._:/-]{1,128}$/.test(x), "invalid identity");
  function shape(cp) {
    canonical(cp);
    exact(cp,["schema","config","state"],"engine checkpoint");
    check(cp.schema==="rrsnn.marked-events.v1","engine profile");
    const c=cp.config,s=cp.state;
    exact(c,["identity","evidence","channels","resetState","refractory","traceTau","pulseDebit","budgetCap","horizon","maxRecords"],"config");
    id(c.identity);
    check(Array.isArray(c.evidence) && c.evidence.length>0 && c.evidence.length<=256,"evidence dimension");
    check(Array.isArray(c.channels) && c.channels.length<=4096,"channel dimension");
    const channelIds=new Set();
    for(const q of c.channels) {
      exact(q,["id","from","to","rate","spike"],"channel"); id(q.id);
      check(!channelIds.has(q.id),"duplicate channel"); channelIds.add(q.id);
      integer(q.from,0,c.evidence.length-1,"from"); integer(q.to,0,c.evidence.length-1,"to");
      number(q.rate,0,1e6,"rate"); check(typeof q.spike==="boolean","spike flag");
    }
    exact(s,["now","stateIndex","budget","refUntil","trace","spikeCount","rng","clock","rates","regimes",
      "obligations","queue","cursor","nextSeq","ledger","utility","log","pulses","aborted"],"state");
    number(s.now,0,c.horizon,"clock"); integer(s.stateIndex,0,c.evidence.length-1,"physical index");
    number(s.budget,0,c.budgetCap,"budget"); integer(s.spikeCount,0,1e9,"spike count");
    exact(s.trace,["time","value"],"trace");number(s.trace.time,0,s.now,"trace anchor");number(s.trace.value,0,1e12,"trace");
    exact(s.rng,["word","draws"],"RNG");integer(s.rng.word,0,0xffffffff,"RNG word");integer(s.rng.draws,0,Number.MAX_SAFE_INTEGER,"draw count");
    exact(s.clock,["at","remaining"],"hazard");number(s.clock.at,0,s.now,"hazard anchor");number(s.clock.remaining,0,1e12,"residual hazard");
    if(s.refUntil!==null) number(s.refUntil,s.now,1e12,"refractory clock");
    check(s.aborted===false,"aborted engine");
    check(Array.isArray(s.rates)&&s.rates.length===c.channels.length,"held rates");
    s.rates.forEach(x=>number(x,0,1e6,"held rate"));
    const bounds={regimes:c.maxRecords+1,obligations:8,queue:4096,log:c.maxRecords,pulses:c.maxRecords};
    for(const [name,bound] of Object.entries(bounds)) check(Array.isArray(s[name])&&s[name].length<=bound,name+" bounds");
    for(const r of s.regimes) {
      exact(r,["id","start","end","rates","exposure","counts"],"regime");
      check(r.rates.length===c.channels.length&&r.exposure.length===c.channels.length&&r.counts.length===c.channels.length,"regime dimensions");
    }
    const obligationIds=new Set();
    for(const o of s.obligations) {
      exact(o,["id","deadline","renewDebit","renewLoss","emitDebit","emitValue","status"],"obligation");id(o.id);
      check(!obligationIds.has(o.id),"duplicate obligation");obligationIds.add(o.id);
      check(["live","retained","resolved"].includes(o.status),"obligation status");
      for(const n of ["deadline","renewDebit","renewLoss","emitDebit","emitValue"]) number(o[n],0,1e12,"obligation "+n);
    }
    const seqs=new Set();let previous=-1;
    for(const e of s.queue) {
      const field={input:"data",control:"rates",shock:"amount",refill:"amount"}[e.type];
      check(field,"event type"); exact(e,["time","type","seq",field],"event");
      number(e.time,0,c.horizon,"input time");check(e.time>=previous,"event ordering");previous=e.time;
      integer(e.seq,0,Number.MAX_SAFE_INTEGER,"event sequence");check(!seqs.has(e.seq),"duplicate event");seqs.add(e.seq);
    }
    integer(s.cursor,0,s.queue.length,"input cursor");integer(s.nextSeq,0,Number.MAX_SAFE_INTEGER,"next input sequence");
    exact(s.ledger,["initial","spentPulse","spentDeadline","removed","added"],"ledger");
    Object.values(s.ledger).forEach(x=>number(x,0,1e12,"ledger value"));
    const l=s.ledger, balance=l.initial-l.spentPulse-l.spentDeadline-l.removed+l.added;
    check(Math.abs(balance-s.budget)<=1e-10*(1+Math.abs(balance)),"ledger conservation");
    exact(s.utility,["emitted","loss"],"utility");
    const logKeys={jump:"time type channel channelIndex from to rate regime spike budget",
      deadline:"time type due actions charge loss reward value spike budget",release:"time type budget",
      shock:"time type seq budget regime",refill:"time type seq budget regime",
      control:"time type seq budget regime",input:"time type seq budget regime"};
    for(const row of s.log) {
      check(Object.hasOwn(logKeys,row.type),"log type");exact(row,logKeys[row.type].split(" "),"log record");
    }
    for(const p of s.pulses) exact(p,["time","kind","channel"],"pulse");
    check(s.pulses.length===s.spikeCount,"pulse count");
  }
  function bind(options) {
    exact(options,["Engine","Continuation","hooks","config","initial","sourceHashes","model"],"adapter options");
    const {Engine,Continuation,hooks}=options,config=copy(options.config),initial=copy(options.initial);
    exact(options.sourceHashes,["engine","continuation","adapter"],"source hashes");
    Object.values(options.sourceHashes).forEach(hash);
    const binding={source:copy(options.sourceHashes),model:digest("rrsnn.model.v1",options.model),
      config:digest("rrsnn.config.v1",config),inputs:digest("rrsnn.initial-inputs.v1",initial),identity:config.identity};
    function pack(snapshot,sequence,predecessor) {
      integer(sequence,0,1024,"journal sequence");hash(predecessor);
      check((sequence===0)===(predecessor===ZERO),"predecessor profile");
      shape(snapshot); check(same(snapshot.config,config),"config identity drift");
      check(same(snapshot.state.queue,initialSnapshot.state.queue)&&snapshot.state.nextSeq===initialSnapshot.state.nextSeq,"fixed input plan changed");
      const payload={binding,sequence,predecessor,time:snapshot.state.now,inputCursor:snapshot.state.cursor,
        nextInputSequence:snapshot.state.nextSeq,snapshot};
      return {schema:SCHEMA,authority:"none",payload:copy(payload),digest:digest(SCHEMA,payload)};
    }
    function unpack(envelope,expectedDigest) {
      canonical(envelope);exact(envelope,["schema","authority","payload","digest"],"envelope");
      check(envelope.schema===SCHEMA&&envelope.authority==="none","envelope profile/authority");
      hash(envelope.digest); if(expectedDigest!==undefined) check(envelope.digest===expectedDigest,"external digest mismatch");
      const p=envelope.payload;
      exact(p,["binding","sequence","predecessor","time","inputCursor","nextInputSequence","snapshot"],"payload");
      check(same(p.binding,binding),"source/model/config/input identity mismatch");
      check(digest(SCHEMA,p)===envelope.digest,"checksum mismatch");
      integer(p.sequence,0,1024,"journal sequence");hash(p.predecessor);
      check((p.sequence===0)===(p.predecessor===ZERO),"predecessor profile");
      shape(p.snapshot);
      check(same(p.snapshot.state.queue,initialSnapshot.state.queue)&&p.snapshot.state.nextSeq===initialSnapshot.state.nextSeq,"fixed input plan changed");
      check(same(p.snapshot.config,config)&&p.time===p.snapshot.state.now&&p.inputCursor===p.snapshot.state.cursor&&p.nextInputSequence===p.snapshot.state.nextSeq,"input frontier mismatch");
      // The real engine validates its own semantics; its complete state is retained.
      const runtime=Engine.restore(copy(p.snapshot),Continuation,hooks,config.identity);
      check(same(runtime.snapshot(),p.snapshot),"engine restore changed state");
      return runtime;
    }
    const initialSnapshot=Engine.create(config,initial,Continuation,hooks).snapshot();
    const genesis=pack(initialSnapshot,0,ZERO);
    return {genesis:copy(genesis),binding:copy(binding),unpack,
      next(envelope,time) {
        number(time,envelope.payload.time,config.horizon,"stale/invalid time");
        const engine=unpack(envelope);engine.runUntil(time);
        return pack(engine.snapshot(),envelope.payload.sequence+1,envelope.digest);
      }};
  }
  function anchor(cp) { return {sequence:cp.payload.sequence,digest:cp.digest}; }
  function validateAnchor(a) { exact(a,["sequence","digest"],"anchor");integer(a.sequence,0,1024,"anchor sequence");hash(a.digest); }
  class MemoryJournal {
    constructor(genesis,limit=64) {
      integer(limit,1,1024,"journal limit");
      this.data={schema:JOURNAL,genesis:copy(genesis),limit,frames:[],tail:null,fence:{generation:0,owner:null}};
    }
    static from(image) { const j=Object.create(MemoryJournal.prototype);j.data=copy(image);return j; }
    image() { return copy(this.data); }
    claim(owner,expectedGeneration) {
      id(owner);check(this.data.fence.generation===expectedGeneration,"fence CAS conflict");
      this.data.fence={generation:expectedGeneration+1,owner};return this.data.fence.generation;
    }
  }
  class MemoryWitness {
    constructor(scope,current) { hash(scope);validateAnchor(current);this.data={schema:"rrsnn.reference-witness.v1",scope,current:copy(current)}; }
    static from(image) { const w=Object.create(MemoryWitness.prototype);w.data=copy(image);return w; }
    image() { return copy(this.data); }
    cas(expected,next) {
      validateAnchor(expected);validateAnchor(next);check(same(this.data.current,expected),"witness CAS conflict");
      check(next.sequence>expected.sequence || same(next,expected),"witness cannot roll back or fork");
      this.data.current=copy(next);
    }
  }
  function frameDigest(frame) { const {digest:ignored,...body}=frame;return digest("rrsnn.journal-frame.v1",body); }
  function open(adapter,journal,witness,lease,minimum) {
    exact(lease,["owner","generation"],"lease");id(lease.owner);integer(lease.generation,1,1e9,"fence generation");
    validateAnchor(minimum);
    const d=journal.data,w=witness.data;
    canonical(d);canonical(w);
    exact(d,["schema","genesis","limit","frames","tail","fence"],"journal image");
    exact(w,["schema","scope","current"],"witness image");validateAnchor(w.current);
    check(d.schema===JOURNAL&&w.schema==="rrsnn.reference-witness.v1","store schema");
    exact(d.fence,["owner","generation"],"fence");
    check(same(d.fence,lease),"stale writer fence");
    check(same(d.genesis,adapter.genesis)&&w.scope===d.genesis.digest,"store identity");
    integer(d.limit,1,1024,"journal capacity");check(d.frames.length<=d.limit,"journal full image");
    let head=d.genesis; const chain=[anchor(head)];
    for(const frame of d.frames) {
      exact(frame,["expected","request","checkpoint","digest"],"journal frame");
      exact(frame.request,["sequence","time"],"request");validateAnchor(frame.expected);
      check(same(frame.expected,anchor(head))&&frame.request.sequence===head.payload.sequence+1,"journal lineage");
      check(frameDigest(frame)===frame.digest,"journal frame checksum");
      const expected=adapter.next(head,frame.request.time);
      check(same(expected,frame.checkpoint),"deterministic replay mismatch");
      head=frame.checkpoint;chain.push(anchor(head));
    }
    check(chain[minimum.sequence]&&same(chain[minimum.sequence],minimum),"acknowledged rollback");
    check(chain[w.current.sequence]&&same(chain[w.current.sequence],w.current),"witness history missing");
    check(w.current.sequence>=minimum.sequence,"witness below independent minimum");
    if(d.tail!==null) { exact(d.tail,["incomplete","prefix"],"tail");check(d.tail.incomplete===true&&typeof d.tail.prefix==="string"&&d.tail.prefix.length<4096,"bad tail");d.tail=null; }
    if(!same(w.current,anchor(head))) witness.cas(w.current,anchor(head));
    let published=copy(head),poisoned=false;
    const fenced=()=>{check(!poisoned,"poisoned owner: reopen required");check(same(journal.data.fence,lease),"stale writer fence");};
    return {
      current:()=>copy(published),
      commit(expected,request,fault="none") {
        fenced();validateAnchor(expected);exact(request,["sequence","time"],"request");
        integer(request.sequence,1,1024,"request sequence");number(request.time,0,1e12,"request time");
        check(["none","before_append","torn_tail","after_append","after_witness"].includes(fault),"unknown fault point");
        const retry=d.frames[request.sequence-1];
        if(retry) {
          check(same(retry.expected,expected)&&same(retry.request,request),"stale/changed tick");
          return copy(retry.checkpoint);
        }
        check(same(expected,anchor(published))&&request.sequence===published.payload.sequence+1,"stale head/sequence");
        check(d.frames.length<d.limit,"journal capacity");
        const next=adapter.next(published,request.time);
        const frame={expected:copy(expected),request:copy(request),checkpoint:next};
        frame.digest=frameDigest(frame);canonical({...d,frames:[...d.frames,frame]});
        const crash=()=>{poisoned=true;fail("simulated crash: "+fault);};
        if(fault==="before_append") crash();
        if(fault==="torn_tail") {d.tail={incomplete:true,prefix:canonical(frame).slice(0,127)};crash();}
        d.frames.push(copy(frame));
        if(fault==="after_append") crash();
        try { witness.cas(expected,anchor(next)); } catch(error) {poisoned=true;throw error;}
        if(fault==="after_witness") crash();
        published=copy(next);return copy(next);
      }
    };
  }
  return {SCHEMA,canonical,sha256,digest,bind,shape,anchor,MemoryJournal,MemoryWitness,open};
})();
if(typeof module!=="undefined") module.exports=RRJointReplay;
