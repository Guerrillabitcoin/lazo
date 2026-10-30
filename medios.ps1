# LaZoo: lee qué suena en Windows (sesiones multimedia del sistema). Solo lectura.
# Escribe una línea JSON cada 1,5 s y se cierra solo si LaZoo se cierra.
param([int]$Parent = 0)
$ErrorActionPreference = 'Stop'
try {
  Add-Type -AssemblyName System.Runtime.WindowsRuntime
  $asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
  function Wait-Op($op, $type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); [void]$t.Wait(3000); $t.Result }
  $mgrType = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media.Control, ContentType = WindowsRuntime]
  $propType = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties, Windows.Media.Control, ContentType = WindowsRuntime]
  $mgr = Wait-Op ($mgrType::RequestAsync()) $mgrType
} catch {
  Write-Output '{"error":"sin sesiones multimedia"}'
  exit 1
}
while ($true) {
  if ($Parent -and -not (Get-Process -Id $Parent -ErrorAction SilentlyContinue)) { exit 0 }
  $rows = @()
  try {
    foreach ($s in $mgr.GetSessions()) {
      try {
        $p = Wait-Op ($s.TryGetMediaPropertiesAsync()) $propType
        $tl = $s.GetTimelineProperties()
        $pos = $tl.Position.TotalSeconds
        $st = [string]$s.GetPlaybackInfo().PlaybackStatus
        if ($st -eq 'Playing') { $pos += ((Get-Date).ToUniversalTime() - $tl.LastUpdatedTime.UtcDateTime).TotalSeconds }
        $rows += [pscustomobject]@{ app = [string]$s.SourceAppUserModelId; status = $st; title = [string]$p.Title; artist = [string]$p.Artist; pos = [math]::Round($pos, 1); len = [math]::Round($tl.EndTime.TotalSeconds, 1) }
      } catch {}
    }
  } catch {}
  $json = ConvertTo-Json -Compress -InputObject @($rows)
  [Console]::Out.WriteLine('{"sessions":' + $json + '}')
  [Console]::Out.Flush()
  Start-Sleep -Milliseconds 1500
}
