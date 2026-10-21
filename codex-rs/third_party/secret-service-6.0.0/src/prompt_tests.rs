use super::handle_signal;
use crate::Error;
use crate::proxy::prompt::Completed;
use zbus::Message;
use zbus::Variant;

#[test]
fn disconnected_prompt_does_not_report_acceptance() {
    assert!(matches!(
        handle_signal(None),
        Err(Error::PromptDisconnected)
    ));
}

#[test]
fn dismissed_prompt_retains_the_access_error() -> Result<(), Box<dyn std::error::Error>> {
    let message = Message::signal(
        "/org/freedesktop/secrets/prompt/fixture",
        "org.freedesktop.Secret.Prompt",
        "Completed",
    )
    .build(&(true, Variant::from(42_u32)))?;
    let completed = Completed::from_message(message).ok_or("invalid signal fixture")?;
    assert!(matches!(handle_signal(Some(completed)), Err(Error::Prompt)));
    Ok(())
}

#[test]
fn accepted_prompt_preserves_its_result() -> Result<(), Box<dyn std::error::Error>> {
    let message = Message::signal(
        "/org/freedesktop/secrets/prompt/fixture",
        "org.freedesktop.Secret.Prompt",
        "Completed",
    )
    .build(&(false, Variant::from(42_u32)))?;
    let completed = Completed::from_message(message).ok_or("invalid signal fixture")?;
    let result = handle_signal(Some(completed))?;
    assert!(matches!(u32::try_from(result), Ok(42)));
    Ok(())
}

#[test]
fn malformed_prompt_payload_remains_an_error() -> Result<(), Box<dyn std::error::Error>> {
    let message = Message::signal(
        "/org/freedesktop/secrets/prompt/fixture",
        "org.freedesktop.Secret.Prompt",
        "Completed",
    )
    .build(&"malformed prompt payload")?;
    let completed = Completed::from_message(message).ok_or("invalid signal fixture")?;
    assert!(matches!(
        handle_signal(Some(completed)),
        Err(Error::Zbus(_))
    ));
    Ok(())
}
