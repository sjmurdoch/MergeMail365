/* MergeMail365 — Wizard UI */

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
// Workflow fields and their reset rules live in wizard-core.js; the page
// adds what only it needs (the editor, the email wrapper, auto-save).
const state = Object.assign(WizardCore.initialState(), {
    // Dirty flag for localStorage auto-save
    formDirty: false,

    // Trix rich-text editor instance
    trixEditor: null,

    // Email wrapper (head/tail) for HTML preview — loaded from server config
    emailWrapper: null,

    /** Convenience getter — spreadsheetData.rows is the single source of truth */
    getRecipients() {
        return this.spreadsheetData ? this.spreadsheetData.rows : null;
    },

    /** Reset downstream state when compose/data changes */
    resetTestAndVerify() {
        Object.assign(this, WizardCore.resetTestAndVerify(this));
        $("test-log").innerHTML = "";
        hide("test-log");
        $("verify-log").innerHTML = "";
        render();
    },

    /** Full reset for "New merge" */
    resetAll() {
        Object.assign(this, WizardCore.newMergeState(this));
    },
});

// Expose on window so E2E tests can set flags via page.evaluate()
window.state = state;

// Legacy global aliases — E2E tests use `testPassed = true` etc.
Object.defineProperty(window, "testPassed", {
    get() { return state.testPassed; },
    set(v) { state.testPassed = v; },
});
Object.defineProperty(window, "verifyPassed", {
    get() { return state.verifyPassed; },
    set(v) { state.verifyPassed = v; },
});
Object.defineProperty(window, "spreadsheetData", {
    get() { return state.spreadsheetData; },
    set(v) { state.spreadsheetData = v; },
});

// Auth state — grouped separately (not part of wizard flow)
const _auth = {
    isSignedIn: false,
    desktopMode: false,
    signInPoll: null,     // interval ID for polling during sign-in
    tokenExpiresAt: null,
};

// Convenience alias kept as a plain function for backward compat
function getRecipients() { return state.getRecipients(); }

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
// Mirrors template.PLACEHOLDER_RE. Python's \w matches letters and digits
// in any script, JavaScript's only ASCII ones, so the classes are spelled
// out with the u flag: otherwise {{Prénom}} is substituted in the email but
// not in the preview, and isn't checked against the columns.
const PLACEHOLDER_SRC = String.raw`\{\{([\p{L}\p{N}_][\p{L}\p{N}_ ]*[\p{L}\p{N}_]|[\p{L}\p{N}_])\}\}`;
function placeholderRe(flags = "") { return new RegExp(PLACEHOLDER_SRC, `u${flags}`); }

function $(id) { return document.getElementById(id); }
function hide(el) { if (typeof el === "string") el = $(el); el.classList.add("hidden"); }
function show(el) { if (typeof el === "string") el = $(el); el.classList.remove("hidden"); }
function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
}

function toggle(id, visible) {
    if (visible) show(id); else hide(id);
}

function renderResult(id, result) {
    const el = $(id);
    toggle(el, result !== null);
    if (result !== null) {
        el.className = result.success ? "callout callout-info" : "callout callout-danger";
        el.textContent = result.message;
    }
}

// The only code that enables the step 4-6 buttons or shows the parts of
// those steps; it reads only WizardCore selectors (named after the pure defs
// in spec/wizard.qnt). Call it after any change to state or _auth.
function render() {
    const C = WizardCore;
    const auth = { signedIn: _auth.isSignedIn };

    // Step 4
    $("btn-send-test").disabled = !C.sendTestEnabled(state, auth);
    if (state.testRunning) $("btn-send-test").setAttribute("aria-busy", "true");
    else $("btn-send-test").removeAttribute("aria-busy");
    toggle("btn-retry-test", C.retryVisible(state));
    $("btn-retry-test").disabled = !C.sendTestEnabled(state, auth);
    $("btn-next-4").disabled = !C.nextEnabled(state, 4);
    renderResult("test-result", state.testResult);

    // Step 5
    $("btn-next-5").disabled = !C.nextEnabled(state, 5);
    renderResult("verify-result", state.verifyResult);

    // The test email and the send go out from the signed-in account, so
    // steps 4 and 6 offer sign-in while the page shows signed out.
    const offered = C.signInOffered(state, auth);
    toggle("signin-callout-4", offered && state.currentStep === 4);
    toggle("signin-callout-6", offered && state.currentStep === 6);
    // In browser mode, signing in leaves the page and comes back to step 1.
    for (const el of document.querySelectorAll(".signin-reload-note")) {
        toggle(el, !_auth.desktopMode);
    }

    // Step 6
    const panel = C.sendPanel(state);
    toggle("send-confirm", panel === "confirm");
    toggle("send-progress", panel === "progress");
    toggle("send-log", state.sendStarted);
    toggle("send-result", panel === "done");
    toggle("send-nav", panel !== "done");
    toggle("send-done-nav", panel === "done");
    $("btn-back-6").disabled = !C.back6Enabled(state);
    $("btn-do-send").disabled = !C.doSendEnabled(state, auth, sendConfirmed());
}

function updateStepUI(n) {
    document.querySelectorAll(".step-panel").forEach(p => { p.classList.remove("active"); });
    $(`step-${n}`).classList.add("active");
    document.querySelectorAll(".step-indicator li").forEach(li => {
        const s = parseInt(li.dataset.step, 10);
        li.classList.remove("active", "completed");
        if (s < n) li.classList.add("completed");
        if (s === n) li.classList.add("active");
    });
}

function renderSpreadsheetSummary(data) {
    $("spreadsheet-summary").textContent = `${data.file_name}: ${data.columns.length} columns, ${data.total_rows} rows.`;
    if (data.total_rows > 99) {
        $("spreadsheet-summary").innerHTML += ` <span class="badge badge-warning">Large file — filters required</span>`;
    }
}

function populateSheetSelect(sheets) {
    const sel = $("sheet-select");
    sel.innerHTML = sheets.map(s =>
        `<option value="${escapeHtml(s)}">${escapeHtml(s)}</option>`
    ).join("");
}

function populateColumnDropdowns(columns) {
    populateSelect($("email-column"), columns, true);
    populateSelect($("name-column"), columns, false);
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
    console.log("Navigating to step", n, "from", state.currentStep);
    const gen = ++state.previewGen;
    // Only perform validation/trigger side-effects when advancing forward
    if (n > state.currentStep) {
        // Step 1 → 2: need a spreadsheet uploaded
        if (n === 2 && state.currentStep === 1) {
            if (!validateDataSource()) return;
            initComposeStep();
        }
        // Step 2 → 3: validate compose fields, load recipient preview
        if (n === 3 && state.currentStep === 2) {
            if (!validateCompose()) return;
            const previewOk = await loadPreview(
                () => gen === state.previewGen && state.currentStep === 2,
            );
            if (!previewOk) return;
        }
        // Step 3 → 4: pre-fill test email
        if (n === 4) {
            if (!state.testPassed) {
                checkAuthForStep4();
            }
        }
        // Step 4 → 5: need test to pass first
        if (n === 5) {
            if (!state.testPassed) return;
            startVerify();
        }
        // Step 5 → 6: need verify to pass first
        if (n === 6) {
            if (!state.verifyPassed) return;
            prepareSend();
        }
    }

    state.currentStep = n;
    saveState();
    updateStepUI(n);
    render();
}

