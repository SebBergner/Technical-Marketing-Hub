<#
.SYNOPSIS
    Independent read-only check of the Entra ID app's access to SharePoint.

.DESCRIPTION
    Deliberately depends on NOTHING in this repo -- no Python, no backend code.
    It talks to Entra ID and Microsoft Graph directly, so it can confirm or
    contradict what scripts/check_graph.py reports rather than repeating it.

    READ-ONLY. Only GETs, plus the token request. Nothing is created, modified
    or deleted in SharePoint.

    It answers four questions in order, because a later one cannot be trusted
    until the earlier one passes:

      1. Do the credentials work at all?          (token request)
      2. Has any Graph permission been consented? (the token's roles claim)
      3. Can we see the site?                     (step 2 of Sites.Selected)
      4. Is the grant read or write?              (per-site permission list)

    Question 2 is the one worth having. An app with no consented permission
    still receives a perfectly valid token and then fails every call with 401,
    and Graph's own error for that is "General exception while processing" --
    which names nothing. The empty roles claim is the only honest signal.

.PARAMETER EnvFile
    Path to a .env holding GRAPH_*. Defaults to the repo root .env.

.EXAMPLE
    .\scripts\Check-GraphAccess.ps1

.EXAMPLE
    .\scripts\Check-GraphAccess.ps1 -TenantId <guid> -ClientId <guid> -ClientSecret <secret>
#>
[CmdletBinding()]
param(
    [string]$EnvFile,
    [string]$TenantId,
    [string]$ClientId,
    [string]$ClientSecret,
    [string]$SiteUrl,
    [string]$LibraryName
)

$ErrorActionPreference = "Stop"

# --------------------------------------------------- configuration
if (-not $EnvFile) {
    $EnvFile = Join-Path (Split-Path -Parent $PSScriptRoot) ".env"
}
if ((Test-Path $EnvFile) -and -not $ClientSecret) {
    Get-Content $EnvFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $k = $line.Substring(0, $line.IndexOf("="))
            $v = $line.Substring($line.IndexOf("=") + 1)
            switch ($k) {
                "GRAPH_TENANT_ID"     { if (-not $TenantId)     { $TenantId = $v } }
                "GRAPH_CLIENT_ID"     { if (-not $ClientId)     { $ClientId = $v } }
                "GRAPH_CLIENT_SECRET" { if (-not $ClientSecret) { $ClientSecret = $v } }
                "GRAPH_SITE_URL"      { if (-not $SiteUrl)      { $SiteUrl = $v } }
                "GRAPH_LIST_NAME"     { if (-not $LibraryName)  { $LibraryName = $v } }
            }
        }
    }
}
if (-not $LibraryName) { $LibraryName = "Demo Catalog" }

$rule = "-" * 74
function Head($text) { Write-Host "`n$rule`n$text`n$rule" }

Head "CONFIGURATION"
if (-not $TenantId -or -not $ClientId -or -not $ClientSecret -or -not $SiteUrl) {
    Write-Host "  Missing settings. Provide them as parameters or in $EnvFile" -ForegroundColor Red
    exit 1
}
Write-Host ("  tenant     {0}" -f $TenantId)
Write-Host ("  client     {0}" -f $ClientId)
Write-Host ("  secret     {0} chars ending ...{1}" -f $ClientSecret.Length, $ClientSecret.Substring($ClientSecret.Length - 4))
Write-Host ("  site       {0}" -f $SiteUrl)
Write-Host ("  library    {0}" -f $LibraryName)

# ----------------------------------------------- 1. do credentials work
Head "1. CREDENTIALS  (can we get a token at all?)"
try {
    $resp = Invoke-RestMethod -Method POST `
        -Uri "https://login.microsoftonline.com/$TenantId/oauth2/v2.0/token" `
        -Body @{
            client_id     = $ClientId
            client_secret = $ClientSecret
            scope         = "https://graph.microsoft.com/.default"
            grant_type    = "client_credentials"
        }
    $token = $resp.access_token
    Write-Host "  token      OK  ($($token.Length) chars, valid $($resp.expires_in)s)" -ForegroundColor Green
} catch {
    Write-Host "  token      FAILED" -ForegroundColor Red
    Write-Host "  $($_.Exception.Message)"
    Write-Host "`n  >>> Wrong tenant id, client id or secret. This is step 0 -- no"
    Write-Host "      permission question arises until this passes."
    exit 1
}

