//! Explicit Root administration, fresh publication and original material recovery.

#[cfg(target_os = "linux")]
fn main() -> Result<(), Box<dyn std::error::Error>> {
    use std::io::Write;
    use std::os::fd::AsFd;
    use std::path::PathBuf;
    let mut args = std::env::args_os().skip(1);
    let command = args
        .next()
        .ok_or("initialize, register-writer, register-learning, register-q24-model-factory, serve-session, serve-fresh-session, serve-fresh-material-session, serve-recovered-material-session, diagnose-native, launch-native, provider-status or provider-login required")?;
    let fresh_session =
        command == "serve-fresh-session" || command == "serve-fresh-material-session";
    let recover_material_session = command == "serve-recovered-material-session";
    let serving_session = command == "serve-session" || fresh_session || recover_material_session;
    if command == "independent-b-source" {
        return codex_hepta_agentd::run_original_independent_b_source_cli(args.collect())
            .map_err(Into::into);
    }
    let mut options = std::collections::BTreeMap::new();
    let mut pidfd_stdin = false;
    let mut initial_peer_ready = false;
    while let Some(option) = args.next() {
        if option == "--owner-pidfd-stdin" {
            if pidfd_stdin {
                return Err("duplicate owner pidfd option".into());
            }
            pidfd_stdin = true;
        } else if option == "--initial-peer-ready" {
            if initial_peer_ready {
                return Err("duplicate Initial peer readiness option".into());
            }
            initial_peer_ready = true;
        } else {
            let value = args.next().ok_or("missing option value")?;
            if options.insert(option, value).is_some() {
                return Err("duplicate option".into());
            }
        }
    }
    if initial_peer_ready && !serving_session {
        return Err("Initial peer readiness requires the original serving command".into());
    }
    let mut take = |key: &str| {
        options
            .remove(std::ffi::OsStr::new(key))
            .map(PathBuf::from)
            .ok_or("missing required option")
    };
    if command == "provider-status" || command == "provider-login" {
        let route = take("--route")?;
        if !options.is_empty() || pidfd_stdin {
            return Err("provider command accepts only the original --route file".into());
        }
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()?;
        let result = if command == "provider-status" {
            runtime
                .block_on(codex_hepta_agentd::text_session::diagnose_existing_provider(&route))?
        } else {
            runtime.block_on(codex_hepta_agentd::text_session::login_existing_provider(
                &route,
                |challenge| {
                    // Only the original one-time login challenge is displayed.
                    // No credential file, token, email or account ID is printed.
                    if let Ok(json) = serde_json::to_string(&challenge) {
                        println!("{json}");
                    }
                },
            ))?
        };
        println!("{}", serde_json::to_string(&result)?);
    } else if command == "diagnose-native" || command == "launch-native" {
        let config = take("--config")?;
        let registration = take("--registration")?;
        let profile = take("--native-profile")?;
        if !options.is_empty() || !pidfd_stdin {
            return Err("existing config, registration, native profile and pre-held owner pidfd are required".into());
        }
        let owner = std::io::stdin().as_fd().try_clone_to_owned()?;
        if command == "diagnose-native" {
            println!(
                "{}",
                serde_json::to_string(&codex_hepta_agentd::diagnose_native_launch(
                    &config,
                    &registration,
                    &profile,
                    &owner
                )?)?
            );
        } else {
            codex_hepta_agentd::launch_host_authority_native_session(
                &config,
                &registration,
                &profile,
                owner,
            )?;
        }
    } else if command == "initialize" {
        let state = take("--state")?;
        let bootstrap = take("--bootstrap")?;
        if !options.is_empty() || pidfd_stdin {
            return Err("unknown initialize option".into());
        }
        let initialized = codex_hepta_agentd::initialize_host_authority(&state, &bootstrap)?;
        println!("{}", serde_json::to_string(&initialized)?);
    } else if command == "register-writer" {
        let config = take("--config")?;
        if !options.is_empty() || pidfd_stdin {
            return Err("unknown register-writer option".into());
        }
        let proof = codex_hepta_agentd::register_host_writer_authorization(&config)?;
        println!("{}", serde_json::to_string(&proof)?);
    } else if command == "register-learning" {
        let config = take("--config")?;
        let registration = take("--registration")?;
        let profile = take("--learning-profile")?;
        if !options.is_empty() || !pidfd_stdin {
            return Err("learning registration requires original config, registration, Root profile and pre-held owner pidfd".into());
        }
        let owner = std::io::stdin().as_fd().try_clone_to_owned()?;
        let registered = codex_hepta_agentd::register_host_learning_checkpoint(
            &config,
            &registration,
            &profile,
            &owner,
        )?;
        println!("{}", serde_json::to_string(&registered)?);
    } else if command == "register-q24-model-factory" {
        let config = take("--config")?;
        let registration = take("--registration")?;
        let learning_profile = take("--learning-profile")?;
        let reservation = take("--q24-model-reservation")?;
        if !options.is_empty() || !pidfd_stdin {
            return Err(
                "Model registration requires original Root inputs and pre-held consumer pidfd"
                    .into(),
            );
        }
        let owner = std::io::stdin().as_fd().try_clone_to_owned()?;
        let registered = codex_hepta_agentd::register_host_q24_model_factory(
            &config,
            &registration,
            &learning_profile,
            &reservation,
            &owner,
        )?;
        println!("{}", serde_json::to_string(&registered)?);
    } else if serving_session {
        let config = take("--config")?;
        let registration = take("--registration")?;
        let text_file = options
            .remove(std::ffi::OsStr::new("--text-ui-registration"))
            .map(PathBuf::from);
        let native_profile = options
            .remove(std::ffi::OsStr::new("--native-profile"))
            .map(PathBuf::from);
        let ui_fd = options.remove(std::ffi::OsStr::new("--text-ui-pidfd"));
        let handoff = options.remove(std::ffi::OsStr::new("--root-handoff-fd"));
        let root_fd = options.remove(std::ffi::OsStr::new("--root-pidfd"));
        let learning_profile = options
            .remove(std::ffi::OsStr::new("--learning-profile"))
            .map(PathBuf::from);
        let learning_handoff = options.remove(std::ffi::OsStr::new("--root-learning-handoff-fd"));
        let model_reservation = options
            .remove(std::ffi::OsStr::new("--q24-model-reservation"))
            .map(PathBuf::from);
        let model_handoff = options.remove(std::ffi::OsStr::new("--root-q24-model-handoff-fd"));
        let post_a_deployment = options
            .remove(std::ffi::OsStr::new("--post-a-learning-deployment"))
            .map(PathBuf::from);
        let independent_b_deployment = options
            .remove(std::ffi::OsStr::new(
                "--post-a-independent-evaluation-deployment",
            ))
            .map(PathBuf::from);
        let independent_b_handoff = options.remove(std::ffi::OsStr::new(
            "--root-independent-b-evaluation-handoff-fd",
        ));
        let independent_source_handoff = options.remove(std::ffi::OsStr::new(
            "--root-independent-b-source-handoff-fd",
        ));
        let post_a_publication_deployment = options
            .remove(std::ffi::OsStr::new("--post-a-publication-deployment"))
            .map(PathBuf::from);
        let publication_deployment = options
            .remove(std::ffi::OsStr::new("--generation-publication-deployment"))
            .map(PathBuf::from);
        let publication_handoff = options.remove(std::ffi::OsStr::new(
            "--root-generation-publication-handoff-fd",
        ));
        let initial_deployment = options
            .remove(std::ffi::OsStr::new("--generation-initial-deployment"))
            .map(PathBuf::from);
        let initial_handoff =
            options.remove(std::ffi::OsStr::new("--root-generation-initial-handoff-fd"));
        let source_deployment = options
            .remove(std::ffi::OsStr::new("--historical-source-deployment"))
            .map(PathBuf::from);
        let run_start_deployment = options
            .remove(std::ffi::OsStr::new("--run-start-deployment"))
            .map(PathBuf::from);
        let historical_deployment = options
            .remove(std::ffi::OsStr::new("--historical-task-deployment"))
            .map(PathBuf::from);
        let historical_handoff = options.remove(std::ffi::OsStr::new(
            "--root-historical-task-read-handoff-fd",
        ));
        let notes_profile = options
            .remove(std::ffi::OsStr::new("--notes-launch-profile"))
            .map(PathBuf::from);
        let notes_reservation = options.remove(std::ffi::OsStr::new("--notes-reservation-fd"));
        let notes_session = options.remove(std::ffi::OsStr::new("--notes-session-pidfd"));
        let notes_deployment = options.remove(std::ffi::OsStr::new("--notes-deployment-fd"));
        if !options.is_empty() || !pidfd_stdin {
            return Err("unknown option or missing pre-held owner pidfd".into());
        }
        if (initial_deployment.is_some() || initial_handoff.is_some())
            && (publication_deployment.is_some()
                || publication_handoff.is_some()
                || post_a_publication_deployment.is_some())
        {
            return Err(
                "initial and learned publication require separate original Root sessions".into(),
            );
        }
        if initial_deployment.is_some() != initial_handoff.is_some()
            || initial_deployment.is_some() && root_fd.is_none()
            || initial_peer_ready && initial_deployment.is_none()
        {
            return Err("initial publication requires its explicit Root deployment, separate purpose handoff and original Root pidfd".into());
        }
        if source_deployment.is_some() && initial_deployment.is_none() {
            return Err(
                "source capture requires its original Initial deployment and session".into(),
            );
        }
        if run_start_deployment.is_some() && initial_deployment.is_none() {
            return Err(
                "RunStart retention requires its original Initial deployment and session".into(),
            );
        }
        if historical_deployment.is_some() != historical_handoff.is_some()
            || historical_deployment.is_some() && root_fd.is_none()
            || historical_deployment.is_some() && initial_deployment.is_some()
        {
            return Err("historical task reads require their fixed Root deployment, independent purpose handoff and original Root pidfd in the recipient session".into());
        }
        if post_a_deployment.is_some()
            && (historical_deployment.is_none()
                || learning_handoff.is_none()
                || model_handoff.is_none()
                || root_fd.is_none()
                || learning_profile.is_some()
                || model_reservation.is_some()
                || publication_deployment.is_some())
        {
            return Err("post-A serving requires its fixed Root plan, original historical route and two late handoffs without eager owner profiles".into());
        }
        if post_a_publication_deployment.is_some() && post_a_deployment.is_none()
            || post_a_deployment.is_some()
                && post_a_publication_deployment.is_some() != publication_handoff.is_some()
        {
            return Err("post-A publication requires its fixed Root plan and original late handoff in the post-A session".into());
        }
        if post_a_deployment.is_none()
            && (publication_deployment.is_some() != publication_handoff.is_some()
                || publication_deployment.is_some()
                    && (learning_profile.is_none() || root_fd.is_none()))
        {
            return Err("publication serving requires its explicit Root deployment, separate purpose handoff, original learning and Root pidfd".into());
        }
        if independent_b_deployment.is_some() != independent_b_handoff.is_some()
            || independent_b_deployment.is_some() != independent_source_handoff.is_some()
            || independent_b_deployment.is_some() && post_a_deployment.is_none()
            || post_a_deployment.is_some()
                && (independent_b_deployment.is_none()
                    || post_a_publication_deployment.is_none()
                    || publication_handoff.is_none())
        {
            return Err("ordinary post-A requires its original independent B deployment and purpose handoff beside its original publication route".into());
        }
        // Claim every numeric inherited FD before any clone/open/runtime can
        // reuse a missing number. One slot owns each FD and closes the original.
        let mut claimed = std::collections::BTreeSet::new();
        let handoff = handoff
            .as_deref()
            .map(|fd| inherited_descriptor(fd, &mut claimed))
            .transpose()?;
        let root_fd = root_fd
            .as_deref()
            .map(|fd| inherited_descriptor(fd, &mut claimed))
            .transpose()?;
        let mut learning_handoff = learning_handoff
            .as_deref()
            .map(|fd| inherited_descriptor(fd, &mut claimed))
            .transpose()?;
        let mut model_handoff = model_handoff
            .as_deref()
            .map(|fd| inherited_descriptor(fd, &mut claimed))
            .transpose()?;
        let mut independent_b_handoff = independent_b_handoff
            .as_deref()
            .map(|fd| inherited_descriptor(fd, &mut claimed))
            .transpose()?;
        let mut independent_source_handoff = independent_source_handoff
            .as_deref()
            .map(|fd| inherited_descriptor(fd, &mut claimed))
            .transpose()?;
        let mut publication_handoff = publication_handoff
            .as_deref()
            .map(|fd| inherited_descriptor(fd, &mut claimed))
            .transpose()?;
        let initial_handoff = initial_handoff
            .as_deref()
            .map(|fd| inherited_descriptor(fd, &mut claimed))
            .transpose()?;
        let historical_handoff = historical_handoff
            .as_deref()
            .map(|fd| inherited_descriptor(fd, &mut claimed))
            .transpose()?;
        if post_a_deployment.is_none()
            && (model_reservation.is_some() != model_handoff.is_some()
                || model_handoff.is_some() && (learning_profile.is_none() || root_fd.is_none()))
        {
            return Err("Model serving requires its reserved Root profile and separate handoff beside original learning".into());
        }
        if post_a_deployment.is_none()
            && (learning_profile.is_some() != learning_handoff.is_some()
                || learning_profile.is_some() && root_fd.is_none())
        {
            return Err("learning serving requires its Root profile, separate handoff and original Root pidfd".into());
        }
        let notes = match (notes_profile, notes_reservation, notes_session, notes_deployment) {
            (None, None, None, None) => None,
            (Some(profile), Some(reservation), Some(session), Some(deployment))
                if fresh_session => Some((
                    profile, inherited_descriptor(&reservation, &mut claimed)?,
                    inherited_descriptor(&session, &mut claimed)?, inherited_descriptor(&deployment, &mut claimed)?,
                )),
            _ => return Err("fresh Notes requires its complete inherited reservation, Session pidfd, deployment memfd and Root profile".into()),
        };
        let text = match (text_file.as_deref(), ui_fd) {
            (None, None) => None,
            (Some(file), Some(fd)) => Some((file, inherited_descriptor(&fd, &mut claimed)?)),
            _ => {
                return Err("text UI registration and pre-held pidfd are required together".into());
            }
        };
        if native_profile.is_some() && text.is_some() {
            return Err("native child launch and an inherited text UI are exclusive".into());
        }
        let owner = std::io::stdin().as_fd().try_clone_to_owned()?;
        let prepared = if fresh_session {
            let handoff =
                handoff.ok_or("fresh session requires the original Root handoff descriptor")?;
            let root = root_fd
                .as_ref()
                .ok_or("fresh session requires the pre-held current Root pidfd")?;
            let runtime = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()?;
            let prepared = if command == "serve-fresh-material-session" {
                runtime.block_on(
                    codex_hepta_agentd::PreparedHostAuthoritySession::prepare_fresh_with_physical_material(
                        &config,
                        &registration,
                        owner,
                    ),
                )?
            } else {
                runtime.block_on(
                    codex_hepta_agentd::PreparedHostAuthoritySession::prepare_fresh_from_registered(
                        &config,
                        &registration,
                        owner,
                    ),
                )?
            };
            let (prepared, consumers) = prepared.handoff_fresh_agent_filesystem()?;
            let prepared = match notes {
                Some((profile, reservation, session, deployment)) => prepared
                    .with_notes_startup_from_session(
                        &profile,
                        std::os::unix::net::UnixDatagram::from(reservation),
                        session,
                        std::fs::File::from(deployment),
                    )?,
                None => prepared,
            };
            let bootstrap = if command == "serve-fresh-material-session" {
                codex_hepta_agentd::PreparedHostAuthoritySession::seal_original_material_bootstrap(
                    &prepared,
                )?
            } else {
                prepared.seal_bootstrap(&consumers)?
            };
            codex_hepta_agentd::send_root_production_handoff(
                std::os::unix::net::UnixDatagram::from(handoff),
                &bootstrap,
                root,
                std::time::Duration::from_secs(30),
            )?;
            prepared
        } else if recover_material_session {
            let handoff =
                handoff.ok_or("material recovery requires the original Root handoff descriptor")?;
            let root = root_fd
                .as_ref()
                .ok_or("material recovery requires the pre-held current Root pidfd")?;
            // This API holds the original writer fence while verifying the
            // kernel-retired predecessor, old expiry, live successor and the
            // retained physical image. It installs/adopts/releases that image;
            // no fresh preparation or filesystem handoff is a recovery fallback.
            let prepared =
                codex_hepta_agentd::PreparedHostAuthoritySession::recover_with_physical_material(
                    &config,
                    &registration,
                    owner,
                )?;
            let bootstrap =
                codex_hepta_agentd::PreparedHostAuthoritySession::seal_original_material_bootstrap(
                    &prepared,
                )?;
            codex_hepta_agentd::send_root_production_handoff(
                std::os::unix::net::UnixDatagram::from(handoff),
                &bootstrap,
                root,
                std::time::Duration::from_secs(30),
            )?;
            prepared
        } else {
            if handoff.is_some()
                || root_fd.is_some()
                    && learning_handoff.is_none()
                    && initial_handoff.is_none()
                    && historical_handoff.is_none()
            {
                return Err("open-only serving does not accept fresh handoff inputs".into());
            }
            codex_hepta_agentd::PreparedHostAuthoritySession::open(&config, &registration, owner)?
        };
        let prepared = match learning_profile {
            Some(profile) => prepared.with_registered_learning(&profile)?,
            None => prepared,
        };
        let mut prepared = match model_reservation {
            Some(reservation) => prepared.with_registered_q24_model_factory(&reservation)?,
            None => prepared,
        };
        let eager_publication_handoff = if post_a_deployment.is_some() {
            None
        } else {
            publication_handoff.take()
        };
        let (deployment, publication_offer) = match (
            publication_deployment,
            eager_publication_handoff,
        ) {
            (Some(path), Some(handoff)) => {
                let (capability, offer) = prepared.enable_generation_publication()?;
                let capability: codex_hepta_agentd::RootGenerationPublicationEnrollmentCapabilityV1 = capability;
                (
                    Some(capability.with_original_deployment(&path)?),
                    Some((handoff, offer)),
                )
            }
            (None, None) => (None, None),
            _ => return Err("publication deployment and inherited offer must be paired".into()),
        };
        let (initial_deployment, initial_offer) = match (initial_deployment, initial_handoff) {
            (Some(path), Some(handoff)) => {
                let files = codex_hepta_agentd::RootGenerationInitialDeploymentFilesV1::open_original_initial_deployment(&path)?;
                if source_deployment.is_some() {
                    codex_hepta_agentd::PreparedHostAuthoritySession::require_original_historical_deployment(&prepared, &files)?;
                }
                let (capability, offer) =
                    prepared.enable_generation_initial(files.deployment().clone())?;
                let capability: codex_hepta_agentd::RootGenerationInitialEnrollmentCapabilityV1 =
                    capability;
                let deployment = capability.with_original_initial_deployment(files)?;
                if initial_peer_ready {
                    codex_hepta_agentd::PreparedHostAuthoritySession::enable_original_initial_peer_ready(
                        &mut prepared,
                        deployment,
                    )?;
                    (None, Some((handoff, offer)))
                } else {
                    (Some(deployment), Some((handoff, offer)))
                }
            }
            (None, None) => (None, None),
            _ => return Err("initial deployment and inherited offer must be paired".into()),
        };
        if let Some(path) = source_deployment {
            prepared.enable_initial_source_capture_from_deployment(&path)?;
        }
        if let Some(path) = run_start_deployment {
            prepared.enable_initial_run_start_retention_from_deployment(&path)?;
        }
        let historical_offer = match (historical_deployment, historical_handoff) {
            (Some(path), Some(handoff)) => {
                codex_hepta_agentd::PreparedHostAuthoritySession::enable_original_historical_task_read_from_deployment(&mut prepared, &path)?;
                if let Some(post_a_path) = post_a_deployment.as_deref() {
                    let learning = learning_handoff
                        .take()
                        .ok_or("original late learning handoff missing")?;
                    let model = model_handoff
                        .take()
                        .ok_or("original late Model handoff missing")?;
                    let root = root_fd
                        .as_ref()
                        .ok_or("original post-A Root pidfd missing")?
                        .try_clone()?;
                    let publication = match (
                        post_a_publication_deployment.as_deref(),
                        publication_handoff.take(),
                    ) {
                        (Some(path), Some(handoff)) => {
                            Some((path, std::os::unix::net::UnixDatagram::from(handoff)))
                        }
                        (None, None) => None,
                        _ => return Err("original post-A publication inputs differ".into()),
                    };
                    let independent_evaluation = match (
                        independent_b_deployment.as_deref(),
                        independent_b_handoff.take(),
                        independent_source_handoff.take(),
                    ) {
                        (Some(path), Some(handoff), Some(source)) => Some((
                            path,
                            std::os::unix::net::UnixDatagram::from(handoff),
                            std::os::unix::net::UnixDatagram::from(source),
                        )),
                        _ => {
                            return Err(
                                "original independent B inputs are missing or already consumed"
                                    .into(),
                            );
                        }
                    };
                    codex_hepta_agentd::PreparedHostAuthoritySession::enable_original_post_a_learning_with_independent_b(
                        &mut prepared,
                        post_a_path,
                        std::os::unix::net::UnixDatagram::from(learning),
                        std::os::unix::net::UnixDatagram::from(model),
                        root,
                        publication,
                        independent_evaluation,
                    )?;
                }
                Some((handoff, codex_hepta_agentd::PreparedHostAuthoritySession::seal_original_historical_task_read(&prepared)?))
            }
            (None, None) => None,
            _ => {
                return Err("historical task deployment and inherited offer must be paired".into());
            }
        };
        let initial_ready = initial_deployment
            .as_ref()
            .map(|deployment| serde_json::to_string(deployment.session()))
            .transpose()?;
        let deployment_ready = deployment
            .as_ref()
            .map(|deployment| serde_json::to_string(deployment.session()))
            .transpose()?;
        let model_offer = model_handoff
            .as_ref()
            .map(|_| prepared.take_q24_model_factory_offer())
            .transpose()?;
        let learning_bootstrap = learning_handoff
            .as_ref()
            .map(|_| prepared.seal_learning_bootstrap())
            .transpose()?;
        let ready = || {
            if let (Some(handoff), Some(bootstrap), Some(root)) =
                (learning_handoff, learning_bootstrap, root_fd.as_ref())
            {
                codex_hepta_agentd::send_root_learning_handoff(
                    std::os::unix::net::UnixDatagram::from(handoff),
                    &bootstrap,
                    root,
                    std::time::Duration::from_secs(30),
                )
                .map_err(std::io::Error::other)?;
            }
            if let (Some(handoff), Some(offer), Some(root)) =
                (model_handoff, model_offer, root_fd.as_ref())
            {
                codex_hepta_agentd::send_root_q24_model_factory_handoff(
                    std::os::unix::net::UnixDatagram::from(handoff),
                    offer,
                    root,
                    std::time::Duration::from_secs(30),
                )
                .map_err(std::io::Error::other)?;
            }
            if let (Some((handoff, offer)), Some(root)) = (publication_offer, root_fd.as_ref()) {
                codex_hepta_agentd::send_root_generation_publication_handoff(
                    std::os::unix::net::UnixDatagram::from(handoff),
                    offer,
                    root,
                    std::time::Duration::from_secs(30),
                )
                .map_err(std::io::Error::other)?;
            }
            if let (Some((handoff, offer)), Some(root)) = (initial_offer, root_fd.as_ref()) {
                codex_hepta_agentd::send_root_generation_initial_handoff(
                    std::os::unix::net::UnixDatagram::from(handoff),
                    offer,
                    root,
                    std::time::Duration::from_secs(30),
                )
                .map_err(std::io::Error::other)?;
            }
            if let (Some((handoff, offer)), Some(root)) = (historical_offer, root_fd.as_ref()) {
                codex_hepta_agentd::send_root_historical_task_read_handoff(
                    std::os::unix::net::UnixDatagram::from(handoff),
                    offer,
                    root,
                    std::time::Duration::from_secs(30),
                )
                .map_err(std::io::Error::other)?;
            }
            if let Some(session) = initial_ready {
                println!("{{\"initial_deployment_session\":{session}}}");
                std::io::stdout().flush()?;
            }
            if let Some(session) = deployment_ready {
                println!("{{\"publication_deployment_session\":{session}}}");
                std::io::stdout().flush()?;
            }
            Ok(())
        };
        let stopping = std::sync::atomic::AtomicBool::new(/*val*/ false);
        std::thread::scope(|scope| -> std::io::Result<()> {
            // A failed ready callback or unwind also stops the read-only waiter
            // before scope joins it. No second service/writer is opened.
            let stop = PublicationDeploymentStop(&stopping);
            let stop_ref = &stopping;
            let worker = deployment.map(|deployment| scope.spawn(move || {
                let deployment: codex_hepta_agentd::RootGenerationPublicationDeploymentV1 = deployment;
                let registered = deployment.wait_and_register(stop_ref)?;
                // Report the original completed registration while serving, so
                // the trusted host can connect without racing its short timeout.
                let stdout = std::io::stdout();
                let mut output = stdout.lock();
                writeln!(output, "{{\"publication_registered_binding\":\"{}\"}}", registered.binding())
                    .and_then(|()| output.flush())
                    .map_err(|error| std::io::Error::other(format!(
                        "original publication registered; acknowledgement output uncertain: {error}",
                    )))?;
                Ok::<_, std::io::Error>(registered)
            }));
            let initial_worker = initial_deployment.map(|deployment| {
                scope.spawn(move || {
                let deployment: codex_hepta_agentd::RootGenerationInitialDeploymentV1 = deployment;
                let registered = deployment.wait_and_register_initial(stop_ref)?;
                let stdout = std::io::stdout();
                let mut output = stdout.lock();
                writeln!(output, "{{\"initial_registered_binding\":\"{}\"}}", registered.binding())
                    .and_then(|()| output.flush())
                    .map_err(|error| std::io::Error::other(format!(
                        "original Initial registered; acknowledgement output uncertain: {error}",
                    )))?;
                Ok::<_, std::io::Error>(registered)
            })
            });
            let served = match (native_profile, text) {
                (Some(profile), None) => {
                    prepared.launch_native_with_ready(&config, &registration, &profile, ready)
                }
                (None, Some((file, pidfd))) => {
                    prepared.serve_with_text_and_ready(file, pidfd, ready)
                }
                (None, None) => prepared.serve_with_ready(ready),
                (Some(_), Some(_)) => {
                    Err(std::io::Error::other("exclusive native/text UI options"))
                }
            };
            drop(stop);
            let registered = match worker {
                Some(worker) => Some(
                    worker
                        .join()
                        .map_err(|_| std::io::Error::other("Root deployment worker panicked"))?,
                ),
                None => None,
            };
            let initial_registered = match initial_worker {
                Some(worker) => Some(worker.join().map_err(|_| {
                    std::io::Error::other("Root Initial deployment worker panicked")
                })?),
                None => None,
            };
            served?;
            if let Some(registered) = initial_registered {
                registered?;
            }
            if let Some(registered) = registered {
                registered?;
            }
            Ok(())
        })?;
    } else {
        return Err("unknown authority command".into());
    }
    Ok(())
}