function resetTestAndVerify() {
    state.resetTestAndVerify();
}

function confirmGoBack(targetStep) {
    // Going back from test/verify/send steps resets test and verify results
    if (state.currentStep >= 4 && (state.testPassed || state.verifyPassed)) {
        if (!confirm("Going back will discard your test and verification results. You will need to complete these steps again. Continue?")) {
            return;
        }
        resetTestAndVerify();
    }
    // Going back from preview (step 3) to compose (step 2) also invalidates
    if (state.currentStep === 3 && targetStep === 2) {
        resetTestAndVerify();
    }
    goToStep(targetStep);
}

// ---------------------------------------------------------------------------
// Step 1: Data Source
// ---------------------------------------------------------------------------
function validateDataSource() {
    if (!state.spreadsheetData) {
        alert("Please upload a spreadsheet.");
        return false;
    }
    return true;
}

// ---------------------------------------------------------------------------
// Step 2: Compose — initialisation and validation
// ---------------------------------------------------------------------------
function initComposeStep() {
    if (!state.spreadsheetData) return;
    const sd = state.spreadsheetData;
    // Update compose data summary
    $("compose-data-summary").textContent =
        `${sd.file_name}: ${sd.columns.length} columns, ${sd.total_rows} rows.`;

    // Build the read-only preview table on the compose step
    buildComposePreviewTable(sd.columns, sd.rows, sd.total_rows);

    // Populate column dropdowns — preserve previous selections if they're
    // still valid (user went back and came forward without changing data)
    const prevEmail = $("email-column").value;
    const prevName = $("name-column").value;
    populateColumnDropdowns(sd.columns);
    if (prevEmail && sd.columns.includes(prevEmail)) {
        $("email-column").value = prevEmail;
    } else {
        // Auto-detect email column
        const emailPatterns = ["email", "e-mail", "email address", "emailaddress", "mail"];
        for (const col of sd.columns) {
            if (emailPatterns.includes(col.toLowerCase())) {
                $("email-column").value = col;
                break;
            }
        }
    }
    if (prevName && sd.columns.includes(prevName)) {
        $("name-column").value = prevName;
    }

    // Show placeholder chips
    showPlaceholderChips(sd.columns);
}

function validateCompose() {
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
    if (state.sendMode === "bcc" && !$("bcc-blast-to").value.trim()) {
        alert("BCC mode requires a To: address.");
        return false;
    }
    if (state.sendMode === "bcc" && placeholderRe().test(subject + body)) {
        alert("BCC blast mode does not support {{placeholders}} in the subject or body. All recipients receive the same message.");
        return false;
    }
    // Quick pre-check using the total row count from the spreadsheet.
    // The authoritative cap check happens server-side in api_get_recipients
    // (after email validation and filtering), but this gives early feedback
    // when the spreadsheet is clearly too large and no filters are set.
    if (state.spreadsheetData.total_rows > 99 && !$("filter-input").value.trim()) {
        alert(`Too many recipients (${state.spreadsheetData.total_rows}). The web interface supports up to 99 recipients. Add filters to reduce the count, or use the command-line tool.`);
        return false;
    }
    return true;
}

function setSendMode(mode) {
    state.sendMode = mode;
    state.previewGen++;
    state.contentVersion++;
    if (mode === "individual") {
        $("mode-individual").classList.add("active-mode");
        $("mode-individual").classList.remove("outline");
        $("mode-bcc").classList.remove("active-mode");
        $("mode-bcc").classList.add("outline");
        hide("bcc-blast-options");
        if (state.spreadsheetData) show("placeholder-chips");
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
    const has = placeholderRe().test(subject + body);
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
                current_step: state.currentStep,
                test_passed: state.testPassed,
                verify_passed: state.verifyPassed
            })
        });
    } catch (_e) { /* ignore */ }
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
        if (data.desktop_mode) {
            _auth.desktopMode = true;
        }
        if (data.email_wrapper) {
            state.emailWrapper = data.email_wrapper;
        }

        // Restore session spreadsheet if it exists
        if (data.spreadsheet) {
            const s = data.spreadsheet;
            state.spreadsheetData = s;
            show("spreadsheet-info");
            renderSpreadsheetSummary(s);
            populateSheetSelect(s.sheets);
            if (s.active_sheet) $("sheet-select").value = s.active_sheet;
            buildPreviewTable(s.columns, s.rows, s.total_rows);
            showPlaceholderChips(s.columns);
            showFilterChips(s.columns);

            // Restore saved sheet selection — if it differs from the
            // server's active sheet, re-fetch the preview for that sheet.
            const savedSheet = localStorage.getItem("mm_sheet");
            if (savedSheet && s.sheets.includes(savedSheet) && savedSheet !== (s.active_sheet || s.sheets[0])) {
                $("sheet-select").value = savedSheet;
                // Trigger a change to re-fetch the sheet's data
                $("sheet-select").dispatchEvent(new Event("change"));
            }

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

        // Restore wizard state — test and verify results don't survive
        // a page reload because the server-side job results are transient.
        // Only trust these flags when reconnecting to an active job.
        state.testPassed = false;
        state.verifyPassed = false;

        if (data.active_job_id) {
            state.currentJobId = data.active_job_id;
            state.sendStarted = true;
            state.sendOutcome = null;
            // Jump to step 6 (Send) and connect to the existing stream
            window.addEventListener("beforeunload", beforeUnloadWarn);
            state.currentStep = 6;
            updateStepUI(6);
            render();
            const jobId = state.currentJobId;
            streamEvents(jobId, "send-log", (result) => onSendComplete(jobId, result), showSendProgress);
        } else if (data.current_step > 1) {
            // On reload, we have the spreadsheet in session but not the
            // filtered recipients list.  We can only safely restore to
            // step 1 (let the user re-advance) or step 2 (re-run the
            // preview fetch).  Steps 3+ require loading recipients and
            // steps 4-6 require test/verify to have actually run in this
            // page session, so fall back to step 1.
            if (data.current_step >= 2 && state.spreadsheetData) {
                // Restore to step 1 — the user can re-advance with one click
                // since all their inputs are still populated.
                state.currentStep = 1;
                updateStepUI(1);
            }
        }
    } catch (e) { console.error("Error loading config:", e); }
}

// Check auth status
async function checkAuthStatus() {
    try {
        const resp = await apiFetch("/auth/status");
        const data = await resp.json();
        const el = $("auth-display");
        if (data.authenticated) {
            _auth.isSignedIn = true;
            el.innerHTML = `<span class="dot green"></span> Signed in as <span class="email">${escapeHtml(data.email)}</span>`;
            if ($("test-email-input") && !$("test-email-input").value) {
                $("test-email-input").value = data.email;
            }
            if (data.token_expires_at) {
                _auth.tokenExpiresAt = new Date(data.token_expires_at);
            }
        } else {
            _auth.isSignedIn = false;
            el.innerHTML = '<span class="dot gray"></span> Not signed in';
            _auth.tokenExpiresAt = null;
        }
        updateSignInButton();
        render();
    } catch (_e) { /* ignore */ }
}