# -------------------------------------- 2. has any permission been consented
Head "2. PERMISSIONS  (what does the token actually carry?)"
$payload = $token.Split(".")[1].Replace("-", "+").Replace("_", "/")
while ($payload.Length % 4) { $payload += "=" }
$claims = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($payload)) | ConvertFrom-Json

Write-Host ("  audience   {0}" -f $claims.aud)
Write-Host ("  app name   {0}" -f $claims.app_displayname)
Write-Host ("  tenant     {0}" -f $claims.tid)

$roles = @()
if ($claims.PSObject.Properties.Name -contains "roles") { $roles = @($claims.roles) }

if ($roles.Count -eq 0) {
    Write-Host "  roles      ABSENT" -ForegroundColor Red

    # Azure lists TWO APIs each exposing a permission named Sites.Selected.
    # Granting the SharePoint one looks identical in the portal but does
    # nothing for Graph, so name that case rather than reporting "none".
    $spRoles = @()
    try {
        $spTok = (Invoke-RestMethod -Method POST `
            -Uri "https://login.microsoftonline.com/$TenantId/oauth2/v2.0/token" `
            -Body @{
                client_id = $ClientId; client_secret = $ClientSecret
                scope = "https://$(([Uri]$SiteUrl).Host)/.default"
                grant_type = "client_credentials"
            }).access_token
        $sp = $spTok.Split(".")[1].Replace("-", "+").Replace("_", "/")
        while ($sp.Length % 4) { $sp += "=" }
        $spClaims = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($sp)) | ConvertFrom-Json
        if ($spClaims.PSObject.Properties.Name -contains "roles") { $spRoles = @($spClaims.roles) }
    } catch { }

    if ($spRoles.Count -gt 0) {
        Write-Host ("  legacy API {0}   <-- granted on the WRONG API" -f ($spRoles -join ", ")) -ForegroundColor Yellow
        Write-Host "`n  >>> The permission exists, but on the legacy SharePoint API rather"
        Write-Host "      than on Microsoft Graph. Azure lists two APIs that each expose a"
        Write-Host "      permission named Sites.Selected, and the portal shows a green"
        Write-Host "      'Granted' either way. This app calls Graph, so it gets nothing."
        Write-Host "`n      Ask IT: API permissions > Add a permission > MICROSOFT GRAPH >"
        Write-Host "      Application permissions > Sites.Selected > Grant admin consent."
        Write-Host "      The per-site grant is a separate step and is also still needed."
        exit 1
    }

    Write-Host "`n  >>> The token is valid but carries NO application permissions."
    Write-Host "      The app registration exists and the secret is correct, but nobody"
    Write-Host "      has consented to a Graph permission for it. Every call will 401,"
    Write-Host "      and Graph's own message for that says nothing useful."
    Write-Host "`n      Ask IT: API permissions > Add > Microsoft Graph >"
    Write-Host "      APPLICATION permissions > Sites.Selected > Grant admin consent."
    Write-Host "      Then the per-site grant, which is a separate step."
    exit 1
}
Write-Host ("  roles      {0}" -f ($roles -join ", ")) -ForegroundColor Green
if ($roles -notcontains "Sites.Selected") {
    Write-Host "`n  Note: Sites.Selected is not among them. If a broader permission such"
    Write-Host "  as Sites.ReadWrite.All was granted instead, access will work but is"
    Write-Host "  wider than this app needs."
}

# -------------------------------------------- 3. can we reach the site
Head "3. SITE ACCESS  (step 2 of the Sites.Selected grant)"
$hostName = ([Uri]$SiteUrl).Host
$sitePath = ([Uri]$SiteUrl).AbsolutePath.Trim("/")
$headers  = @{ Authorization = "Bearer $token" }

