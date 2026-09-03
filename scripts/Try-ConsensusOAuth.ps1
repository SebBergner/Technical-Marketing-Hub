<#
.SYNOPSIS
    Walk the Consensus OAuth 2.0 flow by hand, one step at a time.

.DESCRIPTION
    Depends on nothing in this repo -- no Python, no application, no running
    server. It exists so the OAuth flow can be reproduced independently of our
    code, which matters when the question is "is it them or us".

    The authorization code is single-use and expires in seconds, so sending the
    POST on its own is a race. This does the whole loop: generate PKCE, print
    the authorize URL, wait while you approve in a browser, then exchange
    immediately with the verifier it just generated.

    Everything it sends and receives is printed. Nothing is stored.

.PARAMETER ClientId
    From Integrations > Access Credentials.

.PARAMETER ClientSecret
    Prompted for if omitted, so it stays out of your shell history.

.PARAMETER RedirectUri
    Must match the Callback URL on the credential set, character for character.

.EXAMPLE
    .\scripts\Try-ConsensusOAuth.ps1 -ClientId 3f1d8cd80dcaea0a3b3bcad6a9a38f8b

.EXAMPLE
    # Skip straight to the exchange, with a code you already have:
    .\scripts\Try-ConsensusOAuth.ps1 -ClientId <id> -Code <code> -CodeVerifier <verifier>
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ClientId,
    [string]$ClientSecret,
    [string]$RedirectUri = "http://localhost:8000/api/consensus/oauth/callback",
    [string]$Scopes = "public:api:read read:read",
    [string]$BaseUrl = "https://app.goconsensus.com",
    [string]$Code,
    [string]$CodeVerifier
)

$ErrorActionPreference = "Stop"
$oauth = "$BaseUrl/api/auth/v1.0/oauth2"
$rule = "-" * 74
function Head($t) { Write-Host "`n$rule`n$t`n$rule" }

function ConvertTo-Base64Url([byte[]]$bytes) {
    [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

if (-not $ClientSecret) {
    # Read-Host -AsSecureString keeps it off the screen and out of history.
    $secure = Read-Host "Client secret" -AsSecureString
    $ClientSecret = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
}

# ------------------------------------------------- steps 2.1 and 2.2
if (-not $Code) {
    Head "STEP 2.1  Generate PKCE"

    $verifierBytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($verifierBytes)
    $CodeVerifier = ConvertTo-Base64Url $verifierBytes

    $sha = [Security.Cryptography.SHA256]::Create()
    $challenge = ConvertTo-Base64Url $sha.ComputeHash(
        [Text.Encoding]::ASCII.GetBytes($CodeVerifier))

    $stateBytes = New-Object byte[] 12
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($stateBytes)
    $state = ConvertTo-Base64Url $stateBytes

    Write-Host "  code_verifier   $CodeVerifier"
    Write-Host "  code_challenge  $challenge"
    Write-Host "  state           $state"

    Head "STEP 2.2  Open this in a browser and approve"

    # The guide's example encodes the scope separator as %20, so match it.
    $url = "$oauth/authorize?response_type=code" +
           "&client_id=$ClientId" +
           "&redirect_uri=$([Uri]::EscapeDataString($RedirectUri))" +
           "&scope=$([Uri]::EscapeDataString($Scopes).Replace('+','%20'))" +
           "&state=$state" +
           "&code_challenge=$challenge" +
           "&code_challenge_method=S256"
    Write-Host $url -ForegroundColor Cyan

    Head "STEP 2.3  Paste the URL you land on"
    Write-Host "  The page itself may show an error -- ignore it. Only the"
    Write-Host "  address bar matters. Codes expire fast, so be quick.`n"
    $landed = Read-Host "Redirect URL"

    if ($landed -notmatch 'code=([^&]+)') {
        Write-Host "`n  No `code=` in that URL." -ForegroundColor Red
        if ($landed -match 'error=([^&]+)') {
            Write-Host "  Consensus refused it: $($Matches[1])" -ForegroundColor Red
        }
        exit 1
    }
    $Code = [Uri]::UnescapeDataString($Matches[1])

    if ($landed -match 'state=([^&]+)') {
        $returned = [Uri]::UnescapeDataString($Matches[1])
        if ($returned -ne $state) {
            # Abort rather than continue: a mismatched state is the CSRF case
            # the parameter exists to catch.
            Write-Host "`n  STATE MISMATCH - aborting." -ForegroundColor Red
            Write-Host "    sent     $state"
            Write-Host "    returned $returned"
            exit 1
        }
        Write-Host "  state matches" -ForegroundColor Green
    }
}

# --------------------------------------------------------- step 3
Head "STEP 3  Exchange the code for tokens"

$body = @{
    grant_type    = "authorization_code"
    code          = $Code
    redirect_uri  = $RedirectUri
    client_id     = $ClientId
    client_secret = $ClientSecret
    code_verifier = $CodeVerifier
}
foreach ($k in "grant_type", "code", "redirect_uri", "client_id", "code_verifier") {
    Write-Host ("  {0,-14} {1}" -f $k, $body[$k])
}
Write-Host ("  {0,-14} {1} chars, starts {2}" -f "client_secret",
            $ClientSecret.Length, $ClientSecret.Substring(0, [Math]::Min(7, $ClientSecret.Length)))

try {
    $tokens = Invoke-RestMethod -Method POST -Uri "$oauth/token" -Body $body `
        -ContentType "application/x-www-form-urlencoded"

    Write-Host "`n  SUCCESS" -ForegroundColor Green
    Write-Host "    token_type    $($tokens.token_type)"
    Write-Host "    expires_in    $($tokens.expires_in)s"
    Write-Host "    access_token  $($tokens.access_token.Substring(0,40))..."
    Write-Host "    refresh_token $($tokens.refresh_token.Substring(0,20))..."

    Head "STEP 4  Call the API with it"
    Write-Host "  Note the `platform` header: it is REQUIRED and appears in"
    Write-Host "  neither the OpenAPI spec nor the OAuth guide. Without it a"
    Write-Host "  valid token is rejected as 'Token header is invalid'.`n"
    $demos = Invoke-RestMethod -Uri "$BaseUrl/api/v2/demos/search?pageSize=5" `
        -Headers @{ Authorization = "Bearer $($tokens.access_token)"
                    platform      = "developer-platform" }
    Write-Host "  /api/v2/demos/search returned $($demos.data.items.Count) demos" -ForegroundColor Green
    foreach ($d in $demos.data.items) {
        Write-Host ("    {0}  tags: {1}" -f $d.title, ($d.tags -join ', '))
    }

    Head "Put these in .env"
    Write-Host "  CONSENSUS_V2_TOKEN=$($tokens.access_token)"
    Write-Host "`n  (or let the app hold the refresh token by authorising at"
    Write-Host "   /api/consensus/oauth/start once this works)"
}
catch {
    $status = $_.Exception.Response.StatusCode.value__
    Write-Host "`n  FAILED - HTTP $status" -ForegroundColor Red
    try {
        $raw = (New-Object IO.StreamReader(
            $_.Exception.Response.GetResponseStream())).ReadToEnd()
        Write-Host "  $raw"
        if ($raw -match 'invalid_client') {
            Write-Host "`n  >>> 'invalid_client' means client authentication failed," -ForegroundColor Yellow
            Write-Host "      NOT that the code was bad (that would be 'invalid_grant')."
            Write-Host "      The secret is being rejected before the code is read."
            Write-Host "      See Consensus_Support_OAuth_Client_Secret.md."
        }
    } catch {
        Write-Host "  $($_.Exception.Message)"
    }
    exit 1
}
