<#
.SYNOPSIS
    Generate a self-signed code signing certificate and sign the PyInstaller bundle.

.DESCRIPTION
    This script creates a self-signed certificate (if one doesn't already exist),
    then signs all executables, DLLs, and .pyd files in the PyInstaller output
    directory. Intended for Windows 10+ with PowerShell 5.1+.

    The certificate is stored in Cert:\CurrentUser\My and optionally exported
    as a .pfx file for reuse (e.g. in CI).

.PARAMETER BundlePath
    Path to the PyInstaller output directory. Default: dist\mergemail365

.PARAMETER CertName
    CN for the self-signed certificate. Default: MergeMail365 Self-Signed

.PARAMETER PfxPath
    Path to export the .pfx file. If omitted, the certificate is not exported.

.PARAMETER PfxPassword
    Password for the exported .pfx file. Required if PfxPath is specified.

.PARAMETER ImportPfx
    Path to an existing .pfx to import instead of generating a new certificate.

.PARAMETER TimestampServer
    RFC 3161 timestamp server URL. Default: http://timestamp.digicert.com

.EXAMPLE
    # Generate cert and sign the bundle
    .\scripts\sign-windows.ps1

.EXAMPLE
    # Generate cert, export it, and sign
    .\scripts\sign-windows.ps1 -PfxPath cert.pfx -PfxPassword "secret"

.EXAMPLE
    # Import existing pfx and sign
    .\scripts\sign-windows.ps1 -ImportPfx cert.pfx -PfxPassword "secret"
#>

[CmdletBinding()]
param(
    [string]$BundlePath = "dist\mergemail365",
    [string]$CertName = "MergeMail365 Self-Signed",
    [string]$PfxPath,
    [string]$PfxPassword,
    [string]$ImportPfx,
    [string]$TimestampServer = "http://timestamp.digicert.com"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# --- Locate signtool.exe ---
$signtool = Get-Command signtool.exe -ErrorAction SilentlyContinue
if (-not $signtool) {
    # Search Windows SDK paths
    $sdkPaths = Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\bin\10.*\x64\signtool.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending
    if ($sdkPaths) {
        $signtool = $sdkPaths[0].FullName
        Write-Host "Found signtool at: $signtool"
    } else {
        Write-Error "signtool.exe not found. Install the Windows SDK (Signing Tools component)."
        exit 1
    }
} else {
    $signtool = $signtool.Source
}

# --- Validate bundle path ---
if (-not (Test-Path $BundlePath)) {
    Write-Error "Bundle directory not found: $BundlePath. Run PyInstaller first."
    exit 1
}

# --- Get or create certificate ---
if ($ImportPfx) {
    # Import existing pfx
    if (-not $PfxPassword) {
        Write-Error "-PfxPassword is required when using -ImportPfx"
        exit 1
    }
    if (-not (Test-Path $ImportPfx)) {
        Write-Error "PFX file not found: $ImportPfx"
        exit 1
    }
    Write-Host "Importing certificate from $ImportPfx..."
    $securePass = ConvertTo-SecureString -String $PfxPassword -Force -AsPlainText
    $cert = Import-PfxCertificate -FilePath $ImportPfx -CertStoreLocation Cert:\CurrentUser\My -Password $securePass
    Write-Host "Imported certificate: $($cert.Thumbprint)"
} else {
    # Check for existing cert
    $cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert |
        Where-Object { $_.Subject -eq "CN=$CertName" -and $_.NotAfter -gt (Get-Date) } |
        Sort-Object NotAfter -Descending |
        Select-Object -First 1

    if ($cert) {
        Write-Host "Using existing certificate: $($cert.Thumbprint) (expires $($cert.NotAfter.ToString('yyyy-MM-dd')))"
    } else {
        Write-Host "Creating self-signed code signing certificate..."
        $cert = New-SelfSignedCertificate `
            -Subject "CN=$CertName" `
            -Type CodeSigningCert `
            -CertStoreLocation Cert:\CurrentUser\My `
            -KeyExportPolicy Exportable `
            -HashAlgorithm SHA256 `
            -KeyLength 2048 `
            -KeyUsageProperty Sign `
            -KeyUsage DigitalSignature `
            -NotAfter (Get-Date).AddYears(3)
        Write-Host "Created certificate: $($cert.Thumbprint) (expires $($cert.NotAfter.ToString('yyyy-MM-dd')))"
    }

    # Export to pfx if requested
    if ($PfxPath) {
        if (-not $PfxPassword) {
            Write-Error "-PfxPassword is required when using -PfxPath"
            exit 1
        }
        $securePass = ConvertTo-SecureString -String $PfxPassword -Force -AsPlainText
        Export-PfxCertificate -Cert "Cert:\CurrentUser\My\$($cert.Thumbprint)" `
            -FilePath $PfxPath -Password $securePass | Out-Null
        Write-Host "Exported certificate to $PfxPath"
    }
}

# --- Sign all binaries ---
$files = Get-ChildItem $BundlePath -Include *.exe, *.dll, *.pyd -Recurse
$total = $files.Count
if ($total -eq 0) {
    Write-Error "No signable files found in $BundlePath"
    exit 1
}

Write-Host "Signing $total files in $BundlePath..."
$signed = 0
$failed = 0

foreach ($file in $files) {
    $relativePath = $file.FullName.Substring((Resolve-Path $BundlePath).Path.Length + 1)
    try {
        & $signtool sign /sha1 $cert.Thumbprint `
            /fd sha256 /tr $TimestampServer /td sha256 `
            $file.FullName 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "signtool returned exit code $LASTEXITCODE"
        }
        $signed++
    } catch {
        Write-Warning "Failed to sign ${relativePath}: $_"
        $failed++
    }
}

Write-Host ""
Write-Host "Signing complete: $signed succeeded, $failed failed out of $total files."

# --- Verify main executable ---
$mainExe = Join-Path $BundlePath "mergemail365.exe"
if (Test-Path $mainExe) {
    Write-Host ""
    Write-Host "Verifying mergemail365.exe..."
    & $signtool verify /pa $mainExe
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Signature verification failed for mergemail365.exe"
    }
}

if ($failed -gt 0) {
    exit 1
} else {
    exit 0
}
