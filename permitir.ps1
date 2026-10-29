$ErrorActionPreference = "Continue"
netsh advfirewall firewall delete rule name=Lazo | Out-Null
netsh advfirewall firewall add rule name=Lazo dir=in action=allow protocol=TCP localport=8787 profile=any | Out-Null
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (Test-Path $python) {
  netsh advfirewall firewall add rule name=Lazo dir=in action=allow program="$python" enable=yes profile=any | Out-Null
}
Get-NetConnectionProfile | ForEach-Object {
  try { Set-NetConnectionProfile -InterfaceIndex $_.InterfaceIndex -NetworkCategory Private } catch {}
}
foreach ($store in @("Cert:\LocalMachine\Root", "Cert:\CurrentUser\Root")) {
  Get-ChildItem $store -ErrorAction SilentlyContinue |
    Where-Object { $_.Subject -like "*Lazo CA*" } |
    Remove-Item -Force -ErrorAction SilentlyContinue
}
