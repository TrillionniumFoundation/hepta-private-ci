//! Ordinary CLI -> real accepted Chain task -> signed Supervisor -> next Agentd.
//! This retained development study never alters the default authority build or
//! the original service/sandbox timeouts, and retains failure before cleanup.
use super::*;
use anyhow::{Context, Result, ensure};
use app_test_support::MockResponsesConfig;
use codex_hepta_automation::AutomationStore;
use codex_hepta_fleet::ReleaseId;
use codex_hepta_intelligence_eval as eval;
use codex_hepta_supervisor::SupervisordClient;
use core_test_support::responses;
use ordinary::QualificationMode;
use ordinary_native::{Binary, Chain, Daemon};
use std::time::{Duration, Instant};

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "explicit retained real Supervisor/Agentd/Chain ordinary upgrade, future observation and no-update"]
async fn actual_ordinary_cli_chain_task_supervisor_upgrade_and_no_update() -> Result<()> {
    let root=PathBuf::from(std::env::var("HEPTA_LEARNING_STUDY_DIRECTORY")?);
    std::fs::create_dir(&root)?;let root=root.canonicalize()?;
    let script=PathBuf::from(std::env::var("HEPTA_LEARNING_CUSTODIAN")?);
    let mut host=Host::new(&root).await;
    let actions=host.seed().await;
    let mut roles=Roles::new(&script,&root);
    let operations:Vec<_>=actions.iter().map(|(_,operation)|operation.clone()).collect();
    let material_keys=json!({"evaluator":support::hex(&roles.processes[1].key),"future-custodian":support::hex(&roles.processes[6].key)});
    let observer_key=support::hex(&roles.processes[2].key);
    for role in &mut roles.processes {role.call(json!({"command":"configure","operations":operations,"material_keys":material_keys,"observer_key":observer_key}));}
    let view=Arc::new(publication::StudyView::new(root.join("artifact-owner"),&mut roles));
    let file=std::fs::OpenOptions::new().read(true).write(true).create_new(true).open(root.join("holdouts"))?;
    let store=eval::LockedFileFinalHoldoutCasStoreV1::create(file,hash("three-generation-holdouts"))?;
    let original=eval::FencedFinalHoldoutOwnerV1::initialize(store,hash("three-generation-holdouts"),holdout_fence())?;
    let mut runner=eval::ProductEvaluationRunnerV1::new(original);
    let baseline=root.join("generation-0");std::fs::create_dir(&baseline)?;
    let mut source_fit=fit(&baseline,0,&mut roles,&actions);
    let mut source=view.publish(&baseline,&source_fit,None,&mut roles);
    let mut source_selection=None;
    // Existing canonical history prepares an eligible source release. No
    // service generation is counted until Supervisord actually launches it.
    for generation in 1..=2 {
        let directory=root.join(format!("generation-{generation}"));std::fs::create_dir(&directory)?;
        let candidate=fit(&directory,generation,&mut roles,&actions);
        let published=view.publish(&directory,&candidate,Some(&source.selected.manifest),&mut roles);
        host.prove_candidate_withdrawal(&directory,&candidate,&mut roles).await;
        let (selection,_)=admission::evaluate(&directory,generation,&format!("generation-{generation}"),&candidate,&source.selected.manifest,
            &admission::choices(&candidate,&actions),&admission::choices(&source_fit,&actions),&mut roles,&mut runner)?;
        source_selection=Some(selection);source_fit=candidate;source=published;
    }
    let source_choices=admission::choices(&source_fit,&actions);
    let ranker=PinnedCognitiveRanker::load_evaluated_published(owner(),5,File::open(&source.snapshot)?,File::open(&source.payload)?,
        source.selected.clone(),source_fit.pin.clone(),source.source.clone(),view.clone(),source_selection.as_ref().context("source qualification")?)
        .map_err(anyhow::Error::msg)?;
    let expected_source=ranker.readback().map_err(anyhow::Error::msg)?;
    let anchor=runner.holdout_anchor();drop(runner);drop(ranker);
    let target_root=root.join("generation-3");std::fs::create_dir(&target_root)?;
    let target_fit=fit(&target_root,3,&mut roles,&actions);
    let target=view.publish(&target_root,&target_fit,Some(&source.selected.manifest),&mut roles);
    host.prove_candidate_withdrawal(&target_root,&target_fit,&mut roles).await;
    let target_choices=admission::choices(&target_fit,&actions);
    let selected=ordinary::qualify(&target_root,&host,3,&target_fit,&source,&expected_source,&mut roles,
        &target_choices,&source_choices,anchor,"ordinary-source",QualificationMode::Select).await;
    ensure!(selected["selection"]["state"]=="selected","ordinary target did not obtain original selector admission");
    let anchor:eval::FinalHoldoutCasAnchorV1=serde_json::from_value::<crate::cognitive_process_product_wire::FinalHoldoutCasAnchorV1Raw>(selected["holdout_anchor"].clone())?.into();
    let source_descriptor=process::descriptor(&root,&source,&source_fit,&view,5,anchor);
    let target_descriptor=process::descriptor(&root,&target,&target_fit,&view,9,anchor);
    let node=Binary::pinned("HEPTA_PON_NODE_BINARY")?;
    let fixture_binary=Binary::pinned("HEPTA_PON_TASK_FIXTURE_BINARY")?;
    let genesis=support::micros()/1_000_000-3600;
    let node_directory=root.join("chain");
    let host_file=ordinary_native::host_file(&root,&node,&node_directory.join("node"),genesis)?;
    let agentd=codex_utils_cargo_bin::cargo_bin("codex-hepta-agentd")?;
    let source_release=ReleaseId::parse("ordinary-source")?;
    let target_release=ReleaseId::parse("ordinary-target")?;
    for (release,(descriptor,digest)) in [(&source_release,&source_descriptor),(&target_release,&target_descriptor)] {
        host.fleet.install_release(release.clone(),&agentd,vec!["--cognitive-bootstrap-descriptor".to_owned(),descriptor.display().to_string(),
            "--cognitive-bootstrap-descriptor-digest".to_owned(),digest.to_string(),"--automation-effect-host-file".to_owned(),host_file.display().to_string()])?;
        host.fleet.allow_release(&owner(),release)?;
    }
    save(&root.join("native-agentd-build.json"),&json!({"binary":agentd,"binary_sha256":Digest32::of_bytes(&std::fs::read(&agentd)?).to_string(),
        "source_release":source_release,"target_release":target_release,"source_descriptor":source_descriptor.0,"target_descriptor":target_descriptor.0}));
    let input=json!({"agent_id":owner(),"source_release":source_release,"target_release":target_release,"spawn_generation":9,
        "descriptor_path":target_descriptor.0,"descriptor_sha256":target_descriptor.1.to_string()});
    let (success,inspection)=ordinary::cli(&root,"09-inspect",&host.fleet_path,"inspect",&input);
    ensure!(success,"ordinary target inspection failed: {inspection}");
    let commitment:crate::CognitiveUpgradeCommitmentV1=serde_json::from_value(inspection["commitment"].clone())?;
    let fixture=fixture_binary.run(&root,"task-prepare",&["prepare".to_owned(),node_directory.display().to_string(),genesis.to_string(),
        "authenticated-v1".to_owned(),commitment.output_sha256()?.to_string()])?;
    ensure!(fixture["acceptance_submitted"]==false,"fixture must leave exact acceptance to actual Agentd");
    let chain=Chain{binary:node,genesis,store:node_directory.join("node"),fixture};
    // Only the initial historical fixture transitions use the registry. Every
    // source/target service transition below goes through actual Supervisord.
    host.running();
    host.fleet.compare_and_transition(&owner(),2,AgentLifecycle::Draining)?;
    host.fleet.compare_and_transition(&owner(),3,AgentLifecycle::Stopped)?;
    host.launch=5;
    let model=responses::start_mock_server().await;
    MockResponsesConfig::new(&model.uri()).write(host.layout.home_root())?;
    let daemon=Daemon::start(&root,&host).await?;
    let socket=host.fleet.layout().supervisor_socket().to_path_buf();
    let owned_root=root.clone();
    let local=tokio::task::LocalSet::new();
    // A failed assertion in concrete role/owner helpers still returns through
    // this JoinHandle so cleanup uses the original Supervisor, never /proc.
    let outcome=local.run_until(local.spawn_local(async move {
        let client=SupervisordClient::new(socket)?;
        let status=client.snapshot(owner()).await?;
        client.start(status.control_fence,source_release.clone()).await?;
        let ready=ordinary_native::running(&client,&source_release,5).await?;
        save(&owned_root.join("source-service-status.json"),&serde_json::to_value(ready)?);
        let source_agent=crate::AgentdClient::new(host.layout.agentd_control_socket().to_path_buf(),owner(),5)?;
        let actual_source=source_agent.cognitive_model_status().await?.installed.context("real source ranker")?;
        ensure!(actual_source==expected_source,"actual source differs from evaluated predecessor");
        let plan=ordinary_native::plan(&client,&chain,commitment).await?;
        let wire=serde_json::to_value(&plan)?;
        let begin=Instant::now();
        let (success,awaiting)=ordinary::cli(&owned_root,"10-submit",&host.fleet_path,"advance",&wire);
        ensure!(success && awaiting["state"]=="awaiting_chain","exact acceptance should await original depth: {awaiting}");
        let original=AutomationStore::open(&host.layout).await?;
        let before=original.authorized_taskflow_effect_attempt(&plan.effect.intent.run_id,"effect",1).await?.context("original dispatched attempt")?;
        let confirmation=chain.confirm_acceptance(&owned_root)?;
        let deadline=Instant::now()+Duration::from_secs(60);
        let installed=loop {
            let index=begin.elapsed().as_micros();
            let (success,progress)=ordinary::cli(&owned_root,&format!("11-advance-{index}"),&host.fleet_path,"advance",&wire);
            ensure!(success,"ordinary upgrade step failed: {progress}");
            match progress["state"].as_str() {
                Some("installed")=>break progress,
                Some("installing"|"awaiting_chain")=>{},
                _=>anyhow::bail!("unexpected ordinary upgrade progress: {progress}"),
            }
            ensure!(Instant::now()<deadline,"actual signed install exceeded the original 60s window: {progress}");
            tokio::time::sleep(Duration::from_millis(100)).await;
        };
        let target_agent=crate::AgentdClient::new(host.layout.agentd_control_socket().to_path_buf(),owner(),9)?;
        let actual_target=target_agent.cognitive_model_status().await?.installed.context("real target ranker")?;
        ensure!(actual_target==plan.commitment.installed,"installed actual ranker mismatch");
        host.launch=9;
        let terminal=target_agent.automation_observe_effect(plan.effect.intent.clone(),plan.effect.command_id.clone()).await?;
        ensure!(terminal.state==crate::AutomationEffectReconcileState::Terminal,"target generation cannot reconcile original terminal effect");
        ensure!(original.authorized_taskflow_effect_attempt(&plan.effect.intent.run_id,"effect",1).await?==Some(before)
            && original.authorized_taskflow_effect_attempt(&plan.effect.intent.run_id,"effect",2).await?.is_none(),"original dispatch identity changed across process generations");
        save(&owned_root.join("actual-installation.json"),&json!({"installed":installed,"terminal_after_generation_reopen":terminal,
            "monotonic_dispatch_to_install_micros":begin.elapsed().as_micros(),
            "candidate_to_install_wall_micros":support::micros().checked_sub(plan.commitment.candidate_observed_at_unix_micros),
            "source":actual_source,"target":actual_target,
            "original_durable_dispatch_attempts":1,"observed_qualified_update_count":null}));
        // A heavier real fork removes tag 5. The coordinator must report it
        // without turning Chain's observation into rollback authority.
        let mut parent=chain.fixture["prefix_packets"][1]["block"].as_str().context("receipt block")?.to_owned();
        for (branch,steps) in [("reorg",3_u64),("restore",2_u64)] {
            if branch=="restore" {parent=confirmation.clone();}
            for step in 0..steps {
                let packet=owned_root.join(format!("{branch}-{step}.packet"));
                let made=chain.command(&owned_root,&format!("{branch}-{step}-make"),"make",&["--parent".to_owned(),parent,
                    "--timestamp".to_owned(),(genesis+50+step*10).to_string(),"--output".to_owned(),packet.display().to_string()])?;
                parent=made["result"]["block"].as_str().context("real fork block")?.to_owned();
                chain.command(&owned_root,&format!("{branch}-{step}-submit"),"submit",&["--packet".to_owned(),packet.display().to_string()])?;
            }
            let (success,state)=ordinary::cli(&owned_root,&format!("12-{branch}-observe"),&host.fleet_path,"advance",&wire);
            ensure!(success && state["state"]==if branch=="reorg" {"blocked"} else {"installed"},"real branch observation mismatch: {state}");
            ensure!(target_agent.cognitive_model_status().await?.installed==Some(actual_target.clone()),"read-only Chain observation moved model authority");
        }
        let absent=owned_root.join("temporarily-unavailable-payload");
        std::fs::rename(&target.payload,&absent)?;
        let (success,unavailable)=ordinary::cli(&owned_root,"13-data-unavailable",&host.fleet_path,"advance",&wire);
        std::fs::rename(&absent,&target.payload)?;
        ensure!(!success && unavailable["state"]=="failed","missing published bytes must fail closed");
        let mut actual_choices=serde_json::Map::new();
        for query in ["bootstrap","familyalpha","familybeta","familygamma"] {
            let context=target_agent.cognitive_context(query.to_owned(),1).await?;
            ensure!(context.items.len()==1,"actual runtime choice is not singular");
            actual_choices.insert(query.to_owned(),json!(context.items[0].content.split_whitespace().last().context("actual selected instruction")?));
            save(&owned_root.join(format!("installed-{query}-context.json")),&serde_json::to_value(context)?);
        }
        let actual_choices=Value::Object(actual_choices);
        ensure!(actual_choices==target_choices,"actual installed execution differs from frozen candidate");
        let runtime_observation=ordinary_runtime::collect(&owned_root.join("runtime-observations"),&target_agent,
            &actual_target,&target.payload,&actions,&mut roles).await?;
        let followup=owned_root.join("post-install-future");std::fs::create_dir(&followup)?;
        std::fs::copy(&target.payload,followup.join("payload"))?;
        std::fs::create_dir(followup.join("withdrawal-control"))?;
        std::fs::copy(target_root.join("withdrawal-control/observed.json"),followup.join("withdrawal-control/observed.json"))?;
        let observed=ordinary::qualify(&followup,&host,5,&target_fit,&source,&actual_source,&mut roles,
            &actual_choices,&source_choices,anchor,"ordinary-source",QualificationMode::ObserveInstalled(&actual_target)).await;
        ensure!(observed["state"]=="eligible_for_independent_selection" && observed["selection"].is_null(),"post-install future comparison did not qualify without reselection: {observed}");
        ensure!(target_agent.cognitive_model_status().await?.installed==Some(actual_target.clone()),"model changed during subsequent future observation");
        let anchor:eval::FinalHoldoutCasAnchorV1=serde_json::from_value::<crate::cognitive_process_product_wire::FinalHoldoutCasAnchorV1Raw>(observed["holdout_anchor"].clone())?.into();
        let equal_root=owned_root.join("generation-4");std::fs::create_dir(&equal_root)?;
        let equal=fit(&equal_root,4,&mut roles,&actions);
        view.publish(&equal_root,&equal,Some(&target.selected.manifest),&mut roles);
        host.prove_candidate_withdrawal(&equal_root,&equal,&mut roles).await;
        let equal_choices=admission::choices(&equal,&actions);
        ensure!(equal_choices==actual_choices,"no-update must compare actually equal behavior");
        let no_update=ordinary::qualify(&equal_root,&host,4,&equal,&target,&actual_target,&mut roles,
            &equal_choices,&actual_choices,anchor,"ordinary-target",QualificationMode::Select).await;
        ensure!(no_update["state"]=="no_update" && no_update["retained_model"]==serde_json::to_value(&actual_target)?,"ordinary no-update did not retain running predecessor: {no_update}");
        let cached=target_agent.cognitive_context("familygamma".to_owned(),1).await?;
        let revoked=owned_root.join("installed-revocation");std::fs::create_dir(&revoked)?;
        view.revoke(&revoked,target.selected.manifest.artifact_id.clone(),&mut roles);
        ensure!(target_agent.cognitive_model_status().await.is_err() && target_agent.revalidate_cognitive_context(&cached).await.is_err(),
            "actual Agentd/FinalUse must see original installed-artifact revocation");
        let costs:Vec<_>=roles.processes.into_iter().map(support::Role::close).collect();
        Ok::<_,anyhow::Error>(json!({"schema":"hepta.ordinary-native-upgrade-study.v1","full_service_startup":true,
            "installed_service_generations":1,"source_spawn_generation":5,"target_spawn_generation":9,
            "installed":installed,"runtime_tasks":runtime_observation,"subsequent_future_qualification":observed["qualification_evidence_sha256"],
            "observed_qualified_update_count":1,"count_scope":"one installed fixed arithmetic instruction ranker; later fresh final cohort passed original qualification",
            "no_update":no_update,"chain_reorg_observed":true,"unavailable_data_refused":true,"installed_current_and_final_use_revocation_refused":true,
            "independent_operators":false,"general_neural_model_efficacy":false,"role_process_costs":costs}))
    })).await;
    let cleanup=daemon.cleanup(&root).await;
    daemon.binary.verify()?;
    let result=match outcome {
        Ok(result)=>result,
        Err(error)=>Err(anyhow::anyhow!("actual ordinary study child task failed: {error}")),
    };
    let result=match (result,cleanup) {
        (Ok(_),Err(error))=>Err(error.context("actual owned service cleanup failed")),
        (result,_)=>result,
    };
    match result {
        Ok(summary)=>{save(&root.join("summary.json"),&summary);Ok(())},
        Err(error)=>{save(&root.join("native-failure.json"),&json!({"reason":format!("{error:#}"),"installed_service_generations":null,
            "observed_qualified_update_count":null,"partial_observations_retained":true}));Err(error)},
    }
}
