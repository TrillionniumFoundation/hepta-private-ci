# Authorized external-system improvement and portable evolution

Scope: concrete implementation profile for the nine existing assimilation components and `ASM-0` through `ASM-4`. It grants no host enrollment, root privilege, uncontrolled propagation, production mutation or inherited acceptance.

## 1. One explicit target

Start with one owner-enrolled unprivileged service in an isolated Debian VM/rootfs. Freeze OS release,architecture,base-image digest,package/configuration digests,service name,allowed paths/endpoints,user identity and owner consent/expiry. A reachable open-source system is not automatically an authorized target.

The first capability boundary permits query_state,start,stop and propose_config for that one service. Config application is a distinct reversible authorized operation after validation; proposal alone never writes the live service. Root installs,APT source/key changes,kernel changes,device privileges and peer enrollment are excluded.

## 2. Discovery and typed adapter

Discovery is read-only and bounded by the enrolled scope. Record packages,unit/drop-in dependencies,sockets/D-Bus signatures,process/cgroup/namespace/mount identity,state roots,health and backup ownership by safe references. Do not copy secret files. Record truncation and unknown facts before analysis; absence from a partial inventory does not mean absence from the target.

Generated contracts define typed input/output,error,side effects,idempotency,precondition,timeout and trusted terminal observer. Inferred metadata remains a candidate. Native adapters use argument arrays and explicit environment,not untrusted shell interpolation. Bind canonical path and mount generation; defend against symlink and time-of-check/time-of-use escape through the host's approved descriptor-based path mechanism.

## 3. Concrete service experiment

Use a disposable non-production service whose external test client verifies a deterministic request/response contract. The independent client measures success,latency,error rate,restart behavior and state continuity. Freeze workloads and resource limits before candidate tuning. The generator may change only an admitted configuration field or owner-approved source patch in the sandbox.

Compare unchanged baseline with candidate using equal CPU/memory/workload and a disjoint confirmatory workload. Observe service readiness rather than process liveness. A systemd acceptance response is not proof that the business request succeeded. Start/stop with lost acknowledgement is reconciled against exact process/service generation,not blindly repeated.

## 4. Migration and rollback

A config candidate passes schema/static validation,behavior parity,resource ceilings,fault injection and independent evaluation before any bounded enrolled-host trial. Preserve package,configuration and business-data rollback points separately. Stop admission,drain requests,record a state watermark,stage the new config,validate,commit the intended route/generation,and test from an independent client.

After successor writes,rollback must preserve accepted deltas or use a qualified compatible forward recovery. Reinstalling an older package is not restoration of business state. Package install/remove/configure remain later distinct effect classes because maintainer scripts and partial configuration have their own failure paths.

The Debian Policy requires maintainer scripts to support idempotent recovery; that does not make every package transaction atomically reversible. Keep scripts inside the isolated test boundary until their precise effects and recovery are qualified. Reference: https://www.debian.org/doc/debian-policy/ch-maintainerscripts.html.

## 5. Portable evolution package

A portable package carries exact adapter/code/model hashes,source/build provenance,license/SBOM,compatible OS/service/ABI/semantic profiles,task objective class,evaluation data scope,tests,migration/rollback recipe,resource envelope,expiry and signatures. It contains no live credentials,consumable grants,enrollment,private raw training data or inherited operator acceptance.

Each destination independently checks compatibility,owner consent,scope,available resources,current revocations and local task distribution. A valid signature proves source integrity,not benefit on another host. Re-evaluate local behavior and support; transfer model/code/experience candidates,not authority. Distribution shift may require local fine-tuning or rejection. Disable on incompatible schema,missing rollback,uncertain ownership or unsupported effects.

## 6. Maturity and expansion

A0 read-only manifest; A1 dormant typed wrapper; A2 explicitly controlled reversible operations; A3 sandbox candidate improvement; A4 qualified bounded shadow/canary; A5 multiple independently enrolled hosts. Report host/service/adapter/body generation and boundary for each level. Never publish a single universal `Debian assimilated=true` flag.

Service-graph expansion requires explicit start/stop strategy for cycles,one writer per state domain and failure isolation. A host cannot autonomously enroll peers or copy credentials. Extensibility is an owner-authorized capability transfer mechanism,not autonomous contagion or a claim that arbitrary software becomes a learning algorithm merely by connecting.

## 7. Acceptance cases

Require successful discovery,typed query,authorized stop/start,configuration proposal,sandbox comparison,fault injection and exact restoration of one service with no root or production secrets. Negative cases include altered APT source,malicious maintainer script,D-Bus signature drift,path escape,hidden secret file,partial migration,reboot,acknowledgement loss,role collision,expired consent and unauthorized peer enrollment.

The generator,evaluator and target operator produce separate evidence. Repository fixtures and this documentation cannot satisfy external owner consent,real service/hardware qualification or production rollout decisions.
