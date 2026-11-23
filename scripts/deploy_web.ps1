<#
.SYNOPSIS
  Build the site against the live API and publish it to Cloudflare (docs/deploy.md, section 4).

.DESCRIPTION
  Settings, from the environment or .env:
    PLOTPOINTS_API_URL   the API address (the Cloud Run URL)           (required)
    VITE_FEEDBACK_URL    optional mailto: or form link for the footer
    VITE_ANALYTICS       set to true once Cloudflare Web Analytics is on
    CF_PAGES_PROJECT     the Cloudflare Pages project name             (default watchplotpoints)
  Leaves VITE_ADS unset: the free launch has no ads.

  Use -DryRun to see the commands without running them. Check first which deploy command
  Cloudflare's dashboard recommends for a new static site (Pages and Workers have been merging);
  this script uses `wrangler pages deploy`.
#>
param([switch]$DryRun)
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

$api = (Get-Setting 'PLOTPOINTS_API_URL').TrimEnd('/')
if (-not $api) {
  if ($DryRun) { Write-Warning 'PLOTPOINTS_API_URL is not set (a real run needs it).'; $api = 'https://API-ADDRESS' }
  else { throw 'Set PLOTPOINTS_API_URL in .env (the API address printed by the API deploy).' }
}
$project = Get-Setting 'CF_PAGES_PROJECT' 'watchplotpoints'
# Read every setting here, before moving into web/: Get-Setting looks for .env in the current
# folder, so a read made from inside web/ finds nothing and silently drops the flag.
$feedback = Get-Setting 'VITE_FEEDBACK_URL'
$analytics = Get-Setting 'VITE_ANALYTICS'

Write-Host "==> Build the site (VITE_API_URL=$api)" -ForegroundColor Cyan
Write-Host ("    feedback link: " + $(if ($feedback) { 'on' } else { 'off' }) + ", analytics note: " + $(if ($analytics) { $analytics } else { 'off' }))
if (-not $DryRun) {
  Push-Location web
  try {
    $env:VITE_API_URL = $api
    if ($feedback) { $env:VITE_FEEDBACK_URL = $feedback }
    if ($analytics) { $env:VITE_ANALYTICS = $analytics }
    Remove-Item Env:VITE_ADS -ErrorAction SilentlyContinue
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'The build failed.' }
    Write-Host "==> Publish to Cloudflare Pages ($project)" -ForegroundColor Cyan
    npx wrangler pages deploy dist --project-name $project
    if ($LASTEXITCODE -ne 0) { throw 'The publish failed.' }
  } finally { Pop-Location }
  Write-Host ""
  Write-Host "Published. Next: just status" -ForegroundColor Green
} else {
  Write-Host '    (in web/) npm run build   with VITE_API_URL, and optionally VITE_FEEDBACK_URL / VITE_ANALYTICS'
  Write-Host "    (in web/) npx wrangler pages deploy dist --project-name $project"
  Write-Host ''
  Write-Host 'Dry run only: nothing was built or published.' -ForegroundColor Yellow
}