try {
    $site = Invoke-RestMethod -Headers $headers `
        -Uri "https://graph.microsoft.com/v1.0/sites/${hostName}:/${sitePath}"
    Write-Host "  site       OK  $($site.displayName)" -ForegroundColor Green
    Write-Host "  siteId     $($site.id)"
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    Write-Host "  site       FAILED (HTTP $code)" -ForegroundColor Red
    if ($code -eq 403) {
        Write-Host "`n  >>> Permission consented, but this app has no grant on THIS site."
        Write-Host "      That is step 2, and it cannot be done in the portal UI:"
        Write-Host "        POST /v1.0/sites/{siteId}/permissions"
        Write-Host '        { "roles": ["write"], "grantedToIdentities": [ ... ] }'
    } else {
        Write-Host "`n  >>> Unexpected. Check the site URL is exactly right --"
        Write-Host "      note the host is ptccloud.sharepoint.com, not ptc.sharepoint.com."
    }
    exit 1
}

# -------------------------------------------- 4. read or write?
Head "4. GRANT LEVEL  (read is enough to sync; write is needed to write back)"
try {
    $perms = Invoke-RestMethod -Headers $headers `
        -Uri "https://graph.microsoft.com/v1.0/sites/$($site.id)/permissions"
    $granted = @($perms.value | ForEach-Object { $_.roles } | Sort-Object -Unique)
    if ($granted.Count -eq 0) {
        Write-Host "  grants     none listed"
    } elseif ($granted -contains "write") {
        Write-Host ("  grants     {0}" -f ($granted -join ", ")) -ForegroundColor Green
        Write-Host "`n  >>> Fully configured. Sync and write-back will both work."
    } else {
        Write-Host ("  grants     {0}  (no write)" -f ($granted -join ", ")) -ForegroundColor Yellow
        Write-Host "`n  >>> Read-only. Catalogue sync will work; write-back will not."
        Write-Host "      Ask IT to raise the per-site grant to 'write'."
    }
} catch {
    Write-Host "  grants     could not list (needs Sites.FullControl.All to read)"
    Write-Host "             Inconclusive -- but the site resolved, so a grant exists."
}

# -------------------------------------------- 5. the library and its columns
Head "5. LIBRARY  (is 'Demo Catalog' there, and does ConsensusUUID exist?)"
try {
    $drives = Invoke-RestMethod -Headers $headers `
        -Uri "https://graph.microsoft.com/v1.0/sites/$($site.id)/drives"
    foreach ($d in $drives.value) {
        $mark = ""
        if ($d.name -eq $LibraryName) { $mark = "   <- target" }
        Write-Host ("  {0}{1}" -f $d.name, $mark)
    }
    $target = $drives.value | Where-Object { $_.name -eq $LibraryName } | Select-Object -First 1
    if (-not $target) {
        Write-Host "`n  '$LibraryName' not found among the libraries above." -ForegroundColor Yellow
        exit 0
    }

    $list = Invoke-RestMethod -Headers $headers `
        -Uri "https://graph.microsoft.com/v1.0/drives/$($target.id)/list?`$expand=columns"
    $uuidCol = $list.columns | Where-Object {
        $_.name -replace "_x0020_", "" -replace " ", "" -match "^(?i)consensus(demo)?uuid$" -or
        $_.displayName -replace " ", "" -match "^(?i)consensus(demo)?uuid$"
    } | Select-Object -First 1

    Write-Host ""
    if ($uuidCol) {
        Write-Host "  ConsensusUUID column exists, internal name: $($uuidCol.name)" -ForegroundColor Green
    } else {
        Write-Host "  ConsensusUUID column NOT found." -ForegroundColor Yellow
        Write-Host "  Add a single-line text column to the library before write-back."
    }
} catch {
    Write-Host "  Could not list libraries: $($_.Exception.Message)" -ForegroundColor Yellow
}

Head "DONE -- nothing was created or modified"
