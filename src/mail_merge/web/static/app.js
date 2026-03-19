/* Mail Merge — Wizard UI */

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let currentStep = 1;
let spreadsheetData = null;   // { columns, rows, sheets, file_name }
let previewIndex = 0;
let sendMode = "individual";  // "individual" | "bcc"
let testPassed = false;
let verifyPassed = false;
let sendStarted = false;
let currentJobId = null;
let sendResults = null;
let formDirty = false;

// Convenience getter — spreadsheetData.rows is the single source of truth
function getRecipients() { return spreadsheetData ? spreadsheetData.rows : null; }

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function $(id) { return document.getElementById(id); }
function hide(el) { if (typeof el === "string") el = $(el); el.classList.add("hidden"); }
function show(el) { if (typeof el === "string") el = $(el); el.classList.remove("hidden"); }
function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
}

function updateStepUI(n) {
    document.querySelectorAll(".step-panel").forEach(p => p.classList.remove("active"));
    $("step-" + n).classList.add("active");
    document.querySelectorAll(".step-indicator li").forEach(li => {
        const s = parseInt(li.dataset.step);
        li.classList.remove("active", "completed");
        if (s < n) li.classList.add("completed");
        if (s === n) li.classList.add("active");
    });
}

function renderSpreadsheetSummary(data) {
    $("spreadsheet-summary").textContent = `${data.file_name}: ${data.columns.length} columns, ${data.total_rows} rows.`;
    if (data.total_rows > 99) {
        $("spreadsheet-summary").innerHTML += ` <span class="badge badge-warning" style="margin-left:0.5rem;">Large file — filters required</span>`;
    }
}

function populateDropdowns(data) {
    populateSelect($("email-column"), data.columns, true);
    populateSelect($("name-column"), data.columns, false);
    populateSheetSelect(data.sheets);
}

function apiFetch(url, opts = {}) {
    opts.headers = opts.headers || {};
    if (opts.method && opts.method !== "GET") {
        opts.headers["X-CSRF-Token"] = CSRF_TOKEN;
        // Refresh sliding window on activity
        sessionStart = Date.now();
    }
    return fetch(url, opts);
}

// ---------------------------------------------------------------------------
// Step navigation
// ---------------------------------------------------------------------------
async function goToStep(n) {
    console.log("Navigating to step", n, "from", currentStep);
    
    // Only perform validation/trigger side-effects when advancing forward
    if (n > currentStep) {
        if (n === 2 && currentStep === 1) {
            if (!validateSetup()) return;
            const previewOk = await loadPreview();
            if (!previewOk) return;
        }
        if (n === 3) {
            if (!testPassed) {
                // pre-fill test email
                checkAuthForStep3();
            }
        }
        if (n === 4) {
            if (!testPassed) return;
            startVerify();
        }
        if (n === 5) {
            if (!verifyPassed) return;
            prepareSend();
        }
    }

    currentStep = n;
    saveState();
    updateStepUI(n);
}

function confirmGoBack(targetStep) {
    if (currentStep >= 3 && (testPassed || verifyPassed)) {
        if (!confirm("Going back will discard your test and verification results. You will need to complete these steps again. Continue?")) {
            return;
        }
        testPassed = false;
        verifyPassed = false;
        $("btn-next-3").disabled = true;
        $("btn-next-4").disabled = true;
        $("test-log").innerHTML = "";
        hide("test-log");
        hide("test-result");
        $("verify-log").innerHTML = "";
        hide("verify-result");
    }
    goToStep(targetStep);
}

// ---------------------------------------------------------------------------
// Step 1: Setup
// ---------------------------------------------------------------------------
function validateSetup() {
    if (!spreadsheetData) {
        alert("Please upload a spreadsheet.");
        return false;
    }
    const emailCol = $("email-column").value;
    if (!emailCol) {
        alert("Please select an email column.");
        return false;
    }
    const subject = $("subject-input").value.trim();
    if (!subject) {
        alert("Please enter a subject.");
        return false;
    }
    const body = $("body-input").value.trim();
    if (!body) {
        alert("Please enter a body.");
        return false;
    }
    if (sendMode === "bcc" && !$("bcc-blast-to").value.trim()) {
        alert("BCC Blast mode requires a To: address.");
        return false;
    }
    // Quick pre-check using the total row count from the spreadsheet.
    // The authoritative cap check happens server-side in api_get_recipients
    // (after email validation and filtering), but this gives early feedback
    // when the spreadsheet is clearly too large and no filters are set.
    if (spreadsheetData.total_rows > 99 && !$("filter-input").value.trim()) {
        alert(`Too many recipients (${spreadsheetData.total_rows}). The web interface supports up to 99 recipients. Add filters to reduce the count, or use the command-line tool.`);
        return false;
    }
    return true;
}