function sendConfirmed() {
    return $("send-confirm-input").value.trim().toUpperCase() === "SEND";
}

// Auth message below sign-in button
function showAuthMessage(text, type) {
    const el = $("auth-message");
    el.textContent = text;
    el.className = `auth-message ${type}`;
    el.classList.remove("hidden");
}

function hideAuthMessage() {
    const el = $("auth-message");
    el.classList.add("hidden");
}

// Sign-in button state management

function updateSignInButton() {
    const btn = $("btn-sign-in");
    const progress = $("auth-progress");
    btn.removeAttribute("aria-busy");
    // The sign-in buttons on steps 4 and 6 are only shown while signed out.
    for (const id of ["btn-sign-in-4", "btn-sign-in-6"]) {
        $(id).textContent = _auth.signInPoll ? "Cancel sign-in" : "Sign in with Microsoft";
    }

    if (_auth.signInPoll) {
        // Currently waiting for sign-in to complete
        btn.textContent = "Cancel sign-in";
        btn.className = "outline contrast";
        btn.disabled = false;
        progress.classList.remove("hidden");
    } else if (_auth.isSignedIn) {
        btn.textContent = "Sign out";
        btn.className = "outline secondary";
        btn.disabled = false;
        progress.classList.add("hidden");
    } else {
        btn.textContent = "Sign in with Microsoft";
        btn.className = "outline";
        btn.disabled = false;
        progress.classList.add("hidden");
    }
}

function cancelSignIn(reason) {
    if (_auth.signInPoll) {
        clearInterval(_auth.signInPoll);
        _auth.signInPoll = null;
    }
    if (reason) {
        showAuthMessage(reason, "error");
    }
    updateSignInButton();
}

async function doSignOut() {
    const btn = $("btn-sign-in");
    btn.disabled = true;
    btn.setAttribute("aria-busy", "true");
    try {
        await apiFetch("/auth/logout", { method: "POST" });
        showAuthMessage("Signed out successfully.", "info");
    } catch (e) {
        showAuthMessage(`Sign-out failed: ${e.message}`, "error");
    }
    await checkAuthStatus();
}

async function onSignInClick() {
    // If currently waiting for sign-in, cancel it
    if (_auth.signInPoll) {
        cancelSignIn("Sign-in cancelled.");
        return;
    }

    // If signed in, sign out
    if (_auth.isSignedIn) {
        await doSignOut();
        return;
    }

    // Otherwise, start sign-in
    hideAuthMessage();
    const clientId = $("client-id").value.trim();
    const tenantId = $("tenant-id").value.trim() || "common";
    if (!clientId) {
        showAuthMessage("Please enter a Client ID first.", "error");
        if (state.currentStep !== 1) alert("Enter a Client ID on step 1 before signing in.");
        return;
    }

    if (_auth.desktopMode) {
        // Desktop mode: use interactive auth via system browser
        try {
            await apiFetch("/auth/interactive", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({client_id: clientId, tenant_id: tenantId}),
            });

            // Poll auth status until authenticated or timeout
            const deadline = Date.now() + 5 * 60 * 1000; // 5 minutes
            let pollBusy = false;
            _auth.signInPoll = setInterval(async () => {
                if (pollBusy) return;
                if (Date.now() > deadline) {
                    cancelSignIn("Sign-in timed out. Please try again.");
                    return;
                }
                pollBusy = true;
                try {
                    const resp = await apiFetch("/auth/status");
                    const data = await resp.json();
                    if (data.authenticated) {
                        clearInterval(_auth.signInPoll);
                        _auth.signInPoll = null;
                        updateSignInButton();
                        showAuthMessage("Signed in successfully.", "success");
                        checkAuthStatus();
                    }
                } catch (_e) { /* ignore poll errors */ }
                finally { pollBusy = false; }
            }, 2000);
            updateSignInButton();
        } catch (e) {
            cancelSignIn(`Failed to start sign-in: ${e.message}`);
        }
    } else {
        // Browser mode: redirect to auth login
        window.location.href = `/auth/login?client_id=${encodeURIComponent(clientId)}&tenant_id=${encodeURIComponent(tenantId)}`;
    }
}

$("btn-sign-in").addEventListener("click", onSignInClick);
$("btn-sign-in-4").addEventListener("click", onSignInClick);
$("btn-sign-in-6").addEventListener("click", onSignInClick);

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
            summary = `<div class="callout callout-danger mt-0"><strong>Connection Error:</strong> ${escapeHtml(data.error)}</div>`;
        } else if (data.token_valid) {
            summary = `<div class="callout callout-success mt-0"><strong>Success:</strong> Connection is healthy and token is valid.</div>`;
        } else if (data.authority_reachable) {
            summary = `<div class="callout callout-warning mt-0"><strong>Partial Success:</strong> Authority is reachable, but you are not signed in or token has expired.</div>`;
        } else {
            summary = `<div class="callout callout-danger mt-0"><strong>Failure:</strong> Microsoft login authority is not reachable. Check your internet connection.</div>`;
        }

        $("auth-diag-content").innerHTML = `${summary}<pre>${JSON.stringify(data, null, 2)}</pre>`;
    } catch (e) {
        $("auth-diag-content").innerHTML = `<div class="callout callout-danger mt-0"><strong>Error:</strong> ${escapeHtml(e.message)}</div>`;
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
        state.spreadsheetData = data;
        state.previewGen++;
        state.contentVersion++;
        show("spreadsheet-info");
        renderSpreadsheetSummary(data);
        $("btn-next-1").disabled = false;
        populateSheetSelect(data.sheets);
        if (data.active_sheet) $("sheet-select").value = data.active_sheet;

        // Build preview table on step 1
        buildPreviewTable(data.columns, data.rows, data.total_rows);
        showFilterChips(data.columns);
    } catch (e) {
        alert(`Upload error: ${e.message}`);
    }
});

// Sheet change — re-read preview for the selected sheet
$("sheet-select").addEventListener("change", async () => {
    if (!state.spreadsheetData) return;
    const sheet = $("sheet-select").value;

    try {
        const resp = await apiFetch("/api/change-sheet", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ sheet: sheet || null }),
        });
        const data = await resp.json();
        if (!resp.ok) {
            alert(data.error || "Failed to change sheet");
            return;
        }
        state.spreadsheetData = data;
        state.previewGen++;
        state.contentVersion++;
        renderSpreadsheetSummary(data);
        buildPreviewTable(data.columns, data.rows, data.total_rows);
        showFilterChips(data.columns);
        try { localStorage.setItem("mm_sheet", sheet); } catch (_e) { /* ignore */ }
    } catch (e) {
        alert(`Error changing sheet: ${e.message}`);
    }
});

function populateSelect(sel, cols, required) {
    let html = required ? '<option value="">-- select --</option>' : '<option value="">-- none --</option>';
    for (const c of cols) {
        html += `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`;
    }
    sel.innerHTML = html;
}

