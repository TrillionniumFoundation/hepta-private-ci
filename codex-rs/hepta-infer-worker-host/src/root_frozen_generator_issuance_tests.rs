use super::*;
use std::time::Duration;
use tokio::time::timeout;

#[tokio::test]
async fn waiting_same_agent_keeps_other_agents_slot_available() -> Result<()> {
    let first = AgentId::parse("11111111-1111-4111-8111-111111111111")?;
    let second = AgentId::parse("22222222-2222-4222-8222-222222222222")?;
    let gates = IssuanceGates::new(
        [first.clone(), second.clone()].into_iter(),
        /*capacity*/ 2,
    )?;
    let active = gates.acquire(&first).await?;
    let mut waiting = Box::pin(gates.acquire(&first));
    assert!(
        timeout(Duration::from_millis(/*millis*/ 10), &mut waiting)
            .await
            .is_err()
    );
    let other = timeout(Duration::from_secs(/*secs*/ 1), gates.acquire(&second)).await??;
    drop(active);
    let resumed = timeout(Duration::from_secs(/*secs*/ 1), waiting).await??;
    drop(resumed);
    drop(other);
    Ok(())
}

#[tokio::test]
async fn original_global_capacity_still_bounds_distinct_agents() -> Result<()> {
    let first = AgentId::parse("11111111-1111-4111-8111-111111111111")?;
    let second = AgentId::parse("22222222-2222-4222-8222-222222222222")?;
    let gates = IssuanceGates::new(
        [first.clone(), second.clone()].into_iter(),
        /*capacity*/ 1,
    )?;
    let active = gates.acquire(&first).await?;
    let mut waiting = Box::pin(gates.acquire(&second));
    assert!(
        timeout(Duration::from_millis(/*millis*/ 10), &mut waiting)
            .await
            .is_err()
    );
    drop(active);
    let resumed = timeout(Duration::from_secs(/*secs*/ 1), waiting).await??;
    drop(resumed);
    Ok(())
}
