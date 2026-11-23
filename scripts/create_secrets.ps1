<#
.SYNOPSIS
  Put the API's three secrets into Google Secret Manager, from your local .env (docs/deploy.md).

.DESCRIPTION
  Reads these from .env and stores each as a secret, without ever printing a value:
    INBOX_AWS_ACCESS_KEY_ID      -> secret inbox-access-key-id
    INBOX_AWS_SECRET_ACCESS_KEY  -> secret inbox-secret-access-key
    TMDB_API_KEY                 -> secret tmdb-api-key
  If a secret already exists it gets a new version. Then it lets the Cloud Run service account read
  exactly these three secrets and nothing else in Secret Manager.

  A value is written to a temporary file for a moment (gcloud reads it from there, and a pipe would
  add a stray line ending to the secret) and the file is deleted straight afterwards.

  -DryRun shows what would happen, with names only. Needs: gcloud signed in, GCP_PROJECT in .env.
#>
param([switch]$DryRun)
$ErrorActionPreference = 'Stop'

$sdk = Join-Path $env:LOCALAPPDATA 'Google\Cloud SDK\google-cloud-sdk\bin'
if (-not (Get-Command gcloud.cmd -ErrorAction SilentlyContinue) -and (Test-Path (Join-Path $sdk 'gcloud.cmd'))) {
  $env:PATH = "$sdk;$env:PATH"
}

# Windows PowerShell 5.1 turns any text a native program writes to stderr into an error when
# $ErrorActionPreference is 'Stop', even a harmless "not found" answer. So native calls run with
# 'Continue', and success is judged by the exit code. Returns @{ Code; Out } (gcloud never echoes
# a secret value, so the output is safe to show when something fails).
function Invoke-Gcloud {
  $previous = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try {
    $out = & gcloud.cmd @args 2>&1 | ForEach-Object { "$_" }
    return @{ Code = $LASTEXITCODE; Out = ($out -join "`n") }
  } finally { $ErrorActionPreference = $previous }
}

function Get-Setting([string]$Name) {
  $v = [Environment]::GetEnvironmentVariable($Name)
  if ($v) { return $v }
  if (Test-Path .env) {
    $m = Select-String -Path .env -Pattern ("^\s*" + $Name + "\s*=\s*(.*)$") | Select-Object -First 1
    if ($m) { return $m.Matches[0].Groups[1].Value.Trim().Trim('"').Trim("'") }
  }
  return ''
}

$project = Get-Setting 'GCP_PROJECT'
if (-not $project) { throw 'Set GCP_PROJECT in .env first.' }

$map = [ordered]@{
  'INBOX_AWS_ACCESS_KEY_ID'     = 'inbox-access-key-id'
  'INBOX_AWS_SECRET_ACCESS_KEY' = 'inbox-secret-access-key'
  'TMDB_API_KEY'                = 'tmdb-api-key'
}

Write-Host "Project: $project"
foreach ($key in $map.Keys) {
  $has = [bool](Get-Setting $key)
  Write-Host ("  {0,-30} -> {1,-26} {2}" -f $key, $map[$key], $(if ($has) { 'found in .env' } else { 'MISSING from .env' }))
  if (-not $has) { throw "$key is not in .env, so there is nothing to store." }
}
if ($DryRun) { Write-Host "`nDry run only: nothing was created." -ForegroundColor Yellow; return }

$r = Invoke-Gcloud projects describe $project --format 'value(projectNumber)'
if ($r.Code -ne 0) { throw "Could not read the project: $($r.Out)" }
$runtime = "$($r.Out.Trim())-compute@developer.gserviceaccount.com"

foreach ($key in $map.Keys) {
  $name = $map[$key]
  # does it exist already? (describe exits non-zero when it does not; no error is raised)
  $found = Invoke-Gcloud secrets describe $name --project $project --format 'value(name)'
  $exists = ($found.Code -eq 0)

  $tmp = Join-Path ([IO.Path]::GetTempPath()) ([IO.Path]::GetRandomFileName())
  try {
    [IO.File]::WriteAllText($tmp, (Get-Setting $key))
    if ($exists) {
      Write-Host "==> $name exists: adding a new version"
      $r = Invoke-Gcloud secrets versions add $name --data-file $tmp --project $project --quiet
    } else {
      Write-Host "==> creating $name"
      $r = Invoke-Gcloud secrets create $name --data-file $tmp --replication-policy automatic --project $project --quiet
    }
  } finally {
    if (Test-Path $tmp) { Remove-Item $tmp -Force }
  }
  if ($r.Code -ne 0) { throw "Storing $name failed: $($r.Out)" }

  $r = Invoke-Gcloud secrets add-iam-policy-binding $name --member "serviceAccount:$runtime" --role roles/secretmanager.secretAccessor --project $project --quiet
  if ($r.Code -ne 0) { throw "Could not let the Cloud Run service account read ${name}: $($r.Out)" }
}

Write-Host ""
Write-Host "Done. Secrets now in Secret Manager (names only):" -ForegroundColor Green
$r = Invoke-Gcloud secrets list --project $project --format 'value(name)'
Write-Host $r.Out