function buildPreviewTable(columns, rows, totalRows) {
    const thead = document.querySelector("#preview-table thead");
    const tbody = document.querySelector("#preview-table tbody");
    thead.innerHTML = `<tr>${columns.map(c => `<th>${escapeHtml(c)}</th>`).join("")}</tr>`;
    tbody.innerHTML = rows.map(row =>
        `<tr>${columns.map(c => `<td>${escapeHtml(row[c] || "")}</td>`).join("")}</tr>`
    ).join("");
    // Show truncation notice if not all rows are displayed
    const caption = document.querySelector("#preview-table caption") || document.createElement("caption");
    if (totalRows > rows.length) {
        caption.textContent = `Showing ${rows.length} of ${totalRows} rows`;
        if (!caption.parentNode) document.querySelector("#preview-table").prepend(caption);
    } else {
        caption.remove();
    }
}

function buildComposePreviewTable(columns, rows, totalRows) {
    const thead = document.querySelector("#compose-preview-table thead");
    const tbody = document.querySelector("#compose-preview-table tbody");
    thead.innerHTML = `<tr>${columns.map(c => `<th>${escapeHtml(c)}</th>`).join("")}</tr>`;
    tbody.innerHTML = rows.map(row =>
        `<tr>${columns.map(c => `<td>${escapeHtml(row[c] || "")}</td>`).join("")}</tr>`
    ).join("");
    const caption = document.querySelector("#compose-preview-table caption") || document.createElement("caption");
    if (totalRows > rows.length) {
        caption.textContent = `Showing ${rows.length} of ${totalRows} rows`;
        if (!caption.parentNode) document.querySelector("#compose-preview-table").prepend(caption);
    } else {
        caption.remove();
    }
}

function showPlaceholderChips(columns) {
    show("placeholder-chips");
    const container = $("chips");
    container.innerHTML = "";
    for (const col of columns) {
        const chip = document.createElement("span");
        chip.className = "chip";
        chip.textContent = `{{${col}}}`;
        chip.addEventListener("mousedown", (e) => {
            // Use mousedown and preventDefault to avoid the input losing focus
            // when clicking the chip.
            e.preventDefault();
            const insertion = `{{${col}}}`;

            const active = document.activeElement;
            if ($("html-toggle").checked && state.trixEditor && !$("source-toggle").checked
                && active !== $("subject-input")) {
                state.trixEditor.insertString(insertion);
            } else {
                // Insert into textarea (subject, body, or html-source)
                let target = active;
                if (target !== $("subject-input") && target !== $("body-input")
                    && target !== $("html-source")) {
                    target = $("html-toggle").checked ? $("html-source") : $("body-input");
                }

                const start = target.selectionStart;
                const end = target.selectionEnd;
                const text = target.value;

                target.value = text.substring(0, start) + insertion + text.substring(end);
                target.focus();
                const newPos = start + insertion.length;
                target.setSelectionRange(newPos, newPos);
            }

            // Trigger validation/auto-save
            onTemplateChange();
        });
        container.appendChild(chip);
    }
}

function showFilterChips(columns) {
    show("filter-chips");
    const container = $("filter-chips-container");
    container.innerHTML = "";
    for (const col of columns) {
        const chip = document.createElement("span");
        chip.className = "chip";
        chip.textContent = col;
        chip.dataset.col = col;
        container.appendChild(chip);
    }
}

$("filter-chips-container").addEventListener("mousedown", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    e.preventDefault();
    const col = chip.dataset.col;
    const target = $("filter-input");
    const text = target.value;
    const insertion = `${col}=`;

    // Prepend newline if there is existing content not ending with a newline
    const prefix = text.trimEnd().length > 0 && !text.endsWith("\n") ? "\n" : "";

    const start = target.selectionStart;
    const end = target.selectionEnd;
    // When cursor is at the end (or textarea has no focus), append with newline logic
    const atEnd = start === text.length;
    if (atEnd) {
        target.value = text + prefix + insertion;
    } else {
        target.value = text.substring(0, start) + insertion + text.substring(end);
    }
    target.focus();
    const newPos = target.value.length;
    if (atEnd) {
        target.setSelectionRange(newPos, newPos);
    } else {
        const pos = start + insertion.length;
        target.setSelectionRange(pos, pos);
    }
    onTemplateChange();
});

// ---------------------------------------------------------------------------
// Trix HTML editor — sits outside .pico in the DOM for CSS isolation
// ---------------------------------------------------------------------------
let trixEditorEl = null;
document.addEventListener('trix-initialize', (e) => {
    trixEditorEl = e.target;
    state.trixEditor = e.target.editor;
});

document.addEventListener('trix-change', () => {
    // Trix appends <br> inside every <p>, producing <p><br></p> for blank
    // lines.  The <br> adds a full line-height on top of the <p> margin,
    // causing double spacing in email.  Strip trailing <br>, then remove
    // empty <p></p> tags (the previous paragraph's margin provides spacing).
    $('body-input').value = $('trix-input').value
        .replace(/<br>\s*<\/p>/gi, "</p>")
        .replace(/<p>\s*<\/p>/gi, "");
    onTemplateChange();
});

document.addEventListener('trix-file-accept', (e) => {
    e.preventDefault();
});

// Clean pasted HTML before Trix's parser converts block-element margins
// into literal <br> tags (which causes double spacing).  Simplify the
// block structure so Trix can rebuild it cleanly.
// The clipboard HTML is untrusted, and Trix only sanitises it after this
// handler, so parse it in an inert document: an element of the live
// document would load <img> and fire inline handlers such as onerror.
document.addEventListener('trix-before-paste', (e) => {
    const paste = e.paste;
    if (!paste.html) return;
    const doc = document.implementation.createHTMLDocument("");
    const div = doc.createElement("div");
    div.innerHTML = paste.html;
    // Remove empty paragraphs/divs (margin-only spacers)
    for (const el of div.querySelectorAll("p, div")) {
        if (!el.textContent.trim() && !el.querySelector("img, table")) {
            el.remove();
        }
    }
    // Strip <br> that follows block-level content (Trix would double them)
    for (const br of div.querySelectorAll("p > br:last-child, div > br:last-child")) {
        if (br.previousSibling) br.remove();
    }
    paste.html = div.innerHTML;
});

function activateHtmlEditor() {
    const existingBody = $("body-input").value;
    if (existingBody) {
        if (state.trixEditor) {
            state.trixEditor.loadHTML(existingBody);
        } else {
            // trix-initialize hasn't fired yet; seed the hidden input
            // so Trix picks up the content when it initialises.
            $("trix-input").value = existingBody;
        }
    }
    $("source-toggle").checked = false;
    hide("html-source");
    if (trixEditorEl) show(trixEditorEl);
    const toolbar = trixEditorEl?.toolbarElement;
    if (toolbar) show(toolbar);
    hide("body-input");
    show("html-editor-wrap");
}