function setSendMode(mode) {
    sendMode = mode;
    if (mode === "individual") {
        $("mode-individual").classList.add("active-mode");
        $("mode-individual").classList.remove("outline");
        $("mode-bcc").classList.remove("active-mode");
        $("mode-bcc").classList.add("outline");
        hide("bcc-blast-options");
        if (spreadsheetData) show("placeholder-chips");
    } else {
        $("mode-bcc").classList.add("active-mode");
        $("mode-bcc").classList.remove("outline");
        $("mode-individual").classList.remove("active-mode");
        $("mode-individual").classList.add("outline");
        show("bcc-blast-options");
        hide("placeholder-chips");
        checkBccPlaceholders();
    }
}

function checkBccPlaceholders() {
    const subject = $("subject-input").value;
    const body = $("body-input").value;
    const has = /\{\{\w+\}\}/.test(subject + body);
    if (has) {
        show("bcc-placeholder-warn");
    } else {
        hide("bcc-placeholder-warn");
    }
}

async function saveState() {
    try {
        await apiFetch("/api/state", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                current_step: currentStep,
                test_passed: testPassed,
                verify_passed: verifyPassed
            })
        });
    } catch (e) { /* ignore */ }
}

// Load config and session status on page load
async function loadConfig() {
    try {
        const resp = await apiFetch("/api/config");
        const data = await resp.json();
        
        // Restore config
        if (data.client_id) {
            $("client-id").value = data.client_id;
            show("config-badge");
        }
        if (data.tenant_id) {
            $("tenant-id").value = data.tenant_id;
        }
        // Hide config fields entirely when baked into the application
        if (data.client_id_locked && data.tenant_id_locked) {
            hide("auth-config-fields");
        }

        // Restore session spreadsheet if it exists
        if (data.spreadsheet) {
            const s = data.spreadsheet;
            spreadsheetData = s;
            show("spreadsheet-info");
            renderSpreadsheetSummary(s);
            populateDropdowns(s);
            
            // Restore chosen columns if they match what's in the sheet
            const savedEmailCol = localStorage.getItem("mm_email_col");
            if (savedEmailCol && s.columns.includes(savedEmailCol)) {
                $("email-column").value = savedEmailCol;
            }
            const savedNameCol = localStorage.getItem("mm_name_col");
            if (savedNameCol && s.columns.includes(savedNameCol)) {
                $("name-column").value = savedNameCol;
            }
        }

        // Restore wizard state
        testPassed = data.test_passed;
        verifyPassed = data.verify_passed;
        
        if (data.active_job_id) {
            currentJobId = data.active_job_id;
            sendStarted = true;
            // Jump to step 5 (Send) and connect to the existing stream
            hide("send-confirm");
            show("send-progress");
            show("send-log");
            $("btn-back-5").disabled = true;
            window.addEventListener("beforeunload", beforeUnloadWarn);
            currentStep = 5;
            updateStepUI(5);
            streamEvents(currentJobId, "send-log", (result) => {
                window.removeEventListener("beforeunload", beforeUnloadWarn);
                if (result.status === "completed" || result.status === "stopped") {
                    fetchAndShowSendResults(currentJobId);
                } else {
                    showSendResult(false, result.error || "Send failed");
                }
            }, (current, total) => {
                $("send-progress-bar").max = total;
                $("send-progress-bar").value = current;
                $("send-progress-text").textContent = `Sending ${current} of ${total}...`;
            });
        } else if (data.current_step > 1) {
            await goToStep(data.current_step);
        }
    } catch (e) { console.error("Error loading config:", e); }
}

// Check auth status
let tokenExpiresAt = null;
async function checkAuthStatus() {
    try {
        const resp = await apiFetch("/auth/status");
        const data = await resp.json();
        const el = $("auth-display");
        if (data.authenticated) {
            el.innerHTML = '<span class="dot green"></span> Signed in as <span class="email">' + escapeHtml(data.email) + '</span>';
            if ($("test-email-input") && !$("test-email-input").value) {
                $("test-email-input").value = data.email;
            }
            if (data.token_expires_at) {
                tokenExpiresAt = new Date(data.token_expires_at);
            }
        } else {
            el.innerHTML = '<span class="dot gray"></span> Not signed in';
            tokenExpiresAt = null;
        }
    } catch (e) { /* ignore */ }
}

// Sign in
$("btn-sign-in").addEventListener("click", () => {
    // Save client_id/tenant_id to session first
    const clientId = $("client-id").value.trim();
    const tenantId = $("tenant-id").value.trim() || "common";
    if (!clientId) {
        alert("Please enter a Client ID first.");
        return;
    }
    // Store in session via query params on the login redirect
    window.location.href = `/auth/login?client_id=${encodeURIComponent(clientId)}&tenant_id=${encodeURIComponent(tenantId)}`;
});

