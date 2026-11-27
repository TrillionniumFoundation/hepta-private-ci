"use strict";
/* Objective audit of the existing diagnostic, not an R4 architecture benchmark. */
function auditRRDiagnosticUtility(N,M,C) {
  const check=(ok,msg)=>{if(!ok)throw new Error(msg);};
  const pop=x=>{let n=0;while(x){n+=x&1;x>>>=1;}return n;};
  let decisionCases=0;
  for(let budget=0;budget<=8;budget++)for(const evidence of [0,1])
    for(const due of [1,2])for(let retained=0;retained<=2;retained++) {
      const out=C.deadlineChoices({budget,evidence,resetEvidence:0,
        legs:Array.from({length:due},()=>({renewDebit:1,emitDebit:2,
          renewLoss:.15,emitReward:.4*evidence})),
        continuation:next=>.2*next.budget+1.2*(retained+pop(next.renewedMask))});
      check(!out.best.actions.includes("E"),"unexpected profitable deadline emit");
      check(pop(out.best.next.renewedMask)===Math.min(budget,due),
        "deadline proxy does not greedily renew feasible obligations");
      decisionCases++;
    }
  function zeroControl(seed,scenario) {
    const units=[0,1].map(i=>{
      const config={identity:"rr-utility-audit-zero:unit"+i,evidence:[0,1],
        channels:[{id:"up",from:0,to:1,rate:3,spike:false},
          {id:"pulse",from:1,to:0,rate:0,spike:true}],
        resetState:0,refractory:.05,traceTau:.6,pulseDebit:1,
        budgetCap:8,horizon:4,maxRecords:20000};
      return M.create(config,{stateIndex:0,budget:6,
        seed:(seed^(i?0x9e3779b9:0))>>>0,
        obligations:scenario.maturity.map((deadline,j)=>({id:"memory"+j,
          deadline,renewDebit:1,renewLoss:.15,emitDebit:1,emitValue:.4,status:"live"})),
        events:[{time:0,type:"input",data:[0,0]},
          ...[.5,1.5,2.5,3.5].map((time,j)=>({time,type:"input",
            data:[j%2===0?.5:-.5,0]})),
          {time:1.5,type:"shock",amount:scenario.shock},
          {time:2.5,type:"refill",amount:1}]},C,{
        input:()=>[3,0],
        continuation:post=>.2*post.budget+
          1.2*post.obligations.filter(o=>o.status==="retained").length});
    });
    return N.coordinate(units,[{from:0,to:1,delay:.1},{from:1,to:0,delay:.15}],
      (_edge,_item,time)=>({time,type:"input",data:[0,1]}),
      {identity:"rr-utility-audit-zero",horizon:4,maxSteps:10000});
  }
  const cases=[];
  for(const maturity of [[1,3],[2,2]])for(const shock of [0,2]) {
    const net=zeroControl(9010,{maturity,shock});net.runUntil(4);
    const cp=net.snapshot(),obs=net.observe();
    const retained=obs.units.reduce((sum,u)=>sum+
      u.obligations.filter(o=>o.status==="retained").length,0);
    const budget=obs.units.reduce((sum,u)=>sum+u.budget,0);
    const emitted=cp.units.reduce((sum,u)=>sum+u.state.utility.emitted,0);
    const loss=cp.units.reduce((sum,u)=>sum+u.state.utility.loss,0);
    const score=.2*budget+1.2*retained+emitted-loss,upper=6.2-.4*shock;
    check(net.pulses().length===0&&retained===4,"zero-control ledger");
    check(budget===10-2*shock&&Math.abs(score-upper)<1e-12,"zero-control certificate");
    cases.push({maturity,shock,physicalPulses:0,retained,terminalTotalBudget:budget,
      score,theoreticalUpper:upper});
  }
  return {schema:"rr-diagnostic-objective-audit-1",decisionCases,cases,
    impliedScore:".2 * final total budget + 1.2 * retained count + emitted reward - renewal loss",
    algebra:{
      renewalIncrement:.85,deadlineEmitIncrementUpper:0,
      perUnitScore:".2 * (6 + added - removed - ordinaryPulses - retained) + 1.05 * retained",
      perUnitUpper:"3.1 - .2 * shock",twoUnitUpper:"6.2 - .4 * shock",
      gapIdentityPerUnit:".2 * ((1-added)+(removed+ordinaryPulses-shock)) + .85*(2-retained)",
      integerScaledGap:"20*(Uzero-U) = 4*((1-added)+(removed+ordinaryPulses-shock)) + 17*(2-retained)",
      bounds:["added<=1","retained<=2","removed+ordinaryPulses>=shock",
        "if ordinaryPulses>=1 then removed+ordinaryPulses>=shock+1"],
      assumptions:["complete nonaborted trajectories of the fixed diagnostic",
        "same two obligations per unit; costs and events fixed as diagnostic",
        "shock is 0 or 2 at 1.5; refill is 1 at 2.5; budget starts at 6",
        "deadline policy uses the unchanged .2 budget +1.2 retained continuation",
        "ordinary physical pulses have no task reward in this implied additive score"],
      strictLossIfAnyOrdinaryPulseAtLeast:.2},
    scope:{valueWeightedTask:false,matchedArchitectureBenchmark:false,
      registeredR4Utility:false,calibrationAcceptance:false,
      finiteDiagnosticDegeneracyEstablished:true,generalRRSNNImpossibility:false}};
}
if(typeof module!=="undefined")module.exports=auditRRDiagnosticUtility;
if(typeof require!=="undefined"&&require.main===module)
  console.log(JSON.stringify(auditRRDiagnosticUtility(require("./delayed_network.cjs"),
    require("./event_runtime.cjs"),require("./continuation_operator.cjs")),null,2));
