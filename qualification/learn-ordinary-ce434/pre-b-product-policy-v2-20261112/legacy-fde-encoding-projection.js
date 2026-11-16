// Source-only reference projection of fixed FDE encoders; not a Rust test run.
export function originalFdePolicyVectors() {

const hash=(()=>{
return function sha256(text) {
 const bytes=Array.from(text);
 const n=bytes.length;bytes.push(128);while(bytes.length%64!==56)bytes.push(0);const hi=Math.floor(n/0x20000000),lo=(n<<3)>>>0;for(let i=3;i>=0;i--)bytes.push((hi>>>(8*i))&255);for(let i=3;i>=0;i--)bytes.push((lo>>>(8*i))&255);
 const K=[0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
 const H=[0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
 const rr=(v,s)=>(v>>>s)|(v<<(32-s));const w=new Array(64);
 for(let off=0;off<bytes.length;off+=64){for(let i=0;i<16;i++){let p=off+4*i;w[i]=((bytes[p]<<24)|(bytes[p+1]<<16)|(bytes[p+2]<<8)|bytes[p+3])>>>0;}for(let i=16;i<64;i++){let a=w[i-15],b=w[i-2];w[i]=(w[i-16]+(rr(a,7)^rr(a,18)^(a>>>3))+w[i-7]+(rr(b,17)^rr(b,19)^(b>>>10)))>>>0;}
 let[a,b,c,d,e,f,g,h]=H;for(let i=0;i<64;i++){const t1=(h+(rr(e,6)^rr(e,11)^rr(e,25))+((e&f)^(~e&g))+K[i]+w[i])>>>0;const t2=((rr(a,2)^rr(a,13)^rr(a,22))+((a&b)^(a&c)^(b&c)))>>>0;h=g;g=f;f=e;e=(d+t1)>>>0;d=c;c=b;b=a;a=(t1+t2)>>>0;}for(const[i,v]of[a,b,c,d,e,f,g,h].entries())H[i]=(H[i]+v)>>>0;}
 return H.map(x=>x.toString(16).padStart(8,"0")).join("");
}})();
const ascii=s=>Array.from(s,c=>c.charCodeAt(0));
const hex=h=>h.match(/../g).map(x=>parseInt(x,16));
const d=s=>hex(hash(ascii(s)));
function be(n,width){let x=BigInt(n);if(x<0)x+=(1n<<BigInt(width*8));return Array.from({length:width},(_,i)=>Number((x>>BigInt(8*(width-1-i)))&255n));}
const id=s=>[...be(s.length,4),...ascii(s)];
const ids=v=>[...be(v.length,4),...v.toSorted().flatMap(id)];
function temporal(name){
 const bytes=[...ascii("hepta.ope.temporal-evaluation-plan.v1"),...id(name),...d("policy-objective"),
 ...d(name+"-fold-plan"),...id(name+"-fold"),...be(10,8),...be(20,8),...be(2,8),
 ...d(name+"-ope"),...be(100,8),...be(2,8),...be(1n<<32n,8),...be(4n<<32n,8),
 ...d(name+"-confidence"),...d("original-cluster-assumptions"),...be(50000,4),...be(3,4),...be(2,8)];
 return {bytes,hash:hash(bytes)};
}
const candidate=temporal("candidate-eval"),baseline=temporal("baseline-eval");
const metrics=[["a-primary",0,null],["b-retention",1,1n<<32n],["c-absolute",0,0n]];
const roles=[["a-primary",0,0n],["b-retention",1,7n],["c-absolute",2,null]];
const sources=[["a-primary",0],["b-retention",1],["c-absolute",2]];
const mc=metrics.flatMap(([n,dir,f])=>[...id(n),dir,...(f===null?[0]:[1,...be(f,8)])]);
const rb=roles.flatMap(([n,tag,m])=>[...id(n),tag,...(m===null?[]:be(m,8))]);
const sb=sources.flatMap(([n,tag])=>[...id(n),tag]);
const legacyMetric=[...ascii("hepta.intelligence-eval.metric-contract.v1"),...be(metrics.length,4),...mc];
const roleBytes=[...ascii("hepta.intelligence-eval.metric-contract.v2"),...hex(hash(legacyMetric)),...rb];
function rawPlan(estimand){
 let bytes=[...ascii("hepta.intelligence-eval.cross-fold-plan.v2"),...id("policy-plan"),...id("actual-candidate"),...id("original-baseline"),...id("final-window"),0,
 ...d("policy-objective"),...d("actual-dataset"),...hex(estimand),...hex(hash(legacyMetric)),...d("actual-manifest"),...be(50000,4),...be(3,4),...be(2,4)];
 for(const [n,w] of [["fold-a","final-window"],["fold-b","other-window"]]){
 bytes.push(...id(n),...ids([n+"-train-z",n+"-train-a"]),...ids([n+"-train-episode"]),...ids([n+"-past"]),...ids([n+"-held-principal"]),...ids([n+"-held-episode"]),...ids([w]),...d(n+"-declared-model"),...d(n+"-declared-predictions"));
 }
 const raw=hash(bytes);
 const v2=hash([...ascii("hepta.intelligence-eval.cross-fold-plan.v3"),...hex(raw),...hex(hash(roleBytes))]);
 return {bytes,raw,v2};
}
const sharedEst=[...ascii("hepta.intelligence-eval.product-estimand.v1"),...d("actual-cell-estimand"),...hex(candidate.hash),...hex(baseline.hash),...sb];
const sharedRaw=rawPlan(hash(sharedEst));
const shared=[...ascii("hepta.intelligence-eval.product-frozen-plan.v1"),...hex(sharedRaw.v2),...hex(hash(roleBytes)),...d("actual-cell-estimand"),...hex(candidate.hash),...hex(baseline.hash),...mc,...rb,...sb];
let pair=[...ascii("hepta.intelligence-eval.on-policy-pair-contract.v1"),0,...be(2,4)];
for(let i=0;i<2;i++){
 pair.push(...id("pair-"+i),...d("input-"+i),...d("original-protocol"));
 for(const [name,tag] of [["candidate",0],["baseline",1]])pair.push(tag,...id(name+"-run-"+i),...id("original-principal-"+i),...id(name+"-episode-"+i),...id(name+"-run-"+i),...d(name+"-model"));
}
const pairedEst=[...ascii("hepta.intelligence-eval.product-paired-on-policy-estimand.v1"),...d("actual-cell-estimand"),...hex(candidate.hash),...hex(baseline.hash),...hex(hash(pair)),...be(sources.length,4),...sb];
const pairedRaw=rawPlan(hash(pairedEst));
const paired=[...ascii("hepta.intelligence-eval.product-frozen-paired-on-policy.v1"),...hex(pairedRaw.v2),...hex(hash(roleBytes)),...d("actual-cell-estimand"),...hex(candidate.hash),...hex(baseline.hash),...be(pair.length,4),...pair,...be(metrics.length,4),...mc,...be(roles.length,4),...rb,...be(sources.length,4),...sb];
return {candidate: candidate.hash,baseline:baseline.hash,legacyMetric:hash(legacyMetric),roles:hash(roleBytes),shared:{plan:hash(shared),estimand:hash(sharedEst),raw:sharedRaw.raw,rolePlan:sharedRaw.v2,bytes:shared.length},paired:{plan:hash(paired),estimand:hash(pairedEst),raw:pairedRaw.raw,rolePlan:pairedRaw.v2,bytes:paired.length},pair:hash(pair)};

}