// Real-time placeholder and HTML validation
let validationTimer = null;
function onTemplateChange() {
    state.previewGen++;
    state.contentVersion++;
    clearTimeout(validationTimer);
    validationTimer = setTimeout(() => {
        validatePlaceholders();
        validateHtmlBody();
        if (state.sendMode === "bcc") checkBccPlaceholders();
    }, 500);
    state.formDirty = true;
}
$("subject-input").addEventListener("input", onTemplateChange);
$("body-input").addEventListener("input", onTemplateChange);
$("email-column").addEventListener("change", onTemplateChange);
$("name-column").addEventListener("change", onTemplateChange);
$("html-toggle").addEventListener("change", () => {
    const isHtml = $("html-toggle").checked;
    if (isHtml) {
        activateHtmlEditor();
    } else {
        const html = $("body-input").value;
        if (/<[a-zA-Z][^>]*>/.test(html)) {
            if (!confirm("Body contains HTML formatting. Switch to plain text? Tags will be preserved as text.")) {
                $("html-toggle").checked = true;
                return;
            }
        }
        show("body-input");
        hide("html-editor-wrap");
    }
    onTemplateChange();
});
$("source-toggle").addEventListener("change", () => {
    const toolbar = trixEditorEl?.toolbarElement;
    if ($("source-toggle").checked) {
        $("html-source").value = $("trix-input").value;
        hide(trixEditorEl);
        if (toolbar) hide(toolbar);
        show("html-source");
    } else {
        if (state.trixEditor) state.trixEditor.loadHTML($("html-source").value);
        show(trixEditorEl);
        if (toolbar) show(toolbar);
        hide("html-source");
    }
});
$("html-source").addEventListener("input", () => {
    $("body-input").value = $("html-source").value;
    onTemplateChange();
});
$("cc-input").addEventListener("input", onTemplateChange);
$("bcc-input").addEventListener("input", onTemplateChange);
$("reply-to-input").addEventListener("input", onTemplateChange);
$("filter-input").addEventListener("input", onTemplateChange);

function validatePlaceholders() {
    if (!state.spreadsheetData) return;
    const subject = $("subject-input").value;
    const body = $("body-input").value;
    const combined = subject + body;
    const used = [...combined.matchAll(placeholderRe("g"))].map(m => m[1]);
    const colsLower = state.spreadsheetData.columns.map(c => c.toLowerCase());
    const bad = used.filter(p => !colsLower.includes(p.toLowerCase()));
    const el = $("placeholder-errors");
    if (bad.length > 0) {
        const unique = [...new Set(bad)];
        const available = state.spreadsheetData.columns.map(escapeHtml).join(", ");
        el.innerHTML = unique.map(p =>
            `No column named <strong>{{${escapeHtml(p)}}}</strong>. Available: ${available}`
        ).join("<br>");
        show(el);
    } else {
        hide(el);
    }
}

const GMAIL_CLIP_KB = 102;
const EMAIL_WRAPPER_KB = 1.5;
const HTML_TAG_RE = /<[a-zA-Z][^>]*>/;
const BLOCK_OR_BR_RE = /<(br|p|div|table|tr|td|li|ul|ol|h[1-6])\b/i;
const STRIPPED_TAGS_RE = /<(script|iframe|form|embed|object)\b/i;
const EXT_STYLESHEET_RE = /<link\b[^>]*rel\s*=\s*["']stylesheet["'][^>]*>/i;
const STYLE_BLOCK_RE = /<style\b/i;
const FULL_HTML_DOC_RE = /<html\b|<!doctype/i;
const STRIP_DOC_RE = /<!DOCTYPE[^>]*>|<\/?html[^>]*>|<head\b[^>]*>[\s\S]*?<\/head>|<\/?body[^>]*>/gi;

/** Strip full-document HTML tags; the app always adds its own wrapper. */
function stripHtmlDocTags(body) {
    if (!FULL_HTML_DOC_RE.test(body)) return body;
    return body.replace(STRIP_DOC_RE, "").trim();
}

function validateHtmlBody() {
    const el = $("html-warnings");
    if (!$("html-toggle").checked) { hide(el); return; }
    const body = $("body-input").value;
    if (!body.trim()) { hide(el); return; }

    const warnings = [];

    if (!HTML_TAG_RE.test(body)) {
        warnings.push(
            "<strong>No HTML tags detected.</strong> The body appears to be plain text " +
            "but will be sent as HTML. Line breaks will not be visible to recipients. " +
            "Use <code>&lt;br&gt;</code> for line breaks or <code>&lt;p&gt;</code> for paragraphs."
        );
    } else if (/\n/.test(body) && !BLOCK_OR_BR_RE.test(body)) {
        warnings.push(
            "<strong>Line breaks may not render.</strong> The body contains newlines but no " +
            "<code>&lt;br&gt;</code>, <code>&lt;p&gt;</code>, or <code>&lt;div&gt;</code> tags. " +
            "Newlines are ignored in HTML — use <code>&lt;br&gt;</code> for line breaks."
        );
    }

    if (STRIPPED_TAGS_RE.test(body)) {
        const found = [];
        for (const tag of ["script", "iframe", "form", "embed", "object"]) {
            if (new RegExp(`<${tag}\\b`, "i").test(body)) found.push(`&lt;${tag}&gt;`);
        }
        warnings.push(
            `<strong>Unsupported tags:</strong> ${found.join(", ")} will be stripped by email clients.`
        );
    }

    if (EXT_STYLESHEET_RE.test(body)) {
        warnings.push(
            "<strong>External stylesheets ignored:</strong> <code>&lt;link rel=\"stylesheet\"&gt;</code> " +
            "is not supported in email. Use inline <code>style</code> attributes instead."
        );
    }

    if (STYLE_BLOCK_RE.test(body)) {
        warnings.push(
            "<strong>Inline &lt;style&gt; blocks may be stripped</strong> by email clients " +
            "(Gmail, Outlook.com). Use inline <code>style</code> attributes on each " +
            "element for reliable rendering."
        );
    }

    if (FULL_HTML_DOC_RE.test(body)) {
        warnings.push(
            "<strong>Full HTML document tags detected</strong> (&lt;!DOCTYPE&gt;, &lt;html&gt;, " +
            "&lt;head&gt;, &lt;body&gt;). These will be stripped before sending — the app " +
            "always adds its own email compatibility wrappers. Just provide the body content."
        );
    }

    const sizeKb = new Blob([body]).size / 1024 + EMAIL_WRAPPER_KB;
    if (sizeKb > GMAIL_CLIP_KB) {
        warnings.push(
            `<strong>Large body (~${Math.round(sizeKb)} KB with email wrapper):</strong> Gmail clips ` +
            "emails over ~102 KB. Recipients may see a truncated message."
        );
    }

    if (warnings.length > 0) {
        el.innerHTML = warnings.join("<hr>");
        show(el);
    } else {
        hide(el);
    }
}

// ---------------------------------------------------------------------------
// Step 3: Preview
// ---------------------------------------------------------------------------
// isCurrent() is false once the user has navigated or edited since the
// request was sent; the response is then dropped.
async function loadPreview(isCurrent = () => true) {
    $("btn-next-2").ariaBusy = "true";
    $("btn-next-2").disabled = true;

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
        if (!isCurrent()) return false;

        if (!resp.ok) {
            alert(data.error || "Failed to load recipients");
            return false;
        }

        // Store the final filtered recipients in state
        state.spreadsheetData.rows = data.recipients;

        const rows = state.spreadsheetData.rows;
        if (!rows || rows.length === 0) {
            alert("No recipients found (check your filters and email column).");
            return false;
        }

        state.previewIndex = 0;
        renderPreviewRecipient();
        buildRecipientsTable();

        // Show invalid email warning if any were skipped
        showInvalidEmailWarning(data.invalid_emails || [], data.total_before_validation || 0);

        // Update verify/send recipient counts
        $("verify-count").textContent = rows.length;
        $("send-count").textContent = rows.length;
        return true;

    } catch (e) {
        if (isCurrent()) alert(`Error loading preview: ${e.message}`);
        return false;
    } finally {
        $("btn-next-2").ariaBusy = "false";
        $("btn-next-2").disabled = false;
    }
}

