<#
.SYNOPSIS
    Generate a self-signed code signing certificate and export it for use in CI.

.DESCRIPTION
    Run this once on a Windows machine to create a self-signed code signing
    certificate. Exports a .pfx file and prints the base64-encoded value
    ready to paste into a GitHub secret.

.PARAMETER CertName
    CN for the certificate. Default: MergeMail365 Self-Signed

.PARAMETER PfxPath
    Path to export the .pfx file. Default: mergemail365-codesign.pfx

.PARAMETER PfxPassword
    Password for the .pfx file. Will prompt if not provided.

.EXAMPLE
    .\scripts\generate-cert.ps1
    .\scripts\generate-cert.ps1 -PfxPassword "mysecret"
#>

[CmdletBinding()]
param(
    [string]$CertName = "MergeMail365 Self-Signed",
    [string]$PfxPath = "mergemail365-codesign.pfx",
    [string]$PfxPassword
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $PfxPassword) {
    $securePass = Read-Host "Enter a password for the .pfx file" -AsSecureString
} else {
    $securePass = ConvertTo-SecureString -String $PfxPassword -Force -AsPlainText
}

# Check for existing cert
$existing = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert |
    Where-Object { $_.Subject -eq "CN=$CertName" -and $_.NotAfter -gt (Get-Date) } |
    Sort-Object NotAfter -Descending |
    Select-Object -First 1

if ($existing) {
    Write-Host "Found existing certificate: $($existing.Thumbprint) (expires $($existing.NotAfter.ToString('yyyy-MM-dd')))"
    $cert = $existing
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
    Write-Host "Created certificate: $($cert.Thumbprint)"
    Write-Host "Expires: $($cert.NotAfter.ToString('yyyy-MM-dd'))"
}

# Export pfx
Export-PfxCertificate -Cert "Cert:\CurrentUser\My\$($cert.Thumbprint)" `
    -FilePath $PfxPath -Password $securePass | Out-Null
Write-Host ""
Write-Host "Exported to: $PfxPath"

# Base64 encode for GitHub secrets
$bytes = [System.IO.File]::ReadAllBytes((Resolve-Path $PfxPath))
$base64 = [Convert]::ToBase64String($bytes)

Write-Host ""
Write-Host "============================================"
Write-Host "Add these GitHub secrets (Settings > Secrets):"
Write-Host "============================================"
Write-Host ""
Write-Host "  WINDOWS_CERTIFICATE_PWD = <the password you entered>"
Write-Host ""
Write-Host "  WINDOWS_CERTIFICATE = (base64 value copied to clipboard)"
Write-Host ""

# Copy to clipboard
$base64 | Set-Clipboard
Write-Host "The base64-encoded certificate has been copied to your clipboard."
Write-Host "Paste it as the value of the WINDOWS_CERTIFICATE secret."
Write-Host ""
Write-Host "IMPORTANT: Keep $PfxPath safe or delete it after adding the secret."
Write-Host "           Do NOT commit it to the repository."