// Test connection
$("btn-test-connection").addEventListener("click", async () => {
    show("auth-diagnostics");
    $("auth-diag-content").textContent = "Testing...";
    try {
        const resp = await apiFetch("/auth/debug");
        const data = await resp.json();
        
        // Build a summary of results
        let summary = "";
        if (data.error) {
            summary = `<div class="callout callout-danger" style="margin-top:0;"><strong>Connection Error:</strong> ${escapeHtml(data.error)}</div>`;
        } else if (data.token_valid) {
            summary = `<div class="callout callout-info" style="margin-top:0; background-color: #166534; border-color: #166534;"><strong>Success:</strong> Connection is healthy and token is valid.</div>`;
        } else if (data.authority_reachable) {
            summary = `<div class="callout callout-warning" style="margin-top:0;"><strong>Partial Success:</strong> Authority is reachable, but you are not signed in or token has expired.</div>`;
        } else {
            summary = `<div class="callout callout-danger" style="margin-top:0;"><strong>Failure:</strong> Microsoft login authority is not reachable. Check your internet connection.</div>`;
        }
        
        $("auth-diag-content").innerHTML = summary + `<pre style="font-size:0.8rem; margin-top: 0.5rem;">${JSON.stringify(data, null, 2)}</pre>`;
    } catch (e) {
        $("auth-diag-content").innerHTML = `<div class="callout callout-danger" style="margin-top:0;"><strong>Error:</strong> ${escapeHtml(e.message)}</div>`;
    }
});

// Spreadsheet upload
$("spreadsheet-file").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const form = new FormData();
    form.append("spreadsheet", file);

    try {
        const resp = await apiFetch("/api/upload-spreadsheet", {
            method: "POST",
            body: form,
            headers: { "X-CSRF-Token": CSRF_TOKEN },
        });
        const data = await resp.json();
        if (!resp.ok) {
            alert(data.error || "Upload failed");
            return;
        }
        spreadsheetData = data;
        show("spreadsheet-info");
        renderSpreadsheetSummary(data);
        $("btn-next-1").disabled = false;
        populateDropdowns(data);

        // Auto-detect email column
        const emailPatterns = ["email", "e-mail", "email address", "emailaddress", "mail"];
        for (const col of data.columns) {
            if (emailPatterns.includes(col.toLowerCase())) {
                $("email-column").value = col;
                break;
            }
        }

        // Build preview table
        buildPreviewTable(data.columns, data.rows);

        // Show placeholder chips
        showPlaceholderChips(data.columns);
    } catch (e) {
        alert("Upload error: " + e.message);
    }
});

function populateSelect(sel, cols, required) {
    let html = required ? '<option value="">-- select --</option>' : '<option value="">-- none --</option>';
    for (const c of cols) {
        html += `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`;
    }
    sel.innerHTML = html;
}

function populateSheetSelect(sheets) {
    const sel = $("sheet-select");
    sel.innerHTML = sheets.map(s =>
        `<option value="${escapeHtml(s)}">${escapeHtml(s)}</option>`
    ).join("");
}

function buildPreviewTable(columns, rows) {
    const thead = document.querySelector("#preview-table thead");
    const tbody = document.querySelector("#preview-table tbody");
    thead.innerHTML = "<tr>" + columns.map(c => `<th>${escapeHtml(c)}</th>`).join("") + "</tr>";
    tbody.innerHTML = rows.map(row =>
        "<tr>" + columns.map(c => `<td>${escapeHtml(row[c] || "")}</td>`).join("") + "</tr>"
    ).join("");
}

function showPlaceholderChips(columns) {
    show("placeholder-chips");
    const container = $("chips");
    container.innerHTML = "";
    for (const col of columns) {
        const chip = document.createElement("span");
        chip.className = "chip";
        chip.textContent = "{{" + col + "}}";
        chip.addEventListener("mousedown", (e) => {
            // Use mousedown and preventDefault to avoid the input losing focus
            // when clicking the chip.
            e.preventDefault();
            
            // Target either the subject or the body, whichever was last focused
            let target = document.activeElement;
            if (target !== $("subject-input") && target !== $("body-input")) {
                target = $("body-input");
            }
            
            const start = target.selectionStart;
            const end = target.selectionEnd;
            const text = target.value;
            const insertion = "{{" + col + "}}";
            
            target.value = text.substring(0, start) + insertion + text.substring(end);
            target.focus();
            const newPos = start + insertion.length;
            target.setSelectionRange(newPos, newPos);
            
            // Trigger validation/auto-save
            onTemplateChange();
        });
        container.appendChild(chip);
    }
}

// Real-time placeholder validation
let placeholderTimer = null;
function onTemplateChange() {
    clearTimeout(placeholderTimer);
    placeholderTimer = setTimeout(validatePlaceholders, 500);
    if (sendMode === "bcc") checkBccPlaceholders();
    formDirty = true;
}
$("subject-input").addEventListener("input", onTemplateChange);
$("body-input").addEventListener("input", onTemplateChange);
$("email-column").addEventListener("change", onTemplateChange);
$("name-column").addEventListener("change", onTemplateChange);
$("html-toggle").addEventListener("change", onTemplateChange);
$("cc-input").addEventListener("input", onTemplateChange);
$("bcc-input").addEventListener("input", onTemplateChange);
$("reply-to-input").addEventListener("input", onTemplateChange);
$("filter-input").addEventListener("input", onTemplateChange);

