use super::*;
use anyhow::Result;
use codex_hepta_contracts::AgentId;
use tokio::net::UnixListener;

fn request() -> SupervisorControllerRequest {
    SupervisorControllerRequest::new(
        701,
        SupervisorControllerMethod::Receipt {
            agent_id: AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").unwrap(),
            mutation_request_id: 700,
        },
    )
}

#[tokio::test]
async fn controller_client_pins_kernel_owner_before_sending_original_intent() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let path = temp.path().join("ctl");
    let listener = UnixListener::bind(&path)?;
    let owner = unsafe { libc::geteuid() };
    let client = SupervisorControllerClient::new(path, owner + 1)?;
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await?;
        let mut bytes = Vec::new();
        stream.read_to_end(&mut bytes).await?;
        assert!(bytes.is_empty());
        Ok::<_, anyhow::Error>(())
    });
    assert!(client.request(request()).await.is_err());
    server.await??;
    Ok(())
}

#[tokio::test]
async fn controller_client_rejects_foreign_response_id_and_non_lifecycle_payload() -> Result<()> {
    for (index,payload) in [serde_json::json!({"type":"ordinary_mutation_status","status":null}),
        serde_json::json!({"type":"health","health":{"ready":true,"supervisor_epoch":"018f4f72-5f8f-4cc1-8f55-df9fb3aa2c12","process_id":1,"registered_agents":0,"observed_faults":0}})].into_iter().enumerate() {
        let temp=tempfile::tempdir()?;let path=temp.path().join("ctl");let listener=UnixListener::bind(&path)?;
        let client=SupervisorControllerClient::new(path,unsafe{libc::geteuid()})?;
        let response=serde_json::json!({"schema_version":2,"request_id":if index==0 {702}else{701},"payload":payload});
        let server=tokio::spawn(async move {
            let (stream,_)=listener.accept().await?;let (reader,mut writer)=stream.into_split();
            let mut original=String::new();tokio::io::BufReader::new(reader).read_line(&mut original).await?;
            assert_eq!(serde_json::from_str::<SupervisorControllerRequest>(&original)?,request());
            writer.write_all(format!("{response}\n").as_bytes()).await?;Ok::<_,anyhow::Error>(())
        });
        assert!(client.request(request()).await.is_err());server.await??;
    }
    Ok(())
}
