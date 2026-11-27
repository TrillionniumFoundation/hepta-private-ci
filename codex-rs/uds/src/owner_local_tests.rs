use std::io;
use std::time::Duration;

use pretty_assertions::assert_eq;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::time::timeout;

use super::OwnerLocalListener;
use super::OwnerLocalStream;

#[tokio::test]
async fn authenticated_owner_local_stream_round_trips_application_bytes() -> io::Result<()> {
    let directory = tempfile::TempDir::new()?;
    let endpoint = directory.path().join("control");
    let mut listener = OwnerLocalListener::bind(&endpoint).await?;
    timeout(Duration::from_secs(3), async {
        let (server, mut client) = tokio::try_join!(
            async { listener.accept().await?.authenticate().await },
            OwnerLocalStream::connect(&endpoint),
        )?;
        let mut server = server;
        client.write_all(b"request").await?;
        let mut request = [0; 7];
        server.read_exact(&mut request).await?;
        assert_eq!(&request, b"request");
        server.write_all(b"response").await?;
        let mut response = [0; 8];
        client.read_exact(&mut response).await?;
        assert_eq!(&response, b"response");
        Ok(())
    })
    .await?
}

#[tokio::test]
async fn live_owner_local_listener_cannot_be_replaced() -> io::Result<()> {
    let directory = tempfile::TempDir::new()?;
    let endpoint = directory.path().join("control");
    let mut listener = OwnerLocalListener::bind(&endpoint).await?;
    assert!(OwnerLocalListener::bind(&endpoint).await.is_err());
    let (_server, _client) = tokio::try_join!(
        async { listener.accept().await?.authenticate().await },
        OwnerLocalStream::connect(&endpoint),
    )?;
    assert!(OwnerLocalListener::bind(&endpoint).await.is_err());
    Ok(())
}