function validatePlaceholders() {
    if (!spreadsheetData) return;
    const subject = $("subject-input").value;
    const body = $("body-input").value;
    const combined = subject + body;
    const used = [...combined.matchAll(/\{\{(\w+)\}\}/g)].map(m => m[1]);
    const colsLower = spreadsheetData.columns.map(c => c.toLowerCase());
    const bad = used.filter(p => !colsLower.includes(p.toLowerCase()));
    const el = $("placeholder-errors");
    if (bad.length > 0) {
        const unique = [...new Set(bad)];
        el.innerHTML = unique.map(p =>
            `No column named <strong>{{${escapeHtml(p)}}}</strong>. Available: ${spreadsheetData.columns.join(", ")}`
        ).join("<br>");
        show(el);
    } else {
        hide(el);
    }
}

// ---------------------------------------------------------------------------
// Step 2: Preview
// ---------------------------------------------------------------------------
async function loadPreview() {
    $("btn-next-1").ariaBusy = "true";
    $("btn-next-1").disabled = true;

    try {
        const form = new FormData();
        form.set("email_column", $("email-column").value);
        form.set("filters", $("filter-input").value);
        if ($("sheet-select").value) {
            form.set("sheet", $("sheet-select").value);
        }

        const resp = await apiFetch("/api/get-recipients", {
            method: "POST",
            body: form
        });
        const data = await resp.json();

        if (!resp.ok) {
            alert(data.error || "Failed to load recipients");
            return false;
        }

        // Store the final filtered recipients in spreadsheetData
        spreadsheetData.rows = data.recipients;

        const rows = spreadsheetData.rows;
        if (!rows || rows.length === 0) {
            alert("No recipients found (check your filters and email column).");
            return false;
        }

        previewIndex = 0;
        renderPreviewRecipient();
        buildRecipientsTable();

        // Show invalid email warning if any were skipped
        showInvalidEmailWarning(data.invalid_emails || [], data.total_before_validation || 0);

        // Update verify/send recipient counts
        $("verify-count").textContent = rows.length;
        $("send-count").textContent = rows.length;
        return true;

    } catch (e) {
        alert("Error loading preview: " + e.message);
        return false;
    } finally {
        $("btn-next-1").ariaBusy = "false";
        $("btn-next-1").disabled = false;
    }
}

function renderPreviewRecipient() {
    const recipients = getRecipients();
    if (!recipients || recipients.length === 0) return;
    const row = recipients[previewIndex];
    const subject = $("subject-input").value;
    const body = $("body-input").value;

    // Client-side template rendering for preview
    const rendered_subject = renderTemplate(subject, row);
    const rendered_body = renderTemplate(body, row);

    $("preview-subject").textContent = rendered_subject;
    const isHtml = $("html-toggle").checked;
    if (isHtml) {
        hide("preview-body");
        show("preview-body-html");
        $("preview-body-html").srcdoc = rendered_body;
    } else {
        show("preview-body");
        hide("preview-body-html");
        $("preview-body").textContent = rendered_body;
    }

    // Headers
    if (sendMode === "bcc") {
        $("preview-to").textContent = $("bcc-blast-to").value || "(none)";
        $("preview-cc").textContent = "(none in BCC blast mode)";
        $("preview-bcc").textContent = `[all ${recipients.length} recipients]`;
    } else {
        const emailCol = $("email-column").value;
        const nameCol = $("name-column").value;
        let to = row[emailCol] || "";
        if (nameCol && row[nameCol]) {
            to = `${row[nameCol]} <${to}>`;
        }
        $("preview-to").textContent = to;
        $("preview-cc").textContent = $("cc-input").value || "(none)";
        $("preview-bcc").textContent = $("bcc-input").value || "(none)";
    }
    $("preview-reply-to").textContent = $("reply-to-input").value || "(none)";
    $("preview-importance").textContent = $("importance-select").value || "Normal";

    $("preview-recipient-label").textContent = `Previewing recipient ${previewIndex + 1} of ${recipients.length}`;
}

function renderTemplate(template, data) {
    const lowerData = {};
    for (const [k, v] of Object.entries(data)) {
        lowerData[k.toLowerCase()] = v;
    }
    return template.replace(/\{\{(\w+)\}\}/g, (match, key) => {
        return lowerData[key.toLowerCase()] !== undefined ? lowerData[key.toLowerCase()] : match;
    });
}

function changePreviewRecipient(delta) {
    const recipients = getRecipients();
    if (!recipients) return;
    previewIndex = Math.max(0, Math.min(recipients.length - 1, previewIndex + delta));
    renderPreviewRecipient();
}

