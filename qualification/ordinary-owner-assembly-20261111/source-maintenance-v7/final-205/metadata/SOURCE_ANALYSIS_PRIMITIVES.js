{
  "schema_version": 1,
  "literal_matcher_js": "return (function(){\n function tokens(s){\n  const out=[];let i=0;\n  while(i<s.length){\n   if(/\\s/.test(s[i])){i++;continue;}\n   const start=i;\n   if(s.startsWith(\"//\",i)){i=s.indexOf(\"\\n\",i);if(i<0)i=s.length;out.push({v:s.slice(start,i),start,end:i,kind:\"comment\"});continue;}\n   if(s.startsWith(\"/*\",i)){let d=1;i+=2;while(i<s.length&&d){if(s.startsWith(\"/*\",i)){d++;i+=2;}else if(s.startsWith(\"*/\",i)){d--;i+=2;}else i++;}out.push({v:s.slice(start,i),start,end:i,kind:\"comment\"});continue;}\n   const raw=/^(?:br|cr|r)(#{0,255})\"/.exec(s.slice(i));\n   if(raw){const end=s.indexOf('\"'+raw[1],i+raw[0].length);if(end<0)throw Error(\"unterminated raw string\");i=end+1+raw[1].length;out.push({v:s.slice(start,i),start,end:i,kind:\"literal\"});continue;}\n   if(s[i]==='\"'||((s[i]===\"b\"||s[i]===\"c\")&&s[i+1]==='\"')){if(s[i]!=='\"')i++;i++;let closed=false;while(i<s.length){if(s[i]===\"\\\\\"){i+=2;continue;}if(s[i++]==='\"'){closed=true;break;}}if(!closed)throw Error(\"unterminated string\");out.push({v:s.slice(start,i),start,end:i,kind:\"literal\"});continue;}\n   const ch=/^'(?:\\\\(?:u\\{[0-9a-fA-F_]+\\}|x[0-9a-fA-F]{2}|.)|[^\\\\'\\n])'/.exec(s.slice(i));\n   if(ch){i+=ch[0].length;out.push({v:s.slice(start,i),start,end:i,kind:\"literal\"});continue;}\n   const word=/^[A-Za-z_][A-Za-z_0-9]*/.exec(s.slice(i))||/^[0-9][A-Za-z_0-9]*/.exec(s.slice(i));\n   if(word){i+=word[0].length;out.push({v:s.slice(start,i),start,end:i,kind:\"word\"});continue;}\n   i++;out.push({v:s.slice(start,i),start,end:i,kind:\"punctuation\"});\n  }\n  return out;\n }\n function normalize(ts,trailing){return trailing?ts.filter((t,i)=>!(t.v===\",\"&&ts[i+1]&&[\")\",\"]\",\"}\",\">\"].includes(ts[i+1].v))):ts;}\n function matches(marker,source,options={}){\n  const pattern=normalize(tokens(marker),!!options.trailing),subject=normalize(tokens(source),!!options.trailing);\n  if(!pattern.length)return [];\n  const hits=[];\n  for(let i=0;i+pattern.length<=subject.length;i++){\n   if(subject[i].v!==pattern[0].v)continue;let ok=true;\n   for(let j=1;j<pattern.length;j++)if(subject[i+j].v!==pattern[j].v){ok=false;break;}\n   if(ok){const start=subject[i].start,end=subject[i+pattern.length-1].end;hits.push({start,end,text:source.slice(start,end)});}\n  }\n  return hits;\n }\n return {tokens,matches};\n})();",
  "ordered_marker_resampler_js": "return function resampleOrderedMarkers(sequence, subject, Lexer) {\n const mapped=[],issues=[];let cursor=0;\n for(let i=0;i<sequence.length;i++){\n  const marker=sequence[i],candidates=[];\n  for(const hit of Lexer.matches(marker,subject))if(hit.start>=cursor)candidates.push({...hit,classification:hit.text===marker?\"identical\":\"whitespace\",priority:0});\n  for(const hit of Lexer.matches(marker,subject,{trailing:true}))if(hit.start>=cursor)candidates.push({...hit,classification:\"optional_internal_trailing_comma\",priority:1});\n  const tok=Lexer.tokens(marker);\n  if(tok.at(-1)?.v===\",\"){\n   const bare=marker.slice(0,tok.at(-1).start);\n   for(const hit of Lexer.matches(bare,subject)){\n    if(hit.start<cursor)continue;\n    const next=Lexer.tokens(subject.slice(hit.end))[0];\n    if(next&&[\")\",\"]\",\"}\",\">\"].includes(next.v))candidates.push({...hit,classification:\"optional_fragment_end_comma\",following_actual_delimiter:next.v,priority:2});\n   }\n  }\n  candidates.sort((a,b)=>a.start-b.start||a.priority-b.priority||a.end-b.end);\n  const chosen=candidates[0];\n  if(!chosen){mapped.push(marker);issues.push({index:i,marker,cursor});continue;}\n  mapped.push(chosen.text);\n  if(chosen.text!==marker)issues.push({index:i,before:marker,after:chosen.text,classification:chosen.classification,start:chosen.start,end:chosen.end,following_actual_delimiter:chosen.following_actual_delimiter});\n  cursor=chosen.end;\n }\n return{sequence:mapped,issues};\n};",
  "whole_guard_selections": [
    {
      "selection": {
        "path": "codex-rs/rmcp-client/src/rmcp_client_owned_shutdown.rs",
        "allStructures": true
      },
      "origin": "e6da443d18aefcfb345a222cdbc025195271af72#new_protected:0"
    },
    {
      "selection": {
        "path": "codex-rs/codex-mcp/src/original_owned_shutdown.rs",
        "allStructures": true
      },
      "origin": "e6da443d18aefcfb345a222cdbc025195271af72#new_protected:1"
    },
    {
      "selection": {
        "path": "codex-rs/codex-mcp/src/rmcp_client_owned_shutdown.rs",
        "allStructures": true
      },
      "origin": "e6da443d18aefcfb345a222cdbc025195271af72#new_protected:2"
    },
    {
      "selection": {
        "path": "codex-rs/app-server/src/configured_mcp_runtime_owned_shutdown.rs",
        "allStructures": true
      },
      "origin": "e6da443d18aefcfb345a222cdbc025195271af72#new_protected:3"
    },
    {
      "selection": {
        "path": "codex-rs/core/src/session/original_shutdown.rs",
        "allStructures": true
      },
      "origin": "e6da443d18aefcfb345a222cdbc025195271af72#new_protected:4"
    },
    {
      "selection": {
        "path": "codex-rs/core/src/thread_manager_original_shutdown.rs",
        "allStructures": true
      },
      "origin": "e6da443d18aefcfb345a222cdbc025195271af72#new_protected:5"
    },
    {
      "selection": {
        "path": "codex-rs/core/src/agent/control_original_shutdown.rs",
        "allStructures": true
      },
      "origin": "e6da443d18aefcfb345a222cdbc025195271af72#new_protected:6"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/production_launcher_same_actor_owner.rs",
        "allStructures": true
      },
      "origin": "e6da443d18aefcfb345a222cdbc025195271af72#new_protected:7"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/production_launcher_same_actor_run.rs",
        "allStructures": true
      },
      "origin": "e6da443d18aefcfb345a222cdbc025195271af72#new_protected:8"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/production_launcher_same_actor_runtime.rs",
        "allStructures": true
      },
      "origin": "e6da443d18aefcfb345a222cdbc025195271af72#new_protected:9"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/production_launcher_same_actor_completion.rs",
        "allStructures": true
      },
      "origin": "e6da443d18aefcfb345a222cdbc025195271af72#new_protected:10"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/production_launcher_same_actor_completion_custody.rs",
        "allStructures": true
      },
      "origin": "e6da443d18aefcfb345a222cdbc025195271af72#new_protected:11"
    },
    {
      "selection": {
        "path": "codex-rs/rmcp-client/src/rmcp_client.rs",
        "functions": [
          "new_in_process_client",
          "new_stdio_client_with_protocol_mode",
          "new_streamable_http_client_with_protocol_mode_and_redirect_mode",
          "connect_pending_transport"
        ],
        "structures": [
          "pub struct RmcpClient {"
        ],
        "required": [
          "#[path = \"rmcp_client_owned_shutdown.rs\"]",
          "pub use owned_shutdown::OriginalMcpClientShutdown;",
          "pub use owned_shutdown::OriginalMcpClientShutdownObservation;"
        ]
      },
      "origin": "e6da443d18aefcfb345a222cdbc025195271af72#new_protected:12"
    },
    {
      "selection": {
        "path": "codex-rs/codex-mcp/src/runtime.rs",
        "functions": [
          "new_with_owned_shutdown",
          "original_owned_shutdown"
        ],
        "structures": [
          "pub struct McpRuntimeContext {",
          "impl McpRuntimeContext {"
        ],
        "required": [
          "original_owned_shutdown: None,"
        ]
      },
      "origin": "e6da443d18aefcfb345a222cdbc025195271af72#new_protected:13"
    },
    {
      "selection": {
        "path": "codex-rs/codex-mcp/src/connection_manager.rs",
        "functions": [
          "new"
        ]
      },
      "origin": "e6da443d18aefcfb345a222cdbc025195271af72#new_protected:14"
    },
    {
      "selection": {
        "path": "codex-rs/codex-mcp/src/rmcp_client.rs",
        "functions": [
          "start"
        ],
        "required": [
          "#[path = \"rmcp_client_owned_shutdown.rs\"]",
          "mod original_owned;"
        ]
      },
      "origin": "e6da443d18aefcfb345a222cdbc025195271af72#new_protected:15"
    },
    {
      "selection": {
        "path": "codex-rs/app-server/src/configured_mcp_runtime.rs",
        "functions": [
          "initialize_configured_mcp_server",
          "shutdown"
        ],
        "structures": [
          "pub struct ConfiguredMcpRuntime {"
        ],
        "required": [
          "#[path = \"configured_mcp_runtime_owned_shutdown.rs\"]",
          "pub use owned_shutdown::initialize_configured_mcp_server_with_owned_shutdown;",
          "original_owned_shutdown: None,"
        ]
      },
      "origin": "e6da443d18aefcfb345a222cdbc025195271af72#new_protected:16"
    },
    {
      "selection": {
        "path": "codex-rs/core/src/session/mod.rs",
        "functions": [
          "spawn_internal",
          "session_loop_termination_from_handle",
          "shutdown_and_wait"
        ],
        "structures": [
          "pub(crate) struct SessionIo {"
        ],
        "required": [
          "mod original_shutdown;",
          "pub(crate) use original_shutdown::OriginalCoreTaskFailure;",
          "pub(crate) use original_shutdown::OriginalSessionLoopOutcome;",
          "pub(crate) use original_shutdown::OriginalSessionLoopShutdown;"
        ]
      },
      "origin": "e6da443d18aefcfb345a222cdbc025195271af72#new_protected:17"
    },
    {
      "selection": {
        "path": "codex-rs/core/src/thread_manager.rs",
        "functions": [
          "new",
          "with_models_provider_home_and_state_for_tests",
          "spawn_thread",
          "spawn_thread_owned",
          "shutdown_all_threads_bounded"
        ],
        "structures": [
          "pub(crate) struct ThreadManagerState {"
        ],
        "required": [
          "#[path = \"thread_manager_original_shutdown.rs\"]",
          "mod original_shutdown;",
          "pub(crate) use original_shutdown::OriginalSessionShutdownOrigin;"
        ]
      },
      "origin": "e6da443d18aefcfb345a222cdbc025195271af72#new_protected:18"
    },
    {
      "selection": {
        "path": "codex-rs/core/src/agent/control.rs",
        "functions": [
          "new"
        ],
        "structures": [
          "pub(crate) struct AgentControl {"
        ],
        "required": [
          "#[path = \"control_original_shutdown.rs\"]",
          "mod original_shutdown;"
        ]
      },
      "origin": "e6da443d18aefcfb345a222cdbc025195271af72#new_protected:19"
    },
    {
      "selection": {
        "path": "codex-rs/core/src/codex_delegate.rs",
        "functions": [
          "run_codex_thread_interactive",
          "run_codex_thread_one_shot"
        ]
      },
      "origin": "e6da443d18aefcfb345a222cdbc025195271af72#new_protected:20"
    },
    {
      "selection": {
        "path": "codex-rs/rmcp-client/src/lib.rs",
        "functions": [],
        "required": [
          "pub use rmcp_client::OriginalMcpClientShutdown;",
          "pub use rmcp_client::OriginalMcpClientShutdownObservation;",
          "pub use stdio_server_launcher::OriginalStdioShutdownCustody;",
          "pub use stdio_server_launcher::OriginalStdioShutdownObservation;"
        ]
      },
      "origin": "e6da443d18aefcfb345a222cdbc025195271af72#new_protected:21"
    },
    {
      "selection": {
        "path": "codex-rs/codex-mcp/src/lib.rs",
        "functions": [],
        "required": [
          "mod original_owned_shutdown;",
          "pub use original_owned_shutdown::OriginalMcpRuntimeShutdown;",
          "pub use original_owned_shutdown::OriginalMcpRuntimeShutdownObservation;"
        ]
      },
      "origin": "e6da443d18aefcfb345a222cdbc025195271af72#new_protected:22"
    },
    {
      "selection": {
        "path": "codex-rs/app-server/src/lib.rs",
        "functions": [],
        "required": [
          "pub use configured_mcp_runtime::initialize_configured_mcp_server_with_owned_shutdown;",
          "pub use codex_mcp::OriginalMcpRuntimeShutdown;",
          "pub use codex_mcp::OriginalMcpRuntimeShutdownObservation;"
        ]
      },
      "origin": "e6da443d18aefcfb345a222cdbc025195271af72#new_protected:23"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_deployment_protocol.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:0"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/production_launcher_same_actor_consumer_custody.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:1"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/production_launcher_same_actor_deployment.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:2"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_deployment_client.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:3"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_deployment_ingress.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:4"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_deployment_owner.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:5"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_deployment_factory.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:6"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_deployment_coordinator.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:7"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_deployment_coordinator_materials.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:8"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_deployment_files.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:9"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_deployment_file_origin.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:10"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_deployment_learning_data.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:11"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_deployment_learning.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:12"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_deployment_learning_owners.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:13"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_deployment_preparation.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:14"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_deployment_cell_data.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:15"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_deployment_bundle_data.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:16"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_deployment_model.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:17"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_deployment_task.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:18"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_deployment_c.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:19"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_deployment_artifact_data.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:20"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_deployment_artifacts.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:21"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_deployment_exchange.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:22"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_deployment_temporal_data.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:23"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_deployment_comparison_data.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:24"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_deployment_evaluation_data.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:25"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_deployment_evaluation_signing.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:26"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_deployment_evaluation_storage.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:27"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_deployment_evaluation.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:28"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_deployment_observation_data.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:29"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_deployment_data.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:30"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_deployment_witness.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:31"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_deployment.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:32"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_deployment_retirement.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:33"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_deployment_retained.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:34"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/root_production_same_actor_retirement.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:35"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_deployment_root_exit.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:36"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_required_purpose_retirement.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:37"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_phase_initial.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:38"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/production_launcher_same_actor_phase.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:39"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/main.rs",
        "allStructures": true
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:40"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/root_production_same_actor_phase_inputs.rs",
        "functions": [
          "receive_original_same_actor_inputs",
          "open_original_phase_consumer",
          "require_current",
          "grants",
          "device",
          "notes",
          "root_pidfd",
          "clock",
          "read_original_phase_descriptor",
          "validate_original_phase_binding"
        ],
        "structures": [
          "pub(crate) struct OriginalSameActorRootContext {",
          "pub(crate) struct OriginalSameActorProductionInputs {"
        ]
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:41"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/cognitive_checkpoint_unix.rs",
        "functions": [
          "from_original_phase_stream_until",
          "retire_original_root_checkpoint_purpose",
          "exchange"
        ],
        "structures": [
          "pub struct AgentdUnixCognitiveCheckpointTransport {"
        ]
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:42"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/final_use_issuer.rs",
        "functions": [
          "into_same_actor_phase",
          "retire_original_root_grant_purpose",
          "request_grant",
          "exchange_guarded"
        ],
        "structures": [
          "pub struct AgentdUnixFinalUseGrantProvider {"
        ]
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:43"
    },
    {
      "selection": {
        "path": "codex-rs/hepta-agentd/src/same_actor_q24_phase_gate.rs",
        "functions": [
          "original_retirement_custody",
          "shutdown_original_after_root_intent",
          "shutdown_original_after_root_workers_joined",
          "retain_required_original_stream",
          "start",
          "finish_original_after_root_exit",
          "close",
          "disarm"
        ],
        "structures": [
          "pub(crate) struct RequiredSameActorPhaseChannel {",
          "pub(crate) struct OriginalRequiredPurposeRetirement {",
          "pub(crate) struct OriginalSameActorPhaseWatch {",
          "impl Drop for OriginalSameActorPhaseWatch {"
        ]
      },
      "origin": "c9815b6842ed51866a0ab058d1e9069cd60ef26b#new_protected:44"
    }
  ],
  "primitives": "c82daa6cd3614f74a84097aeb003f45fbb8720fd",
  "generator": "eca89aa4bfff94d81346a3345974ea6c7ffd07c3"
}