#[cfg(target_os = "linux")]
struct PublicationDeploymentStop<'a>(&'a std::sync::atomic::AtomicBool);

#[cfg(target_os = "linux")]
impl Drop for PublicationDeploymentStop<'_> {
    fn drop(&mut self) {
        self.0
            .store(/*val*/ true, std::sync::atomic::Ordering::Release);
    }
}

#[cfg(target_os = "linux")]
fn inherited_descriptor(
    value: &std::ffi::OsStr,
    claimed: &mut std::collections::BTreeSet<i32>,
) -> Result<std::os::fd::OwnedFd, Box<dyn std::error::Error>> {
    use std::os::fd::FromRawFd;
    let fd: i32 = value
        .to_str()
        .ok_or("invalid inherited descriptor")?
        .parse()?;
    if fd < 3 || !claimed.insert(fd) {
        return Err(
            "one distinct inherited descriptor numbered at least 3 is required per slot".into(),
        );
    }
    // SAFETY: all numeric descriptors are claimed before any runtime, open or
    // stdin clone. No Rust owner exists for these inherited descriptors yet.
    let flags = unsafe { libc::fcntl(fd, libc::F_GETFD) };
    if flags < 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    // SAFETY: this is the first and only owner of the checked inherited FD;
    // the per-parse set rejects aliases before a second adoption is possible.
    let descriptor = unsafe { std::os::fd::OwnedFd::from_raw_fd(fd) };
    // SAFETY: the now-owned descriptor remains live across this flags update.
    if unsafe { libc::fcntl(fd, libc::F_SETFD, flags | libc::FD_CLOEXEC) } < 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok(descriptor)
}

#[cfg(all(test, target_os = "linux"))]
#[path = "../root_cli_descriptor_tests.rs"]
mod descriptor_tests;

#[cfg(not(target_os = "linux"))]
fn main() {
    eprintln!("hepta-authority-host requires Linux");
    std::process::exit(1);
}