function buildRecipientsTable() {
    const recipients = getRecipients();
    if (!recipients || !spreadsheetData) return;
    const emailCol = $("email-column").value;
    // Show the email column first, then all other columns
    const cols = [emailCol, ...spreadsheetData.columns.filter(c => c !== emailCol)];
    const thead = document.querySelector("#recipients-table thead");
    const tbody = document.querySelector("#recipients-table tbody");
    thead.innerHTML = "<tr>" + cols.map(c => `<th>${escapeHtml(c)}</th>`).join("") + "</tr>";
    tbody.innerHTML = recipients.map(row =>
        "<tr>" + cols.map(c => `<td>${escapeHtml(row[c] || "")}</td>`).join("") + "</tr>"
    ).join("");
}

function showInvalidEmailWarning(invalidEmails, totalBefore) {
    const el = $("invalid-email-warning");
    if (!invalidEmails || invalidEmails.length === 0) {
        hide(el);
        return;
    }
    const recipients = getRecipients();
    const validCount = recipients ? recipients.length : 0;
    const skippedList = invalidEmails.map(e =>
        `<li><strong>${escapeHtml(e.address || "(empty)")}</strong>: ${escapeHtml(e.reason)}</li>`
    ).join("");
    el.innerHTML =
        `<strong>${invalidEmails.length} invalid email${invalidEmails.length > 1 ? " addresses" : " address"} skipped</strong>` +
        ` (${validCount} of ${totalBefore} recipients remain)` +
        `<ul style="margin:0.5rem 0 0 1rem;padding:0;font-size:0.85rem;">${skippedList}</ul>`;
    show(el);
}

// ---------------------------------------------------------------------------
// Step 3: Test Email
// ---------------------------------------------------------------------------
function checkAuthForStep3() {
    // Pre-fill test email
    checkAuthStatus();
    updateTestPreview();
}

function updateTestPreview() {
    const recipients = getRecipients();
    if (!recipients || recipients.length === 0) return;
    const row = recipients[0];
    const subject = $("subject-input").value;
    const rendered = renderTemplate(subject, row);
    const testAddr = $("test-email-input").value || "(enter test address above)";
    $("test-preview-info").innerHTML =
        `<strong>To:</strong> ${escapeHtml(testAddr)}<br>` +
        `<strong>Subject:</strong> ${escapeHtml(rendered)}<br>` +
        `<small>Using data from first recipient: ${escapeHtml(row[$("email-column").value] || "?")}</small>`;
}

$("test-email-input").addEventListener("input", updateTestPreview);

async function sendTestEmail() {
    const testAddr = $("test-email-input").value.trim();
    if (!testAddr) {
        alert("Please enter a test email address.");
        return;
    }

    testPassed = false;
    saveState();

    $("btn-send-test").disabled = true;
    $("btn-send-test").setAttribute("aria-busy", "true");
    hide("btn-retry-test");
    show("test-log");
    $("test-log").innerHTML = "";
    hide("test-result");

    const form = buildJobFormData("test_email");
    form.set("test_email", testAddr);

    try {
        const resp = await apiFetch("/api/start-job", { method: "POST", body: form, headers: { "X-CSRF-Token": CSRF_TOKEN } });
        const data = await resp.json();
        if (!resp.ok) {
            showTestResult(false, data.error || "Failed to start job");
            return;
        }
        currentJobId = data.job_id;
        streamEvents(data.job_id, "test-log", (result) => {
            if (result.status === "completed") {
                testPassed = true;
                saveState();
                $("btn-next-3").disabled = false;
                showTestResult(true, "Test email sent successfully!");
            } else {
                const errMsg = categoriseError(result.error || "Test email failed");
                showTestResult(false, errMsg);
                show("btn-retry-test");
            }
        });
    } catch (e) {
        showTestResult(false, "Error: " + e.message);
    }
}

function showTestResult(success, msg) {
    $("btn-send-test").disabled = false;
    $("btn-send-test").removeAttribute("aria-busy");
    const el = $("test-result");
    show(el);
    el.className = success ? "callout callout-info" : "callout callout-danger";
    el.textContent = msg;
}

