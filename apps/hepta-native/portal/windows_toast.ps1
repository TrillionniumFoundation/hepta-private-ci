$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$appId = $env:HEPTA_NOTIFICATION_AUMID
$title = $env:HEPTA_NOTIFICATION_TITLE
$body = $env:HEPTA_NOTIFICATION_BODY
if ([string]::IsNullOrWhiteSpace($appId)) { throw 'registered AppUserModelID is missing' }
if ($null -eq $title) { $title = '' }
if ($null -eq $body) { $body = '' }

Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
[Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null

$escapedTitle = [Security.SecurityElement]::Escape($title)
$escapedBody = [Security.SecurityElement]::Escape($body)
$xml = @"
<toast>
  <visual>
    <binding template="ToastGeneric">
      <text>$escapedTitle</text>
      <text>$escapedBody</text>
    </binding>
  </visual>
</toast>
"@
$document = New-Object Windows.Data.Xml.Dom.XmlDocument
$document.LoadXml($xml)
$toast = [Windows.UI.Notifications.ToastNotification]::new($document)
$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId)
$notifier.Show($toast)
