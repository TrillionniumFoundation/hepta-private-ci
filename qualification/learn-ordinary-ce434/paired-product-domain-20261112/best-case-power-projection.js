// Static exact-BigInt projection of the pinned original Q32 confidence radius.
// This does not execute Rust, issue authority, alter a frozen plan or establish actual B efficacy.
(() => {
const Q = 1n << 32n;
function ceilDiv(a,b){return (a+b-1n)/b}
function isqrt(n){if(n<2n)return n;let x=1n<<BigInt(Math.ceil(n.toString(2).length/2));for(;;){const y=(x+n/x)>>1n;if(y>=x)return x;x=y;}}
function radius(range,L,n){const squares=ceilDiv(range*range*L*n,2n*n*n),f=isqrt(squares);return f+(f*f<squares?1n:0n)+8n}
function logUpper(alpha,m){const ratio=ceilDiv(6000000n*BigInt(m),BigInt(alpha));return BigInt((ratio-1n).toString(2).length)}
function cap(x){return x>Q?Q:x}
function calc(n,W,alpha,m){
 n=BigInt(n);W=BigInt(W);const L=logUpper(alpha,m),rw=radius(W*Q,L,n),rd=radius(Q+2n*W*Q+2n,L,n);
 const sL=rw>=Q?0n:cap(((Q-rw)*Q)/(Q+rw)),sU=rw>=Q?Q:cap(ceilDiv(rw*Q,Q-rw));
 return {pairs:Number(n),clusters:Number(n),weight_bound:Number(W),family_alpha_ppm:alpha,simultaneous_comparisons:m,log_upper:Number(L),
 ips:{radius_raw:String(rw),candidate_lower_raw:String(Q-rw),baseline_upper_raw:String(rw),best_improvement_raw:String(Q-2n*rw),strict_zero_margin:Q-2n*rw>0n},
 snips:{candidate_lower_raw:String(sL),baseline_upper_raw:String(sU),best_improvement_raw:String(sL-sU),strict_zero_margin:sL-sU>0n},
 doubly_robust:{range_raw:String(Q+2n*W*Q+2n),radius_raw:String(rd),candidate_lower_raw:String(Q-rd),baseline_upper_raw:String(rd),best_improvement_raw:String(Q-2n*rd),strict_zero_margin:Q-2n*rd>0n}};
}
return {
 rows: [[30,4,50000,1],[31,4,50000,1],[31,1,50000,1],[31,1,100000,1],[512,4,50000,1],[14,1,50000,1],[15,1,50000,1]].map(args => calc(...args)),
 minimum_pairs_with_existing_fixture_parameters: ["ips","snips","doubly_robust"].map(metric => {
   for (let n=2;n<=16384;n++) if (calc(n,4,50000,1)[metric].strict_zero_margin) return {metric,pairs:n};
   return {metric,pairs:null};
 })
};
})()