function renderPreviewRecipient() {
    const recipients = getRecipients();
    if (!recipients || recipients.length === 0) return;
    const row = recipients[state.previewIndex];
    const subject = $("subject-input").value;
    const body = $("body-input").value;

    // Client-side template rendering for preview
    // In BCC mode all recipients get the same message — no substitution
    const rendered_subject = state.sendMode === "bcc" ? subject : renderTemplate(subject, row);
    const rendered_body = state.sendMode === "bcc" ? body : renderTemplate(body, row);

    $("preview-subject").textContent = rendered_subject;
    const isHtml = $("html-toggle").checked;
    if (isHtml) {
        hide("preview-body");
        show("preview-body-html");
        const w = state.emailWrapper;
        $("preview-body-html").srcdoc = w
            ? w.head + stripHtmlDocTags(rendered_body) + w.tail
            : rendered_body;
    } else {
        show("preview-body");
        hide("preview-body-html");
        $("preview-body").textContent = rendered_body;
    }

    // Headers
    if (state.sendMode === "bcc") {
        $("preview-to").textContent = $("bcc-blast-to").value || "(none)";
        $("preview-cc").textContent = "(none in BCC mode)";
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

    $("preview-recipient-label").textContent = `Previewing recipient ${state.previewIndex + 1} of ${recipients.length}`;
}

function renderTemplate(template, data) {
    const lowerData = {};
    for (const [k, v] of Object.entries(data)) {
        lowerData[k.toLowerCase()] = v;
    }
    return template.replace(placeholderRe("g"), (match, key) => {
        return lowerData[key.toLowerCase()] !== undefined ? lowerData[key.toLowerCase()] : match;
    });
}

function changePreviewRecipient(delta) {
    const recipients = getRecipients();
    if (!recipients) return;
    state.previewIndex = Math.max(0, Math.min(recipients.length - 1, state.previewIndex + delta));
    renderPreviewRecipient();
}

function buildRecipientsTable() {
    const recipients = getRecipients();
    if (!recipients || !state.spreadsheetData) return;
    const emailCol = $("email-column").value;
    // Show the email column first, then all other columns
    const cols = [emailCol, ...state.spreadsheetData.columns.filter(c => c !== emailCol)];
    const thead = document.querySelector("#recipients-table thead");
    const tbody = document.querySelector("#recipients-table tbody");
    thead.innerHTML = `<tr>${cols.map(c => `<th>${escapeHtml(c)}</th>`).join("")}</tr>`;
    tbody.innerHTML = recipients.map(row =>
        `<tr>${cols.map(c => `<td>${escapeHtml(row[c] || "")}</td>`).join("")}</tr>`
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
        `<ul class="skipped-list">${skippedList}</ul>`;
    show(el);
}

// ---------------------------------------------------------------------------
// Step 4: Test Email
// ---------------------------------------------------------------------------
function checkAuthForStep4() {
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

    state.testPassed = false;
    const gen = ++state.testGen;
    const isCurrent = () => gen === state.testGen;
    saveState();

    state.testRunning = true;
    state.testFailed = false;
    state.testResult = null;
    render();
    show("test-log");
    $("test-log").innerHTML = "";

    const form = buildJobFormData("test_email");
    form.set("test_email", testAddr);

    try {
        const resp = await apiFetch("/api/start-job", { method: "POST", body: form, headers: { "X-CSRF-Token": CSRF_TOKEN } });
        const data = await resp.json();
        if (!isCurrent()) return;
        if (!resp.ok) {
            showTestResult(false, data.error || "Failed to start job");
            return;
        }
        state.currentJobId = data.job_id;
        streamEvents(data.job_id, "test-log", (result) => {
            if (result.status === "completed") {
                state.testPassed = true;
                saveState();
                showTestResult(true, "Test email sent successfully!");
            } else {
                const errMsg = categoriseError(result.error || "Test email failed");
                showTestResult(false, errMsg);
            }
        }, null, isCurrent);
    } catch (e) {
        if (isCurrent()) showTestResult(false, `Error: ${e.message}`);
    }
}

function showTestResult(success, msg) {
    state.testRunning = false;
    state.testFailed = !success;
    state.testResult = { success, message: msg };
    render();
    // A test that failed for want of a token shows the sign-in callout.
    if (!success) checkAuthStatus();
}

// ---------------------------------------------------------------------------
// Step 5: Verify (Dry Run)
// ---------------------------------------------------------------------------
function startVerify() {
    const recipients = getRecipients();
    $("verify-count").textContent = recipients ? recipients.length : "?";
    $("verify-log").innerHTML = "";
    state.verifyResult = null;
    state.verifyPassed = false;
    render();
    const gen = ++state.verifyGen;
    const isCurrent = () => gen === state.verifyGen;
    saveState();

    const form = buildJobFormData("dry_run");

    apiFetch("/api/start-job", { method: "POST", body: form, headers: { "X-CSRF-Token": CSRF_TOKEN } })
        .then(r => r.json())
        .then(data => {
            if (!isCurrent()) return;
            if (data.error) {
                showVerifyResult(false, data.error);
                return;
            }
            state.currentJobId = data.job_id;
            streamEvents(data.job_id, "verify-log", (result) => {
                if (result.status === "completed") {
                    state.verifyPassed = true;
                    saveState();
                    const recs = getRecipients();
                    const n = recs ? recs.length : "?";
                    const estSec = recs ? recs.length * 2 : "?";
                    let msg = `${n} emails ready to send. Estimated time: ~${estSec} seconds (2-second delay between sends).`;
                    // Token expiry check
                    if (_auth.tokenExpiresAt && recs) {
                        const estEndMs = Date.now() + recs.length * 2000;
                        if (estEndMs > _auth.tokenExpiresAt.getTime()) {
                            msg += "\n\u26a0\ufe0f Warning: Your authentication token may expire before sending completes. Consider signing in again before proceeding.";
                        }
                    }
                    showVerifyResult(true, msg);
                } else {
                    showVerifyResult(false, result.error || "Verification failed");
                }
            }, null, isCurrent);
        })
        .catch(e => { if (isCurrent()) showVerifyResult(false, `Error: ${e.message}`); });
}

function showVerifyResult(success, msg) {
    state.verifyResult = { success, message: msg };
    render();
}

// ---------------------------------------------------------------------------
// Step 6: Send
// ---------------------------------------------------------------------------
function prepareSend() {
    state.sendStarted = false;
    state.sendResults = null;
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

    state.sendOutcome = null;
    $("send-confirm-input").value = "";
    render();
    checkAuthStatus();
}

$("send-confirm-input").addEventListener("input", render);

async function startSend() {
    state.sendStarted = true;
    state.sendOutcome = null;
    // Until the response names the send's job, Stop is queued rather than
    // sent to the previous (dry-run) job.
    state.currentJobId = null;
    state.stopQueued = false;
    $("send-log").innerHTML = "";
    $("send-progress-text").textContent = "Sending...";
    $("send-progress-bar").value = 0;
    render();

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
        state.currentJobId = data.job_id;
        if (state.stopQueued) {
            state.stopQueued = false;
            stopSend();
        }
        streamEvents(data.job_id, "send-log", (result) => onSendComplete(data.job_id, result), showSendProgress);
    } catch (e) {
        window.removeEventListener("beforeunload", beforeUnloadWarn);
        showSendResult(false, `Error: ${e.message}`);
    }
}

function showSendProgress(current, total) {
    $("send-progress-bar").max = total;
    $("send-progress-bar").value = current;
    $("send-progress-text").textContent = `Sending ${current} of ${total}...`;
}

// A send that failed part-way still lists the emails that went out
// (spec/wizard.qnt, failedSendReported).
function onSendComplete(jobId, result) {
    window.removeEventListener("beforeunload", beforeUnloadWarn);
    if (result.status === "completed" || result.status === "stopped"
        || (result.results && result.results.length > 0)) {
        fetchAndShowSendResults(jobId);
    } else {
        showSendResult(false, result.error || "Send failed");
    }
}

function beforeUnloadWarn(e) {
    e.preventDefault();
    e.returnValue = "";
}

async function stopSend() {
    if (!state.currentJobId) {
        if (state.sendStarted) state.stopQueued = true;
        return;
    }
    await apiFetch(`/api/job/${state.currentJobId}/stop`, {
        method: "POST",
        headers: { "X-CSRF-Token": CSRF_TOKEN },
    });
}

async function fetchAndShowSendResults(jobId) {
    try {
        const resp = await apiFetch(`/api/job/${jobId}/status`);
        const data = await resp.json();
        state.sendResults = data.results || [];
        const summary = data.summary || {};
        state.sendOutcome = "results";
        render();

        let html = `<h4>Results</h4>`;
        if (data.status === "stopped") {
            html += `<div class="callout callout-warning">Sending was stopped. Recipients not listed below were not sent an email.</div>`;
        } else if (data.status === "failed") {
            html += `<div class="callout callout-danger">Sending failed: ${escapeHtml(data.error || "unknown error")}. Recipients not listed below were not sent an email.</div>`;
        }
        html += `<p><strong>Total:</strong> ${summary.total || 0} | `;
        html += `<span class="success"><strong>Sent:</strong> ${summary.sent || 0}</span> | `;
        html += `<span class="failure"><strong>Failed:</strong> ${summary.failed || 0}</span></p>`;

        if (state.sendResults.length > 0) {
            html += `<table class="striped results-table"><thead><tr><th>Email</th><th>Status</th><th>Error</th></tr></thead><tbody>`;
            for (const r of state.sendResults) {
                const cls = r.success ? "success" : "failure";
                html += `<tr class="${cls}"><td>${escapeHtml(r.email)}</td><td>${r.success ? "Sent" : "Failed"} ${r.status_code ? `(${r.status_code})` : ""}</td><td>${escapeHtml(r.error || "")}</td></tr>`;
            }
            html += `</tbody></table>`;
        }

        $("send-result").innerHTML = html;
    } catch (e) {
        showSendResult(false, `Error fetching results: ${e.message}`);
    }
}

function showSendResult(success, msg) {
    state.sendOutcome = "error";
    render();
    $("send-result").innerHTML = `<div class="callout ${success ? "callout-info" : "callout-danger"}">${escapeHtml(msg)}</div>`;
    window.removeEventListener("beforeunload", beforeUnloadWarn);
}

function sanitizeCsvValue(val) {
    if (!val) return val;
    const s = String(val);
    if (/^[=+@\-\t\r]/.test(s)) return `\t${s}`;
    return s;
}

function downloadCsv() {
    if (!state.sendResults || state.sendResults.length === 0) return;
    let csv = "email,success,status_code,error\n";
    for (const r of state.sendResults) {
        csv += `"${sanitizeCsvValue(r.email)}",${r.success},${r.status_code || ""},"${sanitizeCsvValue((r.error || "").replace(/"/g, '""'))}"\n`;
    }
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "mergemail365-results.csv";
    a.click();
    URL.revokeObjectURL(url);
}

function newMerge() {
    // Reset all state
    state.resetAll();

    // Clean up server-side temp files and session state
    apiFetch("/api/reset", { method: "POST" }).catch(() => {});

    // Clear Step 1 — spreadsheet
    $("spreadsheet-file").value = "";
    hide("spreadsheet-info");
    $("btn-next-1").disabled = false;

    // Clear Step 2 — compose fields
    $("subject-input").value = "";
    $("body-input").value = "";
    $("email-column").innerHTML = '<option value="">-- select --</option>';
    $("name-column").innerHTML = '<option value="">-- none --</option>';
    $("html-toggle").checked = false;
    $("source-toggle").checked = false;
    if (state.trixEditor) {
        state.trixEditor.loadHTML('');
    }
    $("trix-input").value = "";
    $("html-source").value = "";
    show("body-input");
    hide("html-editor-wrap");
    hide("placeholder-chips");
    hide("filter-chips");
    hide("placeholder-errors");
    hide("html-warnings");

    // Clear Step 2 — options
    $("cc-input").value = "";
    $("bcc-input").value = "";
    $("reply-to-input").value = "";
    $("bcc-blast-to").value = "";
    $("importance-select").value = "";
    $("filter-input").value = "";
    $("attachment-input").value = "";

    // Reset send mode to individual
    setSendMode("individual");

    // Clear Step 3 (Preview)
    $("preview-subject").textContent = "";
    $("preview-body").textContent = "";
    hide("preview-body-html");
    hide("invalid-email-warning");
    document.querySelector("#recipients-table thead").innerHTML = "";
    document.querySelector("#recipients-table tbody").innerHTML = "";

    // Clear Step 4 (Test)
    $("test-email-input").value = "";
    $("test-log").innerHTML = "";
    hide("test-log");
    $("test-result").innerHTML = "";

    // Clear Step 5 (Verify)
    $("verify-log").innerHTML = "";
    hide("verify-log");
    $("verify-result").innerHTML = "";

    // Clear Step 6 (Send)
    $("send-confirm-input").value = "";
    $("send-log").innerHTML = "";
    $("send-result").innerHTML = "";
    $("send-progress-bar").value = 0;

    // Clear localStorage
    try {
        localStorage.removeItem("mm_subject");
        localStorage.removeItem("mm_body");
        localStorage.removeItem("mm_email_col");
        localStorage.removeItem("mm_name_col");
        localStorage.removeItem("mm_html");
        localStorage.removeItem("mm_sheet");
    } catch (_e) { /* ignore */ }

    goToStep(1);
}

// ---------------------------------------------------------------------------
// SSE streaming
// ---------------------------------------------------------------------------
function streamEvents(jobId, logPanelId, onComplete, onProgress, isCurrent = () => true) {
    const panel = $(logPanelId);
    const evtSource = new EventSource(`/api/job/${jobId}/events`);

    evtSource.onmessage = (e) => {
        // A stale job (superseded or invalidated) gets no more log lines
        // and its completion must not touch the current step's state.
        if (!isCurrent()) {
            evtSource.close();
            return;
        }
        const event = JSON.parse(e.data);
        if (event.type === "done") {
            evtSource.close();
            // Fetch final status
            apiFetch(`/api/job/${jobId}/status`)
                .then(r => r.json())
                .then(data => {
                    if (!isCurrent()) return;
                    onComplete(data);
                    saveState();
                });
            return;
        }
        if (event.type === "log") {
            const entry = document.createElement("div");
            entry.className = `log-entry ${event.data.level || "INFO"}`;
            entry.textContent = `[${event.data.timestamp}] ${event.data.message}`;
            panel.appendChild(entry);
            panel.scrollTop = panel.scrollHeight;
            // Extract send progress from log messages like "Sending [3/42]"
            if (onProgress) {
                const match = event.data.message.match(/\[(\d+)\/(\d+)\]/);
                if (match) onProgress(parseInt(match[1], 10), parseInt(match[2], 10));
            }
        }
        if (event.type === "completed" || event.type === "error") {
            // Will be followed by "done"
        }
    };

    evtSource.onerror = () => {
        evtSource.close();
        if (!isCurrent()) return;
        apiFetch(`/api/job/${jobId}/status`)
            .then(r => r.json())
            .then(data => { if (isCurrent()) onComplete(data); })
            .catch(() => { if (isCurrent()) onComplete({ status: "failed", error: "Connection lost" }); });
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
    const isHtml = $("html-toggle").checked;
    let body = $("body-input").value;
    if (isHtml) body = stripHtmlDocTags(body);
    form.set("body", body);

    if ($("name-column").value) form.set("name_column", $("name-column").value);
    if ($("sheet-select").value) form.set("sheet", $("sheet-select").value);
    if ($("importance-select").value) form.set("importance", $("importance-select").value);
    if ($("cc-input").value) form.set("cc", $("cc-input").value);
    if ($("bcc-input").value) form.set("bcc", $("bcc-input").value);
    if ($("reply-to-input").value) form.set("reply_to", $("reply-to-input").value);
    if (isHtml) form.set("html", "true");
    form.set("save_to_sent_items", "true");
    if ($("filter-input").value.trim()) form.set("filters", $("filter-input").value.trim());

    if (state.sendMode === "bcc") {
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
        showAuthMessage("Signed in successfully.", "success");
        checkAuthStatus();
        history.replaceState(null, "", window.location.pathname + window.location.search);
    } else if (hash.startsWith("#auth-error=")) {
        const error = decodeURIComponent(hash.substring("#auth-error=".length));
        showAuthMessage(`Sign-in failed: ${error}`, "error");
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
// Expose functions called from HTML onclick attributes
// ---------------------------------------------------------------------------
window.goToStep = goToStep;
window.setSendMode = setSendMode;
window.confirmGoBack = confirmGoBack;
window.changePreviewRecipient = changePreviewRecipient;
window.sendTestEmail = sendTestEmail;
window.startSend = startSend;
window.stopSend = stopSend;
window.downloadCsv = downloadCsv;
window.newMerge = newMerge;

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
        if (!state.formDirty) return;
        state.formDirty = false;
        try {
            localStorage.setItem("mm_subject", $("subject-input").value);
            localStorage.setItem("mm_body", $("body-input").value);
            localStorage.setItem("mm_email_col", $("email-column").value);
            localStorage.setItem("mm_name_col", $("name-column").value);
            localStorage.setItem("mm_html", $("html-toggle").checked ? "1" : "");
        } catch (_e) { /* ignore */ }
    }, 5000);

    // Restore from localStorage
    try {
        const savedSubject = localStorage.getItem("mm_subject");
        const savedBody = localStorage.getItem("mm_body");
        const savedEmailCol = localStorage.getItem("mm_email_col");
        const savedNameCol = localStorage.getItem("mm_name_col");
        const savedHtml = localStorage.getItem("mm_html");

        if (savedSubject && !$("subject-input").value) $("subject-input").value = savedSubject;
        if (savedBody && !$("body-input").value) $("body-input").value = savedBody;
        if (savedEmailCol && !$("email-column").value) $("email-column").value = savedEmailCol;
        if (savedNameCol && !$("name-column").value) $("name-column").value = savedNameCol;
        if (savedHtml === "1") {
            $("html-toggle").checked = true;
            activateHtmlEditor();
        }
    } catch (_e) { /* ignore */ }
});

