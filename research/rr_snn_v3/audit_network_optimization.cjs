"use strict";
/*
 * Train-only audit of the already frozen fit. No fitting, heldout paths, or
 * free-generation outcomes are read. Bounds use strong convexity of the
 * regularized complete-path objective, not a calibration acceptance margin.
 */
function auditRRNetworkOptimization(N,M,C,archive,protocol) {
  const check=(ok,message)=>{if(!ok)throw new Error(message);};
  const lambda=protocol.optimizer.l2, p=5;
  check(Number.isFinite(lambda)&&lambda>0,"positive regularizer required");
  check(protocol.data.train.episodes===128&&
    JSON.stringify(protocol.data.train.seeds)===JSON.stringify([10000,10127])&&
    protocol.data.horizon===4,"frozen training protocol mismatch");
  check(JSON.stringify(archive.teacherWeights)===JSON.stringify(protocol.teacherWeights),
    "teacher identity mismatch");
  check(archive.learnedWeights.length===2&&archive.optimizer.length===2,
    "two-unit archive required");
  const records=[[],[]],count=protocol.data.train.episodes;
  for(let seed=protocol.data.train.seeds[0];seed<=protocol.data.train.seeds[1];seed++) {
    const net=N.diagnostic(M,C,protocol.teacherWeights,seed);
    net.runUntil(protocol.data.horizon);
    net.records().forEach((rows,i)=>records[i].push(...rows));
  }
  const units=archive.learnedWeights.map((theta,i)=>{
    check(theta.length===p&&theta.every(Number.isFinite),"invalid frozen weights");
    const current=N.likelihood(theta,records[i],lambda);
    const unregularized=N.likelihood(theta,records[i],0);
    let low=Infinity,high=-Infinity;
    const hessian=Array.from({length:p},(_,j)=>
      Array.from({length:p},(_,k)=>j===k?lambda:0));
    for(const r of records[i]) {
      check(r.exposure>=0&&Number.isFinite(r.exposure)&&
        r.features.length===p&&r.features.every(Number.isFinite),
        "invalid training design or exposure");
      const z=theta.reduce((s,w,j)=>s+w*r.features[j],0);
      low=Math.min(low,z);high=Math.max(high,z);
      const weight=r.exposure*Math.exp(z);
      for(let j=0;j<p;j++)for(let k=0;k<p;k++)
        hessian[j][k]+=weight*r.features[j]*r.features[k];
    }
    check(low>=-40&&high<=40,"frozen fit outside declared log-rate domain");
    const gradientArchiveMaxDiff=Math.max(...current.gradient.map((g,j)=>
      Math.abs(g-archive.optimizer[i].finalGradient[j])));
    check(gradientArchiveMaxDiff<=1e-12,"archived gradient not reproduced");
    const expectedPenalty=.5*lambda*theta.reduce((s,w)=>s+w*w,0);
    check(Math.abs(current.loss-unregularized.loss-expectedPenalty)<=1e-10&&
      current.gradient.every((g,j)=>
        Math.abs(g-unregularized.gradient[j]-lambda*theta[j])<=1e-10),
      "regularization must be applied once per vector");
    const normSquared=current.gradient.reduce((s,g)=>s+g*g,0);
    check(hessian.flat().every(Number.isFinite)&&Number.isFinite(normSquared),
      "nonfinite train-only certificate");
    return {unit:i,records:records[i].length,
      regularizedPulseNll:current.loss,gradient:current.gradient,
      gradientL2:Math.sqrt(normSquared),
      gradientLInfinity:Math.max(...current.gradient.map(Math.abs)),
      gradientArchiveMaxDiff,logRateRange:[low,high],hessian,
      strongConvexityLowerBound:lambda,
      objectiveGapUpperBound:normSquared/(2*lambda),
      objectiveGapUpperBoundPerTrainingEpisode:normSquared/(2*lambda*count),
      parameterL2DistanceUpperBound:Math.sqrt(normSquared)/lambda};
  });
  return {schema:"rr-snn-frozen-fit-optimization-audit-1",
    training:{episodes:count,seeds:protocol.data.train.seeds,horizon:4},
    objective:{regularization:lambda,appliedOncePerNeuronVector:true,
      fixedUpChannelConstantsCancel:true,
      optimizerGradientDivisionByRecordCountDoesNotChangeMinimizer:true},
    geometry:{
      objective:"lambda/2 * ||theta||^2 + sum(E_r * exp(f_r.theta) - N_r * f_r.theta)",
      hessian:"lambda * I + sum(E_r * exp(f_r.theta) * f_r * f_r^T)",
      domain:"intersection of the closed slabs -40 <= f_r.theta <= 40",
      strongConvexity:"E_r >= 0 and lambda > 0 imply Hessian >= lambda * I",
      objectiveBound:"F(theta)-F*_D <= ||gradient F(theta)||^2/(2*lambda)",
      parameterBound:"||theta-theta*_D|| <= ||gradient F(theta)||/lambda",
      appliesToConstrainedOptimum:true,
      floatingPointQualification:"Computed gradients and bounds use Float64; this is not a directed-rounding interval certificate."
    },
    units,
    scope:{trainOnly:true,refitted:false,heldoutUsed:false,
      freeGenerationUsed:false,modelOrProtocolChanged:false,
      calibrationPassed:null,utilitySuperiorityEstablished:false}
  };
}
if(typeof module!=="undefined")module.exports=auditRRNetworkOptimization;
if(typeof require!=="undefined"&&require.main===module)
  console.log(JSON.stringify(auditRRNetworkOptimization(
    require("./delayed_network.cjs"),require("./event_runtime.cjs"),
    require("./continuation_operator.cjs"),require("./network_learning_results.json"),
    require("./network_learning_protocol.json")),null,2));