// ---------------------------------------------------------------------------
// Step 4: Verify (Dry Run)
// ---------------------------------------------------------------------------
function startVerify() {
    const recipients = getRecipients();
    $("verify-count").textContent = recipients ? recipients.length : "?";
    $("verify-log").innerHTML = "";
    hide("verify-result");
    $("btn-next-4").disabled = true;
    verifyPassed = false;
    saveState();

    const form = buildJobFormData("dry_run");

    apiFetch("/api/start-job", { method: "POST", body: form, headers: { "X-CSRF-Token": CSRF_TOKEN } })
        .then(r => r.json())
        .then(data => {
            if (data.error) {
                showVerifyResult(false, data.error);
                return;
            }
            currentJobId = data.job_id;
            streamEvents(data.job_id, "verify-log", (result) => {
                if (result.status === "completed") {
                    verifyPassed = true;
                    saveState();
                    $("btn-next-4").disabled = false;
                    const recs = getRecipients();
                    const n = recs ? recs.length : "?";
                    const estSec = recs ? recs.length * 2 : "?";
                    let msg = `${n} emails ready to send. Estimated time: ~${estSec} seconds (2-second delay between sends).`;
                    // Token expiry check
                    if (tokenExpiresAt && recs) {
                        const estEndMs = Date.now() + recs.length * 2000;
                        if (estEndMs > tokenExpiresAt.getTime()) {
                            msg += "\n⚠️ Warning: Your authentication token may expire before sending completes. Consider signing in again before proceeding.";
                        }
                    }
                    showVerifyResult(true, msg);
                } else {
                    showVerifyResult(false, result.error || "Verification failed");
                }
            });
        })
        .catch(e => showVerifyResult(false, "Error: " + e.message));
}

function showVerifyResult(success, msg) {
    const el = $("verify-result");
    show(el);
    el.className = success ? "callout callout-info" : "callout callout-danger";
    el.textContent = msg;
}

// ---------------------------------------------------------------------------
// Step 5: Send
// ---------------------------------------------------------------------------
function prepareSend() {
    sendStarted = false;
    sendResults = null;
    const recipients = getRecipients();
    const n = recipients ? recipients.length : "?";
    $("send-count").textContent = n;

    // Build details
    let details = "";
    const authEmail = $("auth-display").querySelector(".email");
    if (authEmail) details += `<strong>From:</strong> ${escapeHtml(authEmail.textContent)}<br>`;
    details += `<strong>Recipients:</strong> ${n}<br>`;
    if ($("cc-input").value) details += `<strong>CC:</strong> ${escapeHtml($("cc-input").value)}<br>`;
    if ($("bcc-input").value) details += `<strong>BCC:</strong> ${escapeHtml($("bcc-input").value)}<br>`;
    const attInput = $("attachment-input");
    if (attInput.files.length > 0) {
        const attList = Array.from(attInput.files).map(f => {
            const sizeKb = (f.size / 1024).toFixed(0);
            return `${escapeHtml(f.name)} (${sizeKb} KB)`;
        });
        details += `<strong>Attachments:</strong> ${attList.join(", ")}<br>`;
    }
    $("send-confirm-details").innerHTML = details;

    show("send-confirm");
    hide("send-progress");
    hide("send-log");
    hide("send-result");
    show("send-nav");
    hide("send-done-nav");
    $("send-confirm-input").value = "";
    $("btn-do-send").disabled = true;
}

$("send-confirm-input").addEventListener("input", () => {
    $("btn-do-send").disabled = $("send-confirm-input").value.trim().toUpperCase() !== "SEND";
});

async function startSend() {
    sendStarted = true;
    hide("send-confirm");
    show("send-progress");
    show("send-log");
    $("send-log").innerHTML = "";
    $("btn-back-5").disabled = true;

    // beforeunload warning
    window.addEventListener("beforeunload", beforeUnloadWarn);

    const form = buildJobFormData("send");

    try {
        const resp = await apiFetch("/api/start-job", { method: "POST", body: form, headers: { "X-CSRF-Token": CSRF_TOKEN } });
        const data = await resp.json();
        if (!resp.ok) {
            showSendResult(false, data.error || "Failed to start send");
            return;
        }
        currentJobId = data.job_id;
        streamEvents(data.job_id, "send-log", (result) => {
            window.removeEventListener("beforeunload", beforeUnloadWarn);
            if (result.status === "completed" || result.status === "stopped") {
                fetchAndShowSendResults(data.job_id);
            } else {
                showSendResult(false, result.error || "Send failed");
            }
        }, (current, total) => {
            $("send-progress-bar").max = total;
            $("send-progress-bar").value = current;
            $("send-progress-text").textContent = `Sending ${current} of ${total}...`;
        });
    } catch (e) {
        window.removeEventListener("beforeunload", beforeUnloadWarn);
        showSendResult(false, "Error: " + e.message);
    }
}

function beforeUnloadWarn(e) {
    e.preventDefault();
    e.returnValue = "";
}

async function stopSend() {
    if (!currentJobId) return;
    await apiFetch(`/api/job/${currentJobId}/stop`, {
        method: "POST",
        headers: { "X-CSRF-Token": CSRF_TOKEN },
    });
}