// ---------------------------------------------------------------------------
// DOM validation — checks the live DOM for HTML spec violations
// ---------------------------------------------------------------------------

// Elements whose content model forbids block/flow children.
const INLINE_ONLY = new Set(["p", "span", "a", "label", "em", "strong", "small", "b", "i", "u"]);
const BLOCK_TAGS = new Set([
    "div", "p", "section", "article", "aside", "nav", "header", "footer",
    "main", "figure", "figcaption", "blockquote", "pre", "ol", "ul", "li",
    "dl", "dt", "dd", "table", "form", "fieldset", "details", "summary", "h1",
    "h2", "h3", "h4", "h5", "h6", "hr",
]);
const INTERACTIVE = new Set(["a", "button", "details", "select", "textarea"]);

function validateDOM() {
    const errors = [];

    // 1. Duplicate IDs
    const ids = {};
    for (const el of document.querySelectorAll("[id]")) {
        const id = el.id;
        if (ids[id]) errors.push(`Duplicate id="${id}"`);
        else ids[id] = true;
    }

    // 2. Block elements inside inline-only parents
    for (const tag of INLINE_ONLY) {
        for (const parent of document.querySelectorAll(tag)) {
            for (const child of parent.children) {
                if (BLOCK_TAGS.has(child.tagName.toLowerCase())) {
                    errors.push(
                        `<${child.tagName.toLowerCase()}> inside <${tag}>` +
                        (parent.id ? ` (#${parent.id})` : "")
                    );
                }
            }
        }
    }

    // 3. Interactive elements nested inside <a> or <button>
    for (const tag of ["a", "button"]) {
        for (const parent of document.querySelectorAll(tag)) {
            for (const innerTag of INTERACTIVE) {
                for (const child of parent.querySelectorAll(innerTag)) {
                    if (child !== parent) {
                        errors.push(
                            `<${innerTag}> nested inside <${tag}>` +
                            (parent.id ? ` (#${parent.id})` : "")
                        );
                    }
                }
            }
        }
    }

    // 4. Images missing alt attribute
    for (const img of document.querySelectorAll("img:not([alt])")) {
        errors.push(`<img> missing alt attribute (src="${img.src.slice(-40)}")`);
    }

    // 5. Labels with for= pointing to non-existent IDs
    for (const label of document.querySelectorAll("label[for]")) {
        if (!document.getElementById(label.htmlFor)) {
            errors.push(`<label for="${label.htmlFor}"> targets non-existent id`);
        }
    }

    if (errors.length === 0) {
        console.log("validateDOM: no issues found");
    } else {
        console.warn(`validateDOM: ${errors.length} issue(s) found`);
        for (const e of errors) console.warn("  •", e);
    }
    return errors;
}
window.validateDOM = validateDOM;
