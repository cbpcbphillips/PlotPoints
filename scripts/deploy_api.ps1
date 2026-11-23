<#
.SYNOPSIS
  Build the API image and deploy it to Google Cloud Run (docs/deploy.md, section 3).

.DESCRIPTION
  Reads its settings from the environment or from .env:
    GCP_PROJECT                 your Google Cloud project id             (required)
    GCP_REGION                  e.g. us-central1                         (default us-central1)
    AWS_S3_BUCKET, AWS_REGION   where the inbox lives                    (required / default us-east-1)
    PLOTPOINTS_CORS_ORIGINS     the site address(es), comma-separated    (required)
  The three secrets must already exist in Secret Manager (docs/deploy.md, step 2):
    inbox-access-key-id, inbox-secret-access-key, tmdb-api-key

  Use -DryRun to see every command without running any of them. -SkipBuild reuses the image
  already built by `just api-build`.
#>
param([switch]$DryRun, [switch]$SkipBuild)
$ErrorActionPreference = 'Stop'

function Get-Setting([string]$Name, [string]$Default = '') {
  $v = [Environment]::GetEnvironmentVariable($Name)
  if ($v) { return $v }
  if (Test-Path .env) {
    $m = Select-String -Path .env -Pattern ("^\s*" + $Name + "\s*=\s*(.*)$") | Select-Object -First 1
    if ($m) {
      $val = $m.Matches[0].Groups[1].Value.Trim().Trim('"').Trim("'")
      if ($val) { return $val }
    }
  }
  return $Default
}

function Invoke-Step([string]$Label, [string]$Exe, [string[]]$Arguments) {
  Write-Host ""
  Write-Host "==> $Label" -ForegroundColor Cyan
  Write-Host ("    " + $Exe + " " + ($Arguments -join ' '))
  if ($DryRun) { return }
  # Windows PowerShell 5.1 turns text a native program writes to stderr (gcloud's progress lines)
  # into an error when $ErrorActionPreference is 'Stop', so these run with 'Continue' and the exit
  # code decides. gcloud.cmd avoids the gcloud.ps1 wrapper.
  $native = if ($Exe -eq 'gcloud') { 'gcloud.cmd' } else { $Exe }
  $previous = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try { & $native @Arguments } finally { $ErrorActionPreference = $previous }
  if ($LASTEXITCODE -ne 0) { throw "$Label failed (exit code $LASTEXITCODE)." }
}

$project = Get-Setting 'GCP_PROJECT'
$region  = Get-Setting 'GCP_REGION' 'us-central1'
$bucket  = Get-Setting 'AWS_S3_BUCKET'
$awsReg  = Get-Setting 'AWS_REGION' 'us-east-1'
$cors    = Get-Setting 'PLOTPOINTS_CORS_ORIGINS'
$service = Get-Setting 'GCP_SERVICE' 'plotpoints-api'

$missing = @()
if (-not $project) { $missing += 'GCP_PROJECT' }
if (-not $bucket)  { $missing += 'AWS_S3_BUCKET' }
if (-not $cors)    { $missing += 'PLOTPOINTS_CORS_ORIGINS' }
if ($missing.Count -gt 0) {
  if ($DryRun) { Write-Warning ("Not set (a real run needs them): " + ($missing -join ', ')) }
  else { throw ("Set these in .env or the environment first: " + ($missing -join ', ')) }
}
# winget installs gcloud per user, and a terminal opened before that does not have it on PATH yet.
if (-not (Get-Command gcloud.cmd -ErrorAction SilentlyContinue)) {
  $sdk = Join-Path $env:LOCALAPPDATA 'Google\Cloud SDK\google-cloud-sdk\bin'
  if (Test-Path (Join-Path $sdk 'gcloud.cmd')) { $env:PATH = "$sdk;$env:PATH" }
}
foreach ($tool in 'docker', 'gcloud.cmd') {
  if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
    if ($DryRun) { Write-Warning "$tool is not installed (a real run needs it)." }
    else { throw "$tool is not installed or not on PATH." }
  }
}

$image = "$region-docker.pkg.dev/$project/plotpoints/api:latest"

if (-not $SkipBuild) { Invoke-Step 'Build the snapshot and image' 'just' @('api-build') }
Invoke-Step 'Let Docker push to Artifact Registry' 'gcloud' @('auth', 'configure-docker', "$region-docker.pkg.dev", '--quiet')
Invoke-Step 'Tag the image' 'docker' @('tag', 'plotpoints-api', $image)
Invoke-Step 'Push the image' 'docker' @('push', $image)

# The environment variables go in a small file rather than on the command line: gcloud.cmd runs
# through cmd.exe, which reads characters such as | and ^ in an argument as its own syntax, and the
# CORS value contains commas. None of these values is a secret; the secrets come from Secret Manager.
$envYaml = @"
PLOTPOINTS_INBOX: "s3"
AWS_S3_BUCKET: "$bucket"
AWS_REGION: "$awsReg"
PLOTPOINTS_CORS_ORIGINS: "$cors"
PLOTPOINTS_TRUSTED_PROXIES: "1"
"@
$envFile = Join-Path ([IO.Path]::GetTempPath()) ('plotpoints-env-' + [IO.Path]::GetRandomFileName() + '.yaml')
$secrets = 'INBOX_AWS_ACCESS_KEY_ID=inbox-access-key-id:latest,INBOX_AWS_SECRET_ACCESS_KEY=inbox-secret-access-key:latest,TMDB_API_KEY=tmdb-api-key:latest'
Write-Host ""
Write-Host "Environment for the service (also written to a temporary file):"
Write-Host $envYaml
try {
  if (-not $DryRun) { [IO.File]::WriteAllText($envFile, $envYaml) }
  Invoke-Step 'Deploy to Cloud Run' 'gcloud' @(
    'run', 'deploy', $service, '--image', $image, '--region', $region, '--project', $project,
    '--allow-unauthenticated', '--cpu', '1', '--memory', '1Gi', '--cpu-boost', '--concurrency', '20',
    '--timeout', '60', '--min-instances', '0', '--max-instances', '2',
    '--env-vars-file', $envFile, '--set-secrets', $secrets
  )
} finally {
  if (Test-Path $envFile) { Remove-Item $envFile -Force }
}

if (-not $DryRun) {
  $ErrorActionPreference = 'Continue'
  $url = (& gcloud.cmd run services describe $service --region $region --project $project --format 'value(status.url)' 2>$null)
  Write-Host ""
  Write-Host "Deployed: $url" -ForegroundColor Green
  Write-Host "Next: put it in .env as PLOTPOINTS_API_URL=$url, build the site with it, then run: just status"
} else {
  Write-Host ""
  Write-Host "Dry run only: nothing was built, pushed or deployed." -ForegroundColor Yellow
}