async function fetchAndShowSendResults(jobId) {
    try {
        const resp = await apiFetch(`/api/job/${jobId}/status`);
        const data = await resp.json();
        sendResults = data.results || [];
        const summary = data.summary || {};

        hide("send-progress");
        show("send-result");
        hide("send-nav");
        show("send-done-nav");

        let html = `<h4>Results</h4>`;
        html += `<p><strong>Total:</strong> ${summary.total || 0} | `;
        html += `<span class="success"><strong>Sent:</strong> ${summary.sent || 0}</span> | `;
        html += `<span class="failure"><strong>Failed:</strong> ${summary.failed || 0}</span></p>`;

        if (sendResults.length > 0) {
            html += `<table class="striped results-table"><thead><tr><th>Email</th><th>Status</th><th>Error</th></tr></thead><tbody>`;
            for (const r of sendResults) {
                const cls = r.success ? "success" : "failure";
                html += `<tr class="${cls}"><td>${escapeHtml(r.email)}</td><td>${r.success ? "Sent" : "Failed"} ${r.status_code ? `(${r.status_code})` : ""}</td><td>${escapeHtml(r.error || "")}</td></tr>`;
            }
            html += `</tbody></table>`;
        }

        $("send-result").innerHTML = html;
    } catch (e) {
        showSendResult(false, "Error fetching results: " + e.message);
    }
}

function showSendResult(success, msg) {
    hide("send-progress");
    show("send-result");
    hide("send-nav");
    show("send-done-nav");
    $("send-result").innerHTML = `<div class="callout ${success ? "callout-info" : "callout-danger"}">${escapeHtml(msg)}</div>`;
    window.removeEventListener("beforeunload", beforeUnloadWarn);
}

function sanitizeCsvValue(val) {
    if (!val) return val;
    const s = String(val);
    if (/^[=+@\-\t\r]/.test(s)) return "\t" + s;
    return s;
}

function downloadCsv() {
    if (!sendResults || sendResults.length === 0) return;
    let csv = "email,success,status_code,error\n";
    for (const r of sendResults) {
        csv += `"${sanitizeCsvValue(r.email)}",${r.success},${r.status_code || ""},"${sanitizeCsvValue((r.error || "").replace(/"/g, '""'))}"\n`;
    }
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "mail-merge-results.csv";
    a.click();
    URL.revokeObjectURL(url);
}

function newMerge() {
    spreadsheetData = null;
    sendResults = null;
    testPassed = false;
    verifyPassed = false;
    sendStarted = false;
    currentJobId = null;
    currentStep = 1;
    saveState();
    
    // Clear Step 1
    $("spreadsheet-file").value = "";
    hide("spreadsheet-info");
    $("btn-next-1").disabled = false;
    
    // Clear Step 3 (Test)
    $("test-email-input").value = "";
    $("test-log").innerHTML = "";
    hide("test-log");
    $("test-result").innerHTML = "";
    hide("test-result");
    $("btn-next-3").disabled = true;
    
    // Clear Step 4 (Verify)
    $("verify-log").innerHTML = "";
    hide("verify-log");
    $("verify-result").innerHTML = "";
    hide("verify-result");
    $("btn-next-4").disabled = true;
    
    // Clear Step 5 (Send)
    $("send-confirm-input").value = "";
    $("send-log").innerHTML = "";
    hide("send-log");
    $("send-result").innerHTML = "";
    hide("send-result");
    $("send-progress-bar").value = 0;
    
    goToStep(1);
}

// ---------------------------------------------------------------------------
// SSE streaming
// ---------------------------------------------------------------------------
function streamEvents(jobId, logPanelId, onComplete, onProgress) {
    const panel = $(logPanelId);
    const evtSource = new EventSource(`/api/job/${jobId}/events`);

    evtSource.onmessage = (e) => {
        const event = JSON.parse(e.data);
        if (event.type === "done") {
            evtSource.close();
            // Fetch final status
            apiFetch(`/api/job/${jobId}/status`)
                .then(r => r.json())
                .then(data => {
                    onComplete(data);
                    saveState();
                });
            return;
        }
        if (event.type === "log") {
            const entry = document.createElement("div");
            entry.className = "log-entry " + (event.data.level || "INFO");
            entry.textContent = `[${event.data.timestamp}] ${event.data.message}`;
            panel.appendChild(entry);
            panel.scrollTop = panel.scrollHeight;
            // Extract send progress from log messages like "Sending [3/42]"
            if (onProgress) {
                const match = event.data.message.match(/\[(\d+)\/(\d+)\]/);
                if (match) onProgress(parseInt(match[1]), parseInt(match[2]));
            }
        }
        if (event.type === "completed" || event.type === "error") {
            // Will be followed by "done"
        }
    };

    evtSource.onerror = () => {
        evtSource.close();
        apiFetch(`/api/job/${jobId}/status`)
            .then(r => r.json())
            .then(data => onComplete(data))
            .catch(() => onComplete({ status: "failed", error: "Connection lost" }));
    };
}

