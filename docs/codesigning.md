# Code Signing

This documents how to sign the MergeMail365 bundles so users don't see OS security warnings (macOS Gatekeeper / Windows SmartScreen).

## macOS

### Prerequisites

- An [Apple Developer Program](https://developer.apple.com/programs/) membership ($99/year)
- A **Developer ID Application** certificate from the [Apple Developer portal](https://developer.apple.com/account/resources/certificates/list)
- An [app-specific password](https://support.apple.com/en-us/102654) for your Apple ID (used for notarization)

### Local signing

If you have the certificate in your keychain:

```bash
# Build the app
uv run pyinstaller mergemail365.spec

# Sign with hardened runtime (required for notarization)
codesign --deep --force --options runtime \
  --sign "Developer ID Application: Your Name (TEAMID)" \
  dist/MergeMail365.app

# Verify the signature
codesign --verify --deep --strict dist/MergeMail365.app
```

### Self-signing (no Apple Developer account)

If you don't have an Apple Developer account, you can create a self-signed certificate for local use. This avoids the "app is damaged" error for unsigned apps, but users will still see a Gatekeeper warning on first launch (they must right-click > Open, or allow it in System Settings > Privacy & Security). Notarization is not possible with self-signed certificates.

```bash
# Create a self-signed certificate in the login keychain
# (Keychain Access > Certificate Assistant > Create a Certificate can also do this)
security create-identity-preference -s "MergeMail365" -c "MergeMail365 Self-Signed"

# Or via the command line: create a self-signed code signing certificate
cat > /tmp/cert.cfg <<EOF
[ req ]
distinguished_name = req_dn
prompt = no
[ req_dn ]
CN = MergeMail365 Self-Signed
[ ext ]
keyUsage = digitalSignature
extendedKeyUsage = codeSigning
basicConstraints = CA:false
EOF

# Generate key and certificate, import into login keychain
openssl req -x509 -newkey rsa:2048 -keyout /tmp/ss-key.pem -out /tmp/ss-cert.pem \
  -days 365 -nodes -config /tmp/cert.cfg -extensions ext
openssl pkcs12 -export -out /tmp/ss-cert.p12 -inkey /tmp/ss-key.pem -in /tmp/ss-cert.pem -passout pass:
security import /tmp/ss-cert.p12 -k ~/Library/Keychains/login.keychain-db -P "" -T /usr/bin/codesign
rm /tmp/cert.cfg /tmp/ss-key.pem /tmp/ss-cert.pem /tmp/ss-cert.p12

# Sign the app with the self-signed certificate
codesign --deep --force --sign "MergeMail365 Self-Signed" dist/MergeMail365.app

# Verify
codesign --verify --deep dist/MergeMail365.app
```

To run the self-signed app on another Mac, the user must either:
- Right-click the app > **Open** (bypasses Gatekeeper for that app once), or
- Go to **System Settings > Privacy & Security** and click **Open Anyway** after the first blocked launch

### Notarization

Apple requires notarization for apps distributed outside the App Store. After signing:

```bash
# Create a zip for submission
ditto -c -k --sequesterRsrc --keepParent dist/MergeMail365.app dist/MergeMail365-notarize.zip

# Submit for notarization (uses app-specific password, not your main Apple ID password)
xcrun notarytool submit dist/MergeMail365-notarize.zip \
  --apple-id "your@email.com" \
  --password "app-specific-password" \
  --team-id "TEAMID" \
  --wait

# Staple the notarization ticket to the app
xcrun stapler staple dist/MergeMail365.app

# Clean up
rm dist/MergeMail365-notarize.zip
```

### CI signing (GitHub Actions)

To add code signing to the release workflow, add the following steps between the PyInstaller build and the archive step.

#### 1. Export your certificate

On your Mac, open Keychain Access, find your **Developer ID Application** certificate, and export it as a `.p12` file with a password.

Base64-encode it for storage as a GitHub secret:

```bash
base64 -i certificate.p12 | pbcopy
```

#### 2. Add GitHub secrets

Add these to the UCL environment (or repo-level secrets):

| Secret | Value |
|---|---|
| `MACOS_CERTIFICATE` | Base64-encoded `.p12` (from step 1) |
| `MACOS_CERTIFICATE_PWD` | Password used when exporting the `.p12` |
| `MACOS_KEYCHAIN_PWD` | Any random string (for the ephemeral CI keychain) |
| `CODESIGN_IDENTITY` | e.g. `Developer ID Application: Your Name (TEAMID)` |
| `APPLE_ID` | Your Apple ID email |
| `APPLE_ID_PWD` | An app-specific password (not your main password) |
| `APPLE_TEAM_ID` | Your 10-character Apple team ID |

#### 3. Add workflow steps

Add these steps to `.github/workflows/release.yml`:

**Before the build step** -- import the certificate into a temporary keychain:

```yaml
      - name: Import codesigning certificate
        if: runner.os == 'macOS'
        env:
          MACOS_CERTIFICATE: ${{ secrets.MACOS_CERTIFICATE }}
          MACOS_CERTIFICATE_PWD: ${{ secrets.MACOS_CERTIFICATE_PWD }}
          MACOS_KEYCHAIN_PWD: ${{ secrets.MACOS_KEYCHAIN_PWD }}
        run: |
          CERT_FILE=$(mktemp /tmp/cert.XXXXXX.p12)
          KEYCHAIN_FILE=$(mktemp /tmp/keychain.XXXXXX.keychain-db)
          echo "$MACOS_CERTIFICATE" | base64 --decode > "$CERT_FILE"
          security create-keychain -p "$MACOS_KEYCHAIN_PWD" "$KEYCHAIN_FILE"
          security set-keychain-settings -lut 21600 "$KEYCHAIN_FILE"
          security unlock-keychain -p "$MACOS_KEYCHAIN_PWD" "$KEYCHAIN_FILE"
          security import "$CERT_FILE" -P "$MACOS_CERTIFICATE_PWD" -A -t cert -f pkcs12 -k "$KEYCHAIN_FILE"
          security set-key-partition-list -S apple-tool:,apple: -k "$MACOS_KEYCHAIN_PWD" "$KEYCHAIN_FILE"
          security list-keychains -d user -s "$KEYCHAIN_FILE" login.keychain
          echo "KEYCHAIN_FILE=$KEYCHAIN_FILE" >> "$GITHUB_ENV"
          rm "$CERT_FILE"
```

**After the build step, before the archive step** -- sign, notarize, and staple:

```yaml
      - name: Codesign and notarize (macOS)
        if: runner.os == 'macOS'
        env:
          APPLE_ID: ${{ secrets.APPLE_ID }}
          APPLE_ID_PWD: ${{ secrets.APPLE_ID_PWD }}
          APPLE_TEAM_ID: ${{ secrets.APPLE_TEAM_ID }}
          CODESIGN_IDENTITY: ${{ secrets.CODESIGN_IDENTITY }}
        run: |
          # Sign all binaries inside the app bundle
          codesign --deep --force --options runtime \
            --sign "$CODESIGN_IDENTITY" \
            dist/MergeMail365.app

          # Create zip for notarization
          ditto -c -k --sequesterRsrc --keepParent dist/MergeMail365.app dist/MergeMail365-notarize.zip

          # Submit for notarization
          xcrun notarytool submit dist/MergeMail365-notarize.zip \
            --apple-id "$APPLE_ID" \
            --password "$APPLE_ID_PWD" \
            --team-id "$APPLE_TEAM_ID" \
            --wait

          # Staple the notarization ticket to the app
          xcrun stapler staple dist/MergeMail365.app
          rm dist/MergeMail365-notarize.zip
```

**After the upload step** -- clean up the temporary keychain:

```yaml
      - name: Clean up keychain
        if: runner.os == 'macOS' && always()
        run: |
          if [ -n "$KEYCHAIN_FILE" ]; then
            security delete-keychain "$KEYCHAIN_FILE" || true
          fi
```

### macOS notes

- `--options runtime` enables the hardened runtime, which is required for notarization.
- `--deep` signs all nested binaries (frameworks, dylibs) inside the `.app` bundle. For more control, you can sign individual binaries first and the app last.
- Notarization typically takes 1-5 minutes. `--wait` blocks until Apple's service returns a result.
- The `stapler staple` step embeds the notarization ticket in the app so it works offline (without Apple's servers needing to be reachable at launch).

## Windows

### Prerequisites

A code signing certificate from a Certificate Authority (CA). Two types:

- **OV (Organization Validation)** -- identifies your organisation. Builds SmartScreen reputation over time. Issued as a `.pfx` file.
- **EV (Extended Validation)** -- immediate SmartScreen trust (no reputation-building period). Since June 2023, CAs issue EV certificates on hardware security modules (HSMs) or cloud signing services, not as `.pfx` files.

Common CAs: DigiCert, Sectigo, SSL.com, GlobalSign.

### Local signing

With a certificate in a `.pfx` file (OV certificates):

```powershell
# Build
uv run pyinstaller mergemail365.spec

# Sign the exe (signtool is part of the Windows SDK)
signtool sign /f certificate.pfx /p PASSWORD /tr http://timestamp.digicert.com /td sha256 /fd sha256 dist\mergemail365\mergemail365.exe

# Verify
signtool verify /pa dist\mergemail365\mergemail365.exe
```

The `/tr` flag adds an RFC 3161 timestamp so the signature remains valid after the certificate expires.

### Self-signing (no CA certificate)

If you don't have a CA-issued certificate, you can create a self-signed certificate for local testing or internal distribution. Self-signed certificates will still trigger SmartScreen warnings for external users (Windows doesn't trust them by default), but they are useful for:

- Development and testing
- Internal distribution where you can install the certificate on target machines
- Verifying that the signing process works before purchasing a CA certificate

```powershell
# Create a self-signed code signing certificate (PowerShell, run as Administrator)
$cert = New-SelfSignedCertificate `
  -Subject "CN=MergeMail365 Self-Signed" `
  -Type CodeSigningCert `
  -CertStoreLocation Cert:\CurrentUser\My `
  -NotAfter (Get-Date).AddYears(3)

# Export to .pfx for reuse (optional)
$password = ConvertTo-SecureString -String "YourPassword" -Force -AsPlainText
Export-PfxCertificate -Cert $cert -FilePath certificate.pfx -Password $password

# Sign the exe
signtool sign /fd sha256 /sha1 $cert.Thumbprint dist\mergemail365\mergemail365.exe

# Verify
signtool verify /pa dist\mergemail365\mergemail365.exe
```

To suppress SmartScreen warnings on target machines, install the certificate into the **Trusted Publishers** store:

```powershell
# On the target machine (run as Administrator)
Import-PfxCertificate -FilePath certificate.pfx -CertStoreLocation Cert:\LocalMachine\TrustedPublisher -Password $password

# Or import just the public certificate (no private key needed on target machines)
# First export the public cert:
Export-Certificate -Cert $cert -FilePath mergemail365.cer
# Then on the target machine:
Import-Certificate -FilePath mergemail365.cer -CertStoreLocation Cert:\LocalMachine\TrustedPublisher
```

This is practical for managed environments (e.g. deploying via Group Policy) but not for public distribution.

### Cloud signing (EV certificates)

EV certificates are typically stored on a cloud HSM. The exact signing command depends on the provider:

**SSL.com eSigner:**
```powershell
# Install eSigner CodeSignTool
# https://www.ssl.com/guide/esigner-codesigntool-command-guide/

CodeSignTool sign ^
  -username "your@email.com" ^
  -password "password" ^
  -totp_secret "base64-totp-secret" ^
  -input_file_path "dist\mergemail365\mergemail365.exe" ^
  -override
```

**DigiCert KeyLocker:**
```powershell
# Configure via environment variables
smctl sign /fd sha256 /tr http://timestamp.digicert.com /td sha256 ^
  /input "dist\mergemail365\mergemail365.exe"
```

### CI signing (GitHub Actions)

#### Option A: OV certificate (`.pfx` file)

Store the certificate as a base64-encoded GitHub secret and decode it at build time.

**GitHub secrets:**

| Secret | Value |
|---|---|
| `WINDOWS_CERTIFICATE` | Base64-encoded `.pfx` -- `certutil -encode cert.pfx encoded.txt` or `base64 -i cert.pfx \| pbcopy` |
| `WINDOWS_CERTIFICATE_PWD` | Password for the `.pfx` file |

**Workflow steps** (add after the build step, before the archive step):

```yaml
      - name: Sign executable (Windows)
        if: runner.os == 'Windows'
        env:
          WINDOWS_CERTIFICATE: ${{ secrets.WINDOWS_CERTIFICATE }}
          WINDOWS_CERTIFICATE_PWD: ${{ secrets.WINDOWS_CERTIFICATE_PWD }}
        shell: pwsh
        run: |
          $certBytes = [Convert]::FromBase64String($env:WINDOWS_CERTIFICATE)
          $certPath = "$env:RUNNER_TEMP\certificate.pfx"
          [IO.File]::WriteAllBytes($certPath, $certBytes)

          & signtool sign /f $certPath /p $env:WINDOWS_CERTIFICATE_PWD `
            /tr http://timestamp.digicert.com /td sha256 /fd sha256 `
            dist\mergemail365\mergemail365.exe

          Remove-Item $certPath
```

#### Option B: EV certificate (cloud HSM)

EV certificates can't be exported as `.pfx` files. Use the CA's GitHub Action or CLI tool instead. For example, with SSL.com:

```yaml
      - name: Sign executable (Windows, EV)
        if: runner.os == 'Windows'
        uses: sslcom/esigner-codesign@v1
        with:
          command: sign
          username: ${{ secrets.SSLCOM_USERNAME }}
          password: ${{ secrets.SSLCOM_PASSWORD }}
          totp_secret: ${{ secrets.SSLCOM_TOTP_SECRET }}
          file_path: dist\mergemail365\mergemail365.exe
          override: true
```

Other CAs have similar integrations (DigiCert KeyLocker has `digicert/cloud-sign-action`, etc.).

### Windows notes

- **SmartScreen reputation**: OV-signed binaries still trigger SmartScreen warnings until they build enough download reputation. EV certificates bypass this entirely.
- **Timestamping** (`/tr`) is essential -- without it, the signature becomes invalid when the certificate expires.
- **What to sign**: Sign `mergemail365.exe` inside the `dist\mergemail365\` directory before creating the zip archive. You can also sign bundled `.dll` files for completeness, but the `.exe` is what Windows checks.
- **Cost**: OV certificates are ~$70-200/year. EV certificates are ~$300-600/year. Some CAs offer open-source discounts.
