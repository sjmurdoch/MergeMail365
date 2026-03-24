# Code Signing

This documents how to sign the MergeMail365 PyInstaller bundles so users don't see OS security warnings (macOS Gatekeeper / Windows SmartScreen).

## macOS

### Prerequisites

For full distribution (no Gatekeeper warnings):
- An [Apple Developer Program](https://developer.apple.com/programs/) membership ($99/year)
- A **Developer ID Application** certificate from the [Apple Developer portal](https://developer.apple.com/account/resources/certificates/list)
- An [app-specific password](https://support.apple.com/en-us/102654) for your Apple ID (used for notarization)

### Entitlements

PyInstaller apps running Python need specific hardened runtime entitlements. MergeMail365 also uses pywebview (WKWebView), which requires network client access even for local content because WKWebView uses an out-of-process renderer.

Create `entitlements.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>com.apple.security.cs.allow-jit</key>
    <true/>
    <key>com.apple.security.cs.allow-unsigned-executable-memory</key>
    <true/>
    <key>com.apple.security.cs.disable-library-validation</key>
    <true/>
    <key>com.apple.security.network.client</key>
    <true/>
</dict>
</plist>
```

What each entitlement does:
- `allow-jit` -- Python uses JIT-like dynamic code execution
- `allow-unsigned-executable-memory` -- **required for PyInstaller**; Python relies on dynamic code generation and the hardened runtime will kill the process without this
- `disable-library-validation` -- allows loading bundled `.dylib`/`.so` files that aren't signed with the same Team ID (PyInstaller bundles libraries from many sources)
- `network.client` -- **required for pywebview/WKWebView** even when only loading local content

Do not put comments in the entitlements plist file -- recent macOS versions and the notary service are strict about this.

### PyInstaller built-in signing

PyInstaller can sign during the build via the spec file or command-line flags. When `codesign_identity` is set, PyInstaller automatically enables hardened runtime and signs all collected binaries, the executable, and the `.app` bundle (with `--deep`).

In `mergemail365.spec`, set on the `EXE()` call:
```python
codesign_identity='Developer ID Application: Your Name (TEAMID)',
entitlements_file='entitlements.plist',
```

Or pass command-line flags:
```bash
uv run pyinstaller --codesign-identity "Developer ID Application: Your Name (TEAMID)" \
  --osx-entitlements-file entitlements.plist mergemail365.spec
```

### Post-build signing

If you prefer to sign after building (e.g., in CI where the spec file doesn't have the identity):

```bash
# Build the app
uv run pyinstaller mergemail365.spec

# Sign with hardened runtime and entitlements
codesign --deep --force --options runtime --timestamp \
  --entitlements entitlements.plist \
  --sign "Developer ID Application: Your Name (TEAMID)" \
  dist/MergeMail365.app

# Verify the signature
codesign --verify --deep --strict dist/MergeMail365.app
```

Apple recommends signing inside-out (inner binaries first, then the bundle), but `--deep` is required for PyInstaller bundles because all the bundled Python libraries need to be signed. The `--timestamp` flag is required for notarization.

### Ad-hoc signing

PyInstaller ad-hoc signs all binaries by default (mandatory on Apple Silicon). Ad-hoc signing is sufficient for running on the machine where the app was built, but apps will be blocked by Gatekeeper when transferred to another Mac.

Gatekeeper treats ad-hoc signed and self-signed apps identically — both are "unidentified developer" because neither chains back to an Apple-issued Developer ID certificate. The user experience when opening a blocked app depends on the macOS version:

- **Ventura (13) and Sonoma (14):** Right-click (Control-click) the app, choose **Open**, confirm in the dialog. One-time approval.
- **Sequoia (15.0+):** The right-click bypass was removed. Users must go to **System Settings > Privacy & Security**, find the blocked app under the Security section, and click **Open Anyway**. One-time approval.

Note that the `com.apple.quarantine` extended attribute is what triggers Gatekeeper, not the signing type. Apps copied via Terminal (`cp`) or with quarantine removed (`xattr -d com.apple.quarantine App.app`) will run without any prompt regardless of how they are signed. Distribution instructions can suggest this as a workaround.

```bash
# Ad-hoc sign (no identity needed)
codesign -s - --force --deep dist/MergeMail365.app

# Ad-hoc with hardened runtime (useful for testing entitlements locally)
codesign -s - --force --deep --options runtime \
  --entitlements entitlements.plist dist/MergeMail365.app
```

### Self-signing

Self-signed certificates do **not** work with hardened runtime on macOS. When PyInstaller enables hardened runtime (which it does automatically with `codesign_identity`), self-signed certificates cause shared libraries to fail to load with: *"code signature not valid for use in process using Library Validation: mapped file has no Team ID"*.

Self-signed certificates also cannot be notarized (Apple requires Developer ID). Gatekeeper blocks self-signed apps with the same dialog and bypass steps as ad-hoc signed apps (see above), so self-signing offers no UX advantage for distribution. For local testing, ad-hoc signing (`codesign -s -`) is simpler and equally effective. For distribution, you need a paid Apple Developer account.

If you still want a self-signed certificate (e.g., for signing **without** hardened runtime):

```bash
# Create a self-signed code signing certificate via openssl
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

openssl req -x509 -newkey rsa:2048 -keyout /tmp/ss-key.pem -out /tmp/ss-cert.pem \
  -days 365 -nodes -config /tmp/cert.cfg -extensions ext
openssl pkcs12 -export -out /tmp/ss-cert.p12 -inkey /tmp/ss-key.pem -in /tmp/ss-cert.pem -passout pass:
security import /tmp/ss-cert.p12 -k ~/Library/Keychains/login.keychain-db -P "" -T /usr/bin/codesign
rm /tmp/cert.cfg /tmp/ss-key.pem /tmp/ss-cert.pem /tmp/ss-cert.p12

# Sign WITHOUT hardened runtime (--options runtime must be omitted)
codesign --deep --force --sign "MergeMail365 Self-Signed" dist/MergeMail365.app
```

To run the self-signed app on another Mac, the user must allow it in **System Settings > Privacy & Security** (on Sequoia 15.0+) or right-click > **Open** (on Sonoma and earlier). This is the same process as for ad-hoc signed apps.

### Notarization

Apple requires notarization for apps distributed outside the App Store. After signing with a Developer ID certificate:

```bash
# Create a zip for submission
ditto -c -k --sequesterRsrc --keepParent dist/MergeMail365.app dist/MergeMail365-notarize.zip

# Submit for notarization (uses notarytool, NOT the deprecated altool)
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

Common notarization failures with PyInstaller:
- Unsigned binaries inside the bundle (particularly `.dylib` from third-party packages)
- Missing `--timestamp` flag during signing
- Missing hardened runtime (`--options runtime`)
- Entitlements not applied

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
          codesign --deep --force --options runtime --timestamp \
            --entitlements entitlements.plist \
            --sign "$CODESIGN_IDENTITY" \
            dist/MergeMail365.app

          ditto -c -k --sequesterRsrc --keepParent dist/MergeMail365.app dist/MergeMail365-notarize.zip

          xcrun notarytool submit dist/MergeMail365-notarize.zip \
            --apple-id "$APPLE_ID" \
            --password "$APPLE_ID_PWD" \
            --team-id "$APPLE_TEAM_ID" \
            --wait

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
- `--deep` signs all nested binaries (frameworks, dylibs) inside the `.app` bundle. Apple recommends signing inside-out, but `--deep` is required for PyInstaller bundles because there can be hundreds of collected binaries.
- `--timestamp` is required for notarization. Without it, the submission will be rejected.
- Notarization typically takes 1-5 minutes. `--wait` blocks until Apple's service returns a result.
- The `stapler staple` step embeds the notarization ticket in the app so it works offline.
- `--onedir` mode (which our spec uses via `COLLECT`) is strongly recommended over `--onefile` for signed/notarized apps. Onefile bundles cannot be post-signed (embedded binaries are inaccessible) and are incompatible with sandboxing.
- If signing fails with `"no cdhash, completely unsigned?"`, ensure you're using `--force` to replace PyInstaller's default ad-hoc signatures.
- **Gatekeeper bypass changed in Sequoia**: macOS 15.0 removed the right-click > Open bypass for unsigned/ad-hoc/self-signed apps. Users must now go to System Settings > Privacy & Security > Open Anyway. This makes distribution without a Developer ID certificate noticeably more friction for end users.

## Windows

### Prerequisites

`signtool.exe` from the [Windows SDK](https://developer.microsoft.com/en-us/windows/downloads/windows-sdk/) (only the "Signing Tools for Desktop Apps" component is needed). Add it to your PATH or reference it absolutely from `C:\Program Files (x86)\Windows Kits\10\bin\10.0.xxxxx.0\x64\signtool.exe`.

For public distribution, a code signing certificate from a CA:

- **OV (Organization Validation)** -- identifies your organisation. Builds SmartScreen reputation over time. Since June 2023, CAs may require hardware-backed key storage even for OV.
- **EV (Extended Validation)** -- higher initial SmartScreen trust (though as of March 2024, EV no longer *instantly* bypasses SmartScreen). Private key lives on a hardware token or cloud HSM.

Common CAs: DigiCert, Sectigo, SSL.com, GlobalSign.

### Local signing

With a certificate in a `.pfx` file:

```powershell
# Build
uv run pyinstaller mergemail365.spec

# Sign the exe and all DLLs in the output directory
signtool sign /f certificate.pfx /p PASSWORD `
  /fd sha256 /tr http://timestamp.digicert.com /td sha256 `
  dist\mergemail365\mergemail365.exe

# Optionally sign bundled DLLs (recommended for Smart App Control)
signtool sign /f certificate.pfx /p PASSWORD `
  /fd sha256 /tr http://timestamp.digicert.com /td sha256 `
  dist\mergemail365\*.dll dist\mergemail365\*.pyd

# Verify
signtool verify /pa dist\mergemail365\mergemail365.exe
```

Key flags:
- `/f` -- path to the PFX certificate file
- `/p` -- certificate password
- `/fd sha256` -- digest algorithm (always use SHA256; SHA1 is deprecated)
- `/tr` -- RFC 3161 timestamp server URL (essential -- without it, the signature becomes invalid when the certificate expires)
- `/td sha256` -- timestamp digest algorithm

### Self-signing (no CA certificate)

Self-signed certificates are useful for validating your signing pipeline before purchasing a CA certificate, and for internal distribution where you control target machines. They will still show "Unknown Publisher" SmartScreen warnings for external users.

```powershell
# Create a self-signed code signing certificate (PowerShell, run as Administrator)
$cert = New-SelfSignedCertificate `
  -Subject "CN=MergeMail365 Self-Signed" `
  -Type CodeSigningCert `
  -CertStoreLocation Cert:\CurrentUser\My `
  -KeyExportPolicy Exportable `
  -HashAlgorithm SHA256 `
  -KeyLength 2048 `
  -KeyUsageProperty Sign `
  -KeyUsage CertSign `
  -NotAfter (Get-Date).AddYears(3)

# Export to .pfx for reuse
$password = ConvertTo-SecureString -String "YourPassword" -Force -AsPlainText
Export-PfxCertificate -Cert "Cert:\CurrentUser\My\$($cert.Thumbprint)" `
  -FilePath certificate.pfx -Password $password

# Sign the exe
signtool sign /f certificate.pfx /p YourPassword `
  /fd sha256 /tr http://timestamp.digicert.com /td sha256 `
  dist\mergemail365\mergemail365.exe

# Verify
signtool verify /pa dist\mergemail365\mergemail365.exe
```

To suppress SmartScreen warnings on managed target machines, install the certificate into the **Trusted Publishers** store:

```powershell
# Export the public certificate (no private key)
Export-Certificate -Cert "Cert:\CurrentUser\My\$($cert.Thumbprint)" -FilePath mergemail365.cer

# On the target machine (run as Administrator)
Import-Certificate -FilePath mergemail365.cer -CertStoreLocation Cert:\LocalMachine\TrustedPublisher
```

This is practical for managed environments (e.g. deploying via Group Policy) but not for public distribution.

### Cloud signing (EV certificates)

Since June 2023, code signing private keys must be stored on FIPS 140-2 Level 3 hardware. For CI/CD, this means cloud HSM services.

**SSL.com eSigner** (only file hashes are sent to SSL.com; your code never leaves the CI runner):
```powershell
CodeSignTool sign ^
  -username "your@email.com" ^
  -password "password" ^
  -totp_secret "base64-totp-secret" ^
  -input_file_path "dist\mergemail365\mergemail365.exe" ^
  -override
```

**DigiCert KeyLocker** (registers as a Windows KSP, so standard signtool works):
```powershell
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

          # Sign the main exe and all DLLs
          Get-ChildItem dist\mergemail365\*.exe, dist\mergemail365\*.dll, dist\mergemail365\*.pyd |
            ForEach-Object {
              & signtool sign /f $certPath /p $env:WINDOWS_CERTIFICATE_PWD `
                /tr http://timestamp.digicert.com /td sha256 /fd sha256 `
                $_.FullName
            }

          Remove-Item $certPath
```

#### Option B: EV certificate (cloud HSM)

EV certificates can't be exported as `.pfx` files. Use the CA's GitHub Action instead.

**SSL.com:**
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

**DigiCert KeyLocker** (use `digicert/code-signing-software-trust-action@v1.0.0`; the older `digicert/ssm-code-signing@v1.1.1` is deprecated, end-of-life May 2026).

### Windows Defender and SmartScreen issues

PyInstaller executables commonly trigger antivirus false positives and SmartScreen warnings. This is because PyInstaller's bootloader binary is shared by all PyInstaller apps (including malware), so antivirus heuristics flag the pattern.

**Mitigations (in order of effectiveness):**

1. **Code sign with a CA-issued certificate** -- the most important step.

2. **Sign all binaries, not just the exe** -- sign `.dll` and `.pyd` files in `dist\mergemail365\` too. Windows 11 Smart App Control checks all loaded binaries, not just the main executable. This is why the CI workflow above signs everything.

3. **Recompile PyInstaller's bootloader from source** -- creates a unique binary hash, avoiding pattern-matching:
   ```bash
   cd <pyinstaller-source>/bootloader
   python ./waf all
   cd ..
   python setup.py install
   ```

4. **Submit false positives to Microsoft** -- upload your exe at https://www.microsoft.com/en-us/wdsi/filesubmission. Microsoft typically responds within hours.

5. **Submit to VirusTotal** -- upload at https://www.virustotal.com, then report false positives to each flagging vendor.

### Windows notes

- **SmartScreen reputation**: OV-signed binaries trigger SmartScreen warnings until they build download reputation (weeks to months). As of March 2024, EV certificates also no longer *instantly* bypass SmartScreen, though they start with higher trust.
- **Timestamping** (`/tr`) is essential -- without it, the signature becomes invalid when the certificate expires.
- **Sign before archiving**: Sign all binaries inside `dist\mergemail365\` before creating the zip in the release workflow.
- **`--onefile` vs `--onedir`**: Our spec uses `--onedir` (via `COLLECT`). This is important because `--onefile` embeds DLLs that are extracted unsigned at runtime, which Smart App Control blocks. With `--onedir`, you can sign every binary individually.
- **Cost**: OV certificates are ~$70-200/year. EV certificates are ~$300-600/year. Some CAs offer open-source discounts.
- **pywebview**: On Windows, pywebview uses Edge WebView2, which is already signed by Microsoft and requires no additional signing steps.

## References

- [PyInstaller Feature Notes: Code Signing](https://pyinstaller.org/en/stable/feature-notes.html)
- [PyInstaller Wiki: Recipe OSX Code Signing](https://github.com/pyinstaller/pyinstaller/wiki/Recipe-OSX-Code-Signing)
- [PyInstaller Wiki: Recipe Win Code Signing](https://github.com/pyinstaller/pyinstaller/wiki/Recipe-Win-Code-Signing)
- [txoof's OS X Code Signing PyInstaller Guide](https://gist.github.com/txoof/0636835d3cc65245c6288b2374799c43)
- [Signing and Notarizing a Python macOS UI Application (haim.dev)](https://haim.dev/posts/2020-08-08-python-macos-app)
- [Automate PyInstaller Builds and Code Signing on Windows](https://johanneskinzig.com/automating-pyinstaller-builds-and-code-signing-with-powershell.html)
- [Self-sign a Windows Executable (GitHub Gist)](https://gist.github.com/PaulCreusy/7fade8d5a8026f2228a97d31343b335e)
- [PyInstaller Issue #6747: Sign files for Smart App Control](https://github.com/pyinstaller/pyinstaller/issues/6747)
- [Apple: Hardened Runtime](https://developer.apple.com/documentation/security/hardened-runtime)
- [Apple: WKWebView requires network.client entitlement](https://developer.apple.com/forums/thread/116359)