// ---------------------------------------------------------------------------
// Build form data for job
// ---------------------------------------------------------------------------
function buildJobFormData(mode) {
    const form = new FormData();
    form.set("mode", mode);
    form.set("email_column", $("email-column").value);
    form.set("subject", $("subject-input").value);
    form.set("body", $("body-input").value);

    if ($("name-column").value) form.set("name_column", $("name-column").value);
    if ($("sheet-select").value) form.set("sheet", $("sheet-select").value);
    if ($("importance-select").value) form.set("importance", $("importance-select").value);
    if ($("cc-input").value) form.set("cc", $("cc-input").value);
    if ($("bcc-input").value) form.set("bcc", $("bcc-input").value);
    if ($("reply-to-input").value) form.set("reply_to", $("reply-to-input").value);
    if ($("html-toggle").checked) form.set("html", "true");
    form.set("save_to_sent_items", "true");
    if ($("filter-input").value.trim()) form.set("filters", $("filter-input").value.trim());

    if (sendMode === "bcc") {
        form.set("bcc_blast", "true");
        form.set("bcc_blast_to", $("bcc-blast-to").value);
    }

    // Attachments
    const attInput = $("attachment-input");
    if (attInput.files.length > 0) {
        for (const f of attInput.files) {
            form.append("attachments", f);
        }
    }

    return form;
}

// ---------------------------------------------------------------------------
// Auth hash handling (after callback redirect)
// ---------------------------------------------------------------------------
function handleAuthHash() {
    const hash = window.location.hash;
    if (hash.startsWith("#auth-success")) {
        checkAuthStatus();
        history.replaceState(null, "", window.location.pathname + window.location.search);
    } else if (hash.startsWith("#auth-error=")) {
        const error = decodeURIComponent(hash.substring("#auth-error=".length));
        alert("Authentication error: " + error);
        history.replaceState(null, "", window.location.pathname + window.location.search);
    }
}

// ---------------------------------------------------------------------------
// Session timer
// ---------------------------------------------------------------------------
const SESSION_LIFETIME_MS = 24 * 60 * 60 * 1000; // 24 hours
let sessionStart = Date.now();

function updateSessionTimer() {
    const el = $("session-timer");
    if (!el) return;
    const elapsed = Date.now() - sessionStart;
    const remaining = Math.max(0, SESSION_LIFETIME_MS - elapsed);
    const mins = Math.ceil(remaining / 60000);
    if (remaining <= 0) {
        el.textContent = "Session expired";
        el.className = "session-timer session-warn";
        show(el);
        const modal = $("session-timeout-modal");
        if (modal) modal.setAttribute("open", "true");
    } else if (mins <= 10) {
        el.textContent = `Session expires in ${mins}m`;
        el.className = "session-timer session-warn";
        show(el);
    } else if (mins <= 60) {
        el.textContent = `Session expires in ${mins}m`;
        el.className = "session-timer";
        show(el);
    } else {
        hide(el);
    }
}

// ---------------------------------------------------------------------------
// Categorised error messages for test email
// ---------------------------------------------------------------------------
function categoriseError(msg) {
    if (!msg) return msg;
    if (/401|403|Forbidden|Unauthorized/i.test(msg)) {
        return "Permission denied. Check that your Azure AD app has Mail.Send permission and admin consent has been granted.";
    }
    if (/400|Bad Request/i.test(msg)) {
        return "Email rejected by Microsoft. Check that all addresses, attachments, and fields are valid.";
    }
    if (/429|Too Many Requests|throttl/i.test(msg)) {
        return "Rate limited by Microsoft. Wait a moment and retry.";
    }
    if (/5\d\d|Server Error|Internal/i.test(msg)) {
        return "Microsoft server error. This is usually temporary. Try again in a few moments.";
    }
    return msg;
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
    loadConfig();
    checkAuthStatus();
    handleAuthHash();

    // Session timer — update every 30 seconds
    updateSessionTimer();
    setInterval(updateSessionTimer, 30000);

    // Initial check for expired session (if browser was suspended etc)
    const elapsed = Date.now() - sessionStart;
    if (elapsed >= SESSION_LIFETIME_MS) {
        const modal = $("session-timeout-modal");
        if (modal) modal.setAttribute("open", "true");
    }

    // Auto-save to localStorage (only when form content changed)
    setInterval(() => {
        if (!formDirty) return;
        formDirty = false;
        try {
            localStorage.setItem("mm_subject", $("subject-input").value);
            localStorage.setItem("mm_body", $("body-input").value);
            localStorage.setItem("mm_email_col", $("email-column").value);
            localStorage.setItem("mm_name_col", $("name-column").value);
        } catch (e) { /* ignore */ }
    }, 5000);

    // Restore from localStorage
    try {
        const savedSubject = localStorage.getItem("mm_subject");
        const savedBody = localStorage.getItem("mm_body");
        const savedEmailCol = localStorage.getItem("mm_email_col");
        const savedNameCol = localStorage.getItem("mm_name_col");
        
        if (savedSubject && !$("subject-input").value) $("subject-input").value = savedSubject;
        if (savedBody && !$("body-input").value) $("body-input").value = savedBody;
        if (savedEmailCol && !$("email-column").value) $("email-column").value = savedEmailCol;
        if (savedNameCol && !$("name-column").value) $("name-column").value = savedNameCol;
    } catch (e) { /* ignore */ }
});
