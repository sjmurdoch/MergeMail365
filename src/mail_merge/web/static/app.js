/* MergeMail365 — Wizard UI */

// In a <meta> tag, not an inline script: the page's Content Security Policy
// allows no inline script.
const CSRF_TOKEN = document.querySelector('meta[name="csrf-token"]').content;

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
        clearTestAndVerifyLogs();
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
    // Stored in state.signedIn so the reducer and selectors see it.
    get isSignedIn() { return state.signedIn; },
    set isSignedIn(v) { state.signedIn = v; },
    desktopMode: false,
    signInPoll: null,     // interval ID for polling during sign-in
    tokenExpiresAt: null,
};

// Convenience alias kept as a plain function for backward compat
function getRecipients() { return state.getRecipients(); }

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
// Placeholders ({{column name}}) are found, checked and substituted by
// TemplateCore (template-core.js), which follows the same grammar and the
// same test cases as template.py, so the preview shows what will be sent.
function $(id) { return document.getElementById(id); }
function hide(el) { if (typeof el === "string") el = $(el); el.classList.add("hidden"); }
function show(el) { if (typeof el === "string") el = $(el); el.classList.remove("hidden"); }
// Markup is built with html`...` (every ${value} escaped) and put on the
// page with setHtml(); nothing else in this file assigns innerHTML
// (tests/test_spec_coverage.py TestHtmlSinks). See safe-html.js.
const { html, joinHtml, setHtml } = SafeHtmlLib;
function clear(el) { if (typeof el === "string") el = $(el); el.replaceChildren(); }

// Requests the page waits for (WizardCore.startRequest): a response or job
// completion is applied only while its request is current.
function beginRequest(kind) {
    const { patch, id } = WizardCore.startRequest(state, kind);
    Object.assign(state, patch);
    return id;
}

function requestIsCurrent(id) {
    return WizardCore.isCurrent(state, id);
}

function finishRequest(id) {
    Object.assign(state, WizardCore.finishRequest(state, id));
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

    // Step 4
    $("btn-send-test").disabled = !C.sendTestEnabled(state);
    if (state.testRunning) $("btn-send-test").setAttribute("aria-busy", "true");
    else $("btn-send-test").removeAttribute("aria-busy");
    toggle("btn-retry-test", C.retryVisible(state));
    $("btn-retry-test").disabled = !C.sendTestEnabled(state);
    $("btn-next-4").disabled = !C.nextEnabled(state, 4);
    renderResult("test-result", state.testResult);

    // Step 5
    $("btn-next-5").disabled = !C.nextEnabled(state, 5);
    renderResult("verify-result", state.verifyResult);

    // The test email and the send go out from the signed-in account, so
    // steps 4 and 6 offer sign-in while the page shows signed out.
    const offered = C.signInOffered(state);
    toggle("signin-callout-4", offered && state.currentStep === 4);
    toggle("signin-callout-6", offered && state.currentStep === 6);
    // In browser mode, signing in leaves the page and comes back to step 1.
    for (const el of document.querySelectorAll(".signin-reload-note")) {
        toggle(el, !_auth.desktopMode);
    }

    // Step 1: sends an earlier server process didn't finish
    toggle("interrupted-send", C.interruptedShown(state));

    // Step 6
    const panel = C.sendPanel(state);
    toggle("send-confirm", panel === "confirm");
    toggle("send-progress", panel === "progress");
    toggle("send-log", state.sendStarted);
    toggle("send-result", panel === "done");
    toggle("send-nav", panel !== "done");
    toggle("send-done-nav", panel === "done");
    $("btn-back-6").disabled = !C.back6Enabled(state);
    $("btn-do-send").disabled = !C.doSendEnabled(state, sendConfirmed());
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
    $("spreadsheet-summary").textContent = `${data.file_name}: ${WizardCore.count(data.columns.length, "column")}, ${WizardCore.count(data.total_rows, "row")}.`;
    renderNumberFormatNote(data);
    if (data.total_rows > 99) {
        const badge = document.createElement("span");
        badge.className = "badge badge-warning";
        badge.textContent = "Large file — filters required";
        $("spreadsheet-summary").append(" ", badge);
    }
}

// Dates and percentages are sent as Excel shows them, but other number
// formats (currency symbols, thousands separators, fixed decimals) are not
// applied: say which columns that affects. The tables below already show
// exactly what will be sent.
function renderNumberFormatNote(data) {
    const el = $("number-format-note");
    const columns = Object.entries(data.unformatted_numbers || {});
    toggle(el, columns.length > 0);
    if (columns.length === 0) return;
    const examples = columns.map(([name, example]) => `${name} (for example ${example})`).join(", ");
    el.textContent = `Numbers in ${columns.length === 1 ? "this column" : "these columns"} are sent without their Excel `
        + `formatting, such as currency symbols, separators or fixed decimals: ${examples}. The table below shows `
        + "exactly what will be sent. To control it, format the column as Text in Excel.";
}

function populateSheetSelect(sheets) {
    const sel = $("sheet-select");
    setHtml(sel, sheets.map(s => html`<option value="${s}">${s}</option>`));
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
// Applies an event through WizardCore.reduce() and carries out the effects
// it returns. Navigation goes through here, so each move is one event
// (WizardCore.ACTIONS maps them to the spec/wizard.qnt actions).
async function dispatch(event) {
    const { state: next, effects } = WizardCore.reduce(state, event);
    // A navigation that reached its step is saved even if the step didn't
    // change (newMerge() resets the step before goToStep(1)).
    const arrived = next.currentStep !== state.currentStep
        || (event.to !== undefined && next.currentStep === event.to);
    Object.assign(state, next);
    if (arrived) saveState();
    updateStepUI(state.currentStep);
    render();
    for (const effect of effects) await runEffect(effect);
    // Effects can change inputs the selectors read (clearForm empties the
    // SEND confirmation).
    if (effects.length > 0) render();
}

async function runEffect(effect) {
    switch (effect.type) {
        case "alert":
            alert(effect.message);
            break;
        case "initCompose":
            initComposeStep();
            break;
        case "fetchPreview": {
            const ok = await loadPreview(
                () => requestIsCurrent(effect.id) && state.currentStep === 2,
            );
            await dispatch({ type: "previewResponse", id: effect.id, ok });
            break;
        }
        case "enterTest":
            checkAuthForStep4();
            break;
        case "startJob":
            await runJob(effect.mode, effect.id);
            break;
        case "saveState":
            saveState();
            break;
        case "checkAuth":
            checkAuthStatus();
            break;
        case "prepareSend":
            prepareSend();
            break;
        case "clearLogs":
            clearTestAndVerifyLogs();
            break;
        case "showAuth":
            showAuth(effect.status);
            break;
        case "showSpreadsheet":
            showRestoredSpreadsheet();
            break;
        case "startSendJob":
            await startSendJob(effect.id);
            break;
        case "postStop":
            await postStop(effect.jobId);
            break;
        case "streamSend":
            streamSend(effect.jobId);
            break;
        case "fetchResults":
            await fetchResults(effect.jobId);
            break;
        case "showResults":
            showResults(effect.data);
            break;
        case "showSendError":
            showSendError(effect.message);
            break;
        case "showInterrupted":
            showInterrupted();
            break;
        case "postDismissInterrupted":
            apiFetch("/api/interrupted/dismiss", { method: "POST" }).catch(() => {});
            break;
        case "reconnectSend":
            reconnectSend(effect.jobId);
            break;
        case "resetServer":
            // Clean up server-side temp files and session state
            apiFetch("/api/reset", { method: "POST" }).catch(() => {});
            break;
        case "clearForm":
            clearForm();
            break;
        default:
            throw new Error(`Unknown effect: ${effect.type}`);
    }
}

async function goToStep(n) {
    console.log("Navigating to step", n, "from", state.currentStep);
    // The compose form is checked here because it lives in the DOM.
    const composeOk = n === 3 && state.currentStep === 2 ? validateCompose() : true;
    await dispatch({ type: "goTo", to: n, composeOk });
}

function confirmGoBack(targetStep) {
    // Going back from test/verify/send steps discards their results.
    const accepted = !WizardCore.needsConfirmBack(state)
        || confirm("Going back will discard your test and verification results. You will need to complete these steps again. Continue?");
    return dispatch({ type: "back", to: targetStep, accepted });
}

function clearTestAndVerifyLogs() {
    clear("test-log");
    hide("test-log");
    clear("verify-log");
}

// ---------------------------------------------------------------------------
// Step 2: Compose — initialisation and validation
// ---------------------------------------------------------------------------
// A value the page saved in localStorage, or "" if there is none or
// storage is unavailable.
function savedSetting(key) {
    try { return localStorage.getItem(key) || ""; } catch (_e) { return ""; }
}

function initComposeStep() {
    if (!state.spreadsheetData) return;
    const sd = state.spreadsheetData;
    // Update compose data summary
    $("compose-data-summary").textContent =
        `${sd.file_name}: ${WizardCore.count(sd.columns.length, "column")}, ${WizardCore.count(sd.total_rows, "row")}.`;

    // Build the read-only preview table on the compose step
    buildComposePreviewTable(sd.columns, sd.rows, sd.total_rows);

    // Populate column dropdowns — preserve previous selections if they're
    // still valid (user went back and came forward without changing data),
    // or the ones saved before the app was last closed: on a fresh start
    // the dropdowns are empty until a spreadsheet is uploaded.
    const prevEmail = $("email-column").value || savedSetting("mm_email_col");
    const prevName = $("name-column").value || savedSetting("mm_name_col");
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
    if (state.sendMode === "bcc" && TemplateCore.hasPlaceholders(subject + body)) {
        alert("BCC blast mode does not support {{placeholders}} in the subject or body. All recipients receive the same message.");
        return false;
    }
    // A placeholder that names no column would otherwise only be refused
    // later, by the test email or the dry run.
    const bad = unresolvedPlaceholders();
    if (state.sendMode !== "bcc" && bad.length > 0) {
        alert(`No column named ${bad.map(p => `{{${p}}}`).join(", ")}. Fix the placeholder, or choose one from the list above the subject.`);
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
    dispatch({ type: "contentChanged" });
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
    const has = TemplateCore.hasPlaceholders(subject + body);
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

        // The spreadsheet, the passed flags and an active send (WizardCore
        // configLoaded); the effects fill the page.
        await dispatch({ type: "configLoaded", config: data });
    } catch (e) { console.error("Error loading config:", e); }
}

// The "showSpreadsheet" effect: fill step 1 from the restored spreadsheet,
// then restore the sheet and column choices saved in localStorage.
function showRestoredSpreadsheet() {
    const s = state.spreadsheetData;
    show("spreadsheet-info");
    renderSpreadsheetSummary(s);
    populateSheetSelect(s.sheets);
    if (s.active_sheet) $("sheet-select").value = s.active_sheet;
    buildPreviewTable(s.columns, s.rows, s.total_rows);
    showPlaceholderChips(s.columns);
    showFilterChips(s.columns);

    restoreSavedSheet(s);

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

// Choose the sheet that was chosen last time, if the workbook has one of
// that name and the server read another: after a reload, and after the
// spreadsheet is uploaded again once the app has been reopened.
function restoreSavedSheet(s) {
    const savedSheet = savedSetting("mm_sheet");
    if (savedSheet && s.sheets.includes(savedSheet) && savedSheet !== (s.active_sheet || s.sheets[0])) {
        $("sheet-select").value = savedSheet;
        // Trigger a change to re-fetch the sheet's data
        $("sheet-select").dispatchEvent(new Event("change"));
    }
}

// The "reconnectSend" effect: follow a send started before the reload.
function reconnectSend(jobId) {
    window.addEventListener("beforeunload", beforeUnloadWarn);
    streamSend(jobId);
}

// Check auth status
async function checkAuthStatus() {
    const id = beginRequest("auth");
    try {
        const resp = await apiFetch("/auth/status");
        const status = await resp.json();
        await dispatch({ type: "authStatus", id, status });
    } catch (_e) {
        finishRequest(id);
    }
}

// Shows a current /auth/status answer (the "showAuth" effect).
function showAuth(status) {
    const el = $("auth-display");
    if (status.authenticated) {
        setHtml(el, html`<span class="dot green"></span> Signed in as <span class="email">${status.email}</span>`);
        if ($("test-email-input") && !$("test-email-input").value) {
            $("test-email-input").value = status.email;
            // Step 4 shows its "Will send" line before this answer arrives.
            updateTestPreview();
        }
        _auth.tokenExpiresAt = status.token_expires_at ? new Date(status.token_expires_at) : null;
    } else {
        setHtml(el, html`<span class="dot gray"></span> Not signed in`);
        _auth.tokenExpiresAt = null;
    }
    updateSignInButton();
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

// The Test connection result describes the account that was signed in.
function hideAuthDiagnostics() {
    hide("auth-diagnostics");
    clear("auth-diag-content");
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
        hideAuthDiagnostics();
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
        let summary;
        if (data.error) {
            summary = html`<div class="callout callout-danger mt-0"><strong>Connection Error:</strong> ${data.error}</div>`;
        } else if (data.token_valid) {
            summary = html`<div class="callout callout-success mt-0"><strong>Success:</strong> Connection is healthy and token is valid.</div>`;
        } else if (data.authority_reachable) {
            summary = html`<div class="callout callout-warning mt-0"><strong>Partial Success:</strong> Authority is reachable, but you are not signed in or token has expired.</div>`;
        } else {
            summary = html`<div class="callout callout-danger mt-0"><strong>Failure:</strong> Microsoft login authority is not reachable. Check your internet connection.</div>`;
        }

        // The JSON holds the tenant ID, account names and error text.
        setHtml($("auth-diag-content"), html`${summary}<pre>${JSON.stringify(data, null, 2)}</pre>`);
    } catch (e) {
        setHtml($("auth-diag-content"), html`<div class="callout callout-danger mt-0"><strong>Error:</strong> ${e.message}</div>`);
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
        dispatch({ type: "spreadsheetLoaded", data });
        show("spreadsheet-info");
        renderSpreadsheetSummary(data);
        $("btn-next-1").disabled = false;
        populateSheetSelect(data.sheets);
        if (data.active_sheet) $("sheet-select").value = data.active_sheet;

        // Build preview table on step 1
        buildPreviewTable(data.columns, data.rows, data.total_rows);
        showFilterChips(data.columns);
        restoreSavedSheet(data);
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
        dispatch({ type: "spreadsheetLoaded", data });
        renderSpreadsheetSummary(data);
        buildPreviewTable(data.columns, data.rows, data.total_rows);
        showFilterChips(data.columns);
        try { localStorage.setItem("mm_sheet", sheet); } catch (_e) { /* ignore */ }
    } catch (e) {
        alert(`Error changing sheet: ${e.message}`);
    }
});

function populateSelect(sel, cols, required) {
    const first = required ? html`<option value="">-- select --</option>` : html`<option value="">-- none --</option>`;
    setHtml(sel, [first, ...cols.map(c => html`<option value="${c}">${c}</option>`)]);
}

function buildPreviewTable(columns, rows, totalRows) {
    const thead = document.querySelector("#preview-table thead");
    const tbody = document.querySelector("#preview-table tbody");
    setHtml(thead, html`<tr>${columns.map(c => html`<th title="${c}">${c}</th>`)}</tr>`);
    setHtml(tbody, rows.map(row => html`<tr>${columns.map(c => html`<td title="${row[c] || ""}">${row[c] || ""}</td>`)}</tr>`));
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
    setHtml(thead, html`<tr>${columns.map(c => html`<th title="${c}">${c}</th>`)}</tr>`);
    setHtml(tbody, rows.map(row => html`<tr>${columns.map(c => html`<td title="${row[c] || ""}">${row[c] || ""}</td>`)}</tr>`));
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
    clear(container);
    // A column whose name has a brace can't be named by a placeholder.
    const unusable = TemplateCore.unusableColumns(columns);
    $("chips-unusable").textContent = unusable.length > 0
        ? `Not available as placeholders, because the name contains { or }: ${unusable.join(", ")}`
        : "";
    for (const col of columns.filter(c => !unusable.includes(c))) {
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
    clear(container);
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
function trixReady(el) {
    trixEditorEl = el;
    state.trixEditor = el.editor;
}
document.addEventListener('trix-initialize', (e) => trixReady(e.target));
// trix.js runs before this script and fires trix-initialize on the next
// animation frame, which can come before this listener exists.
const initialTrix = document.querySelector("trix-editor");
if (initialTrix?.editor) trixReady(initialTrix);

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
    div.innerHTML = paste.html;  // inert document: nothing loads or runs
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
    dispatch({ type: "contentChanged" });
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

// The placeholders in the subject and body that name no column. The body
// of an HTML email is read as HTML (the editor writes {{R&amp;D budget}}).
function unresolvedPlaceholders() {
    if (!state.spreadsheetData) return [];
    const columns = state.spreadsheetData.columns;
    return [...new Set([
        ...TemplateCore.unresolved($("subject-input").value, columns),
        ...TemplateCore.unresolved($("body-input").value, columns, $("html-toggle").checked),
    ])].sort();
}

function validatePlaceholders() {
    if (!state.spreadsheetData) return;
    const messages = [];
    const available = state.spreadsheetData.columns.join(", ");
    for (const p of unresolvedPlaceholders()) {
        messages.push(html`No column named <strong>{{${p}}}</strong>. Available: ${available}`);
    }
    // An unfinished placeholder, such as {{name}, would be sent as typed.
    for (const [label, id] of [["subject", "subject-input"], ["body", "body-input"]]) {
        if (TemplateCore.hasStrayBraces($(id).value)) {
            messages.push(html`The ${label} has a <strong>{{</strong> or <strong>}}</strong> that is not part of a placeholder. It will be sent as written: check for a missing brace.`);
        }
    }
    const el = $("placeholder-errors");
    if (messages.length > 0) {
        setHtml(el, joinHtml(messages, html`<br>`));
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
        warnings.push(html`<strong>No HTML tags detected.</strong> The body appears to be plain text
            but will be sent as HTML. Line breaks will not be visible to recipients.
            Use <code>&lt;br&gt;</code> for line breaks or <code>&lt;p&gt;</code> for paragraphs.`);
    } else if (/\n/.test(body) && !BLOCK_OR_BR_RE.test(body)) {
        warnings.push(html`<strong>Line breaks may not render.</strong> The body contains newlines but no
            <code>&lt;br&gt;</code>, <code>&lt;p&gt;</code>, or <code>&lt;div&gt;</code> tags.
            Newlines are ignored in HTML — use <code>&lt;br&gt;</code> for line breaks.`);
    }

    if (STRIPPED_TAGS_RE.test(body)) {
        const found = [];
        for (const tag of ["script", "iframe", "form", "embed", "object"]) {
            if (new RegExp(`<${tag}\\b`, "i").test(body)) found.push(`<${tag}>`);
        }
        warnings.push(html`<strong>Unsupported tags:</strong> ${found.join(", ")} will be stripped by email clients.`);
    }

    if (EXT_STYLESHEET_RE.test(body)) {
        warnings.push(html`<strong>External stylesheets ignored:</strong> <code>&lt;link rel="stylesheet"&gt;</code>
            is not supported in email. Use inline <code>style</code> attributes instead.`);
    }

    if (STYLE_BLOCK_RE.test(body)) {
        warnings.push(html`<strong>Inline &lt;style&gt; blocks may be stripped</strong> by email clients
            (Gmail, Outlook.com). Use inline <code>style</code> attributes on each
            element for reliable rendering.`);
    }

    if (FULL_HTML_DOC_RE.test(body)) {
        warnings.push(html`<strong>Full HTML document tags detected</strong> (&lt;!DOCTYPE&gt;, &lt;html&gt;,
            &lt;head&gt;, &lt;body&gt;). These will be stripped before sending — the app
            always adds its own email compatibility wrappers. Just provide the body content.`);
    }

    const sizeKb = new Blob([body]).size / 1024 + EMAIL_WRAPPER_KB;
    if (sizeKb > GMAIL_CLIP_KB) {
        warnings.push(html`<strong>Large body (~${Math.round(sizeKb)} KB with email wrapper):</strong> Gmail clips
            emails over ~102 KB. Recipients may see a truncated message.`);
    }

    if (warnings.length > 0) {
        setHtml(el, joinHtml(warnings, html`<hr>`));
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
        // Checked by the server with the recipients, so a mistyped address
        // is reported now.
        form.set("cc", $("cc-input").value);
        form.set("bcc", $("bcc-input").value);
        form.set("reply_to", $("reply-to-input").value);
        if (state.sendMode === "bcc") {
            form.set("bcc_blast", "true");
            form.set("bcc_blast_to", $("bcc-blast-to").value);
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
        $("verify-count").textContent = WizardCore.count(rows.length, "email");
        $("send-count").textContent = WizardCore.count(rows.length, "real email");
        return true;

    } catch (e) {
        if (isCurrent()) alert(`Error loading preview: ${e.message}`);
        return false;
    } finally {
        $("btn-next-2").ariaBusy = "false";
        $("btn-next-2").disabled = false;
    }
}

// Show an HTML email in the preview frame. Each preview gets a new frame,
// a copy of the empty one in index.html (so still sandbox=""): on Windows,
// WebView2 left the reused frame blank after New merge, for every recipient
// (phase H), which Chromium doesn't reproduce.
function showPreviewHtml(doc) {
    const old = $("preview-body-html");
    const frame = old.cloneNode(false);
    frame.removeAttribute("srcdoc");
    frame.srcdoc = doc;  // sandbox="" (no script, no forms)
    old.replaceWith(frame);
}

function renderPreviewRecipient() {
    const recipients = getRecipients();
    if (!recipients || recipients.length === 0) return;
    const row = recipients[state.previewIndex];
    const subject = $("subject-input").value;
    const body = $("body-input").value;

    // Client-side template rendering for preview
    // In BCC mode all recipients get the same message — no substitution
    // In an HTML body the values are escaped, as they are when sent.
    const isHtml = $("html-toggle").checked;
    const rendered_subject = state.sendMode === "bcc" ? subject : renderTemplate(subject, row);
    const rendered_body = state.sendMode === "bcc" ? body : renderTemplate(body, row, isHtml);

    $("preview-subject").textContent = rendered_subject;
    if (isHtml) {
        hide("preview-body");
        show("preview-body-html");
        const w = state.emailWrapper;
        showPreviewHtml(w ? w.head + stripHtmlDocTags(rendered_body) + w.tail : rendered_body);
    } else {
        show("preview-body");
        hide("preview-body-html");
        $("preview-body").textContent = rendered_body;
    }

    // Headers
    if (state.sendMode === "bcc") {
        $("preview-to").textContent = $("bcc-blast-to").value || "(none)";
        $("preview-cc").textContent = "(none in BCC mode)";
        $("preview-bcc").textContent = `[${WizardCore.count(recipients.length, "recipient")}]`;
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

function renderTemplate(template, data, isHtml = false) {
    return TemplateCore.render(template, data, isHtml);
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
    setHtml(thead, html`<tr>${cols.map(c => html`<th title="${c}">${c}</th>`)}</tr>`);
    setHtml(tbody, recipients.map(row => html`<tr>${cols.map(c => html`<td title="${row[c] || ""}">${row[c] || ""}</td>`)}</tr>`));
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
        html`<li><strong>${e.address || "(empty)"}</strong>: ${e.reason}</li>`);
    setHtml(el, html`<strong>${invalidEmails.length} invalid email${invalidEmails.length > 1 ? " addresses" : " address"} skipped</strong> (${validCount} of ${totalBefore} recipients remain)<ul class="skipped-list">${skippedList}</ul>`);
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
    setHtml($("test-preview-info"), html`<strong>To:</strong> ${testAddr}<br><strong>Subject:</strong> ${rendered}<br><small>Using data from first recipient: ${row[$("email-column").value] || "?"}</small>`);
}

$("test-email-input").addEventListener("input", updateTestPreview);

function sendTestEmail() {
    return dispatch({ type: "sendTestEmail", addressOk: Boolean($("test-email-input").value.trim()) });
}

// The "startJob" effect: start a test email or dry run for request `id` and
// report its end as a jobCompleted event. Returns once the job has started;
// the stream runs on.
async function runJob(mode, id) {
    const isCurrent = () => requestIsCurrent(id);
    const logPanel = mode === "test_email" ? "test-log" : "verify-log";
    // New merge hides both panels.
    show(logPanel);
    if (mode !== "test_email") {
        const recipients = getRecipients();
        $("verify-count").textContent = WizardCore.count(recipients ? recipients.length : "?", "email");
    }
    clear(logPanel);
    saveState();

    const form = buildJobFormData(mode);
    if (mode === "test_email") form.set("test_email", $("test-email-input").value.trim());
    const completed = (ok, message) => dispatch({ type: "jobCompleted", id, ok, message });

    try {
        const resp = await apiFetch("/api/start-job", { method: "POST", body: form, headers: { "X-CSRF-Token": CSRF_TOKEN } });
        const data = await resp.json();
        if (!isCurrent()) return;
        if (!resp.ok) {
            await completed(false, data.error || (mode === "test_email" ? "Failed to start job" : "Verification failed"));
            return;
        }
        await dispatch({ type: "jobStarted", id, jobId: data.job_id });
        streamEvents(data.job_id, logPanel, (result) => {
            // result.ok, not the status: a job whose email was rejected
            // still runs to the end (spec/wizard.qnt, testPassHonest).
            const ok = WizardCore.jobSucceeded(result);
            if (mode === "test_email") {
                completed(ok, ok ? "Test email sent successfully!" : WizardCore.testEmailFailure(result));
            } else {
                completed(ok, ok ? dryRunSummary() : jobFailureText(result, "Verification failed"));
            }
        }, null, isCurrent);
    } catch (e) {
        if (isCurrent()) await completed(false, `Error: ${e.message}`);
    }
}

// Why a job that didn't succeed failed: its error, or the first rejected
// email's, or `fallback`.
function jobFailureText(result, fallback) {
    if (result.error) return result.error;
    const failed = (result.results || []).find(r => !r.success);
    if (failed) return `${failed.status_code || ""} ${failed.error || ""}`.trim() || fallback;
    return fallback;
}

// What a passed dry run reports: the count, the time it will take, and a
// warning if the token may expire before the send ends.
function dryRunSummary() {
    const recs = getRecipients();
    const n = recs ? recs.length : "?";
    const estSec = recs ? recs.length * 2 : "?";
    let msg = `${WizardCore.count(n, "email")} ready to send. Estimated time: ~${WizardCore.count(estSec, "second")} (2-second delay between sends).`;
    if (_auth.tokenExpiresAt && recs) {
        const estEndMs = Date.now() + recs.length * 2000;
        if (estEndMs > _auth.tokenExpiresAt.getTime()) {
            msg += "\n\u26a0\ufe0f Warning: Your authentication token may expire before sending completes. Consider signing in again before proceeding.";
        }
    }
    return msg;
}

// ---------------------------------------------------------------------------
// Step 6: Send
// ---------------------------------------------------------------------------
function prepareSend() {
    state.sendStarted = false;
    state.sendResults = null;
    const recipients = getRecipients();
    const n = recipients ? recipients.length : "?";
    $("send-count").textContent = WizardCore.count(n, "real email");

    // Build details
    const details = [];
    const authEmail = $("auth-display").querySelector(".email");
    if (authEmail) details.push(html`<strong>From:</strong> ${authEmail.textContent}<br>`);
    details.push(html`<strong>Recipients:</strong> ${n}<br>`);
    if ($("cc-input").value) details.push(html`<strong>CC:</strong> ${$("cc-input").value}<br>`);
    if ($("bcc-input").value) details.push(html`<strong>BCC:</strong> ${$("bcc-input").value}<br>`);
    const attInput = $("attachment-input");
    if (attInput.files.length > 0) {
        const attList = Array.from(attInput.files).map(f => `${f.name} (${WizardCore.formatSize(f.size)})`);
        details.push(html`<strong>Attachments:</strong> ${attList.join(", ")}<br>`);
    }
    setHtml($("send-confirm-details"), details);

    state.sendOutcome = null;
    $("send-confirm-input").value = "";
    render();
    checkAuthStatus();
}

$("send-confirm-input").addEventListener("input", render);

function startSend() {
    return dispatch({ type: "startSend" });
}

// The "startSendJob" effect: start the send for request `id`.
async function startSendJob(id) {
    clear("send-log");
    $("send-progress-text").textContent = "Sending...";
    $("send-progress-bar").value = 0;
    window.addEventListener("beforeunload", beforeUnloadWarn);
    const form = buildJobFormData("send");
    try {
        const resp = await apiFetch("/api/start-job", { method: "POST", body: form, headers: { "X-CSRF-Token": CSRF_TOKEN } });
        const data = await resp.json();
        if (!resp.ok) {
            await dispatch({ type: "startSendResponse", id, error: data.error || "Failed to start send" });
            return;
        }
        await dispatch({ type: "startSendResponse", id, jobId: data.job_id });
    } catch (e) {
        await dispatch({ type: "startSendResponse", id, error: `Error: ${e.message}` });
    }
}

// The "streamSend" effect: follow the send's log until it ends.
function streamSend(jobId) {
    streamEvents(jobId, "send-log", (result) => dispatch({ type: "sendCompleted", jobId, result }), showSendProgress);
}

function showSendProgress(current, total) {
    $("send-progress-bar").max = total;
    $("send-progress-bar").value = current;
    $("send-progress-text").textContent = `Sending ${current} of ${total}...`;
}

function beforeUnloadWarn(e) {
    e.preventDefault();
    e.returnValue = "";
}

function stopSend() {
    return dispatch({ type: "stopSend" });
}

// The "postStop" effect.
async function postStop(jobId) {
    await apiFetch(`/api/job/${jobId}/stop`, {
        method: "POST",
        headers: { "X-CSRF-Token": CSRF_TOKEN },
    });
}

// The "fetchResults" effect.
async function fetchResults(jobId) {
    try {
        const resp = await apiFetch(`/api/job/${jobId}/status`);
        const data = await resp.json();
        await dispatch({ type: "sendResults", data });
    } catch (e) {
        await dispatch({ type: "sendError", message: `Error fetching results: ${e.message}` });
    }
}

// The "showResults" effect: list the send's results. A send that was
// stopped or failed part-way still lists the emails that went out
// (spec/wizard.qnt, failedSendReported).
function showResults(data) {
    window.removeEventListener("beforeunload", beforeUnloadWarn);
    const summary = data.summary || {};
    const parts = [html`<h4>Results</h4>`];
    if (data.status === "stopped") {
        parts.push(html`<div class="callout callout-warning">Sending was stopped. Recipients not listed below were not sent an email.</div>`);
    } else if (data.status === "failed") {
        parts.push(html`<div class="callout callout-danger">Sending failed: ${data.error || "unknown error"}. Recipients not listed below were not sent an email.</div>`);
    }
    const unknownCount = summary.unknown
        ? html` | <span class="unknown"><strong>Unknown:</strong> ${summary.unknown}</span>`
        : "";
    parts.push(html`<p><strong>Total:</strong> ${summary.total || 0} | <span class="success"><strong>Sent:</strong> ${summary.sent || 0}</span> | <span class="failure"><strong>Failed:</strong> ${summary.failed || 0}</span>${unknownCount}</p>`);
    if (summary.unknown) {
        parts.push(html`<div class="callout callout-warning">Microsoft did not answer for ${summary.unknown === 1 ? "one email" : `${summary.unknown} emails`}, which may have been delivered. Check Sent Items before sending ${summary.unknown === 1 ? "it" : "them"} again.</div>`);
    }

    if (state.sendResults.length > 0) {
        const rows = state.sendResults.map(r => html`<tr class="${resultClass(r)}"><td>${r.email}</td><td>${resultLabel(r)} ${r.status_code ? `(${r.status_code})` : ""}</td><td>${r.error || ""}</td></tr>`);
        parts.push(html`<table class="striped results-table"><thead><tr><th>Email</th><th>Status</th><th>Error</th></tr></thead><tbody>${rows}</tbody></table>`);
    }

    setHtml($("send-result"), parts);
}

// One send result, as the results tables show it. An unknown outcome (no
// answer from Microsoft) may have been delivered, so it is not "Failed".
function resultClass(r) {
    if (r.success) return "success";
    return r.unknown ? "unknown" : "failure";
}

function resultLabel(r) {
    if (r.success) return "Sent";
    return r.unknown ? "Unknown: may have been delivered" : "Failed";
}

// The "showSendError" effect.
function showSendError(message) {
    window.removeEventListener("beforeunload", beforeUnloadWarn);
    setHtml($("send-result"), html`<div class="callout callout-danger">${message}</div>`);
}

function sanitizeCsvValue(val) {
    if (!val) return val;
    const s = String(val);
    if (/^[=+@\-\t\r]/.test(s)) return `\t${s}`;
    return s;
}

function downloadCsv() {
    if (!state.sendResults || state.sendResults.length === 0) return;
    saveCsv(state.sendResults, "mergemail365-results.csv");
}

// The "showInterrupted" effect: what each unfinished send had sent.
// Addresses come from the spreadsheet, so they are escaped.
function showInterrupted() {
    const parts = [];
    for (const send of state.interrupted) {
        const sent = send.results.filter(r => r.success).length;
        parts.push(html`<p><strong>The app closed while sending</strong> (started ${send.started || "at an unknown time"}). ${sent} email${sent === 1 ? " was" : "s were"} recorded as sent. Recipients not listed were not sent an email, except perhaps the one being sent when the app stopped.</p>`);
        if (send.results.length > 0) {
            const rows = send.results.map(r => html`<tr class="${resultClass(r)}"><td>${r.email}</td><td>${r.success || r.unknown ? resultLabel(r) : `Failed: ${r.error || ""}`}</td></tr>`);
            parts.push(html`<table class="striped results-table"><thead><tr><th>Email</th><th>Status</th></tr></thead><tbody>${rows}</tbody></table>`);
        }
    }
    setHtml($("interrupted-send-details"), parts);
}

function downloadInterruptedCsv() {
    const results = state.interrupted.flatMap(s => s.results);
    if (results.length > 0) saveCsv(results, "mergemail365-interrupted.csv");
}

function dismissInterrupted() {
    return dispatch({ type: "dismissInterrupted" });
}

function saveCsv(results, fileName) {
    let csv = "email,success,status_code,error,unknown\n";
    for (const r of results) {
        csv += `"${sanitizeCsvValue(r.email)}",${r.success},${r.status_code || ""},"${sanitizeCsvValue((r.error || "").replace(/"/g, '""'))}",${Boolean(r.unknown)}\n`;
    }
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = fileName;
    a.click();
    // The desktop app's web view starts the download after this returns
    // (once pywebview has decided to treat the click as a download), so
    // revoking at once could leave nothing to save.
    setTimeout(() => URL.revokeObjectURL(url), 60000);
}

function newMerge() {
    return dispatch({ type: "newMerge" });
}

// Which collapsible panels are open when the page loads.
const DETAILS_AT_LOAD = [...document.querySelectorAll("details")].map((el) => [el, el.open]);

// The "clearForm" effect of New merge: empty every field the previous merge
// filled in, so that the page shows what a newly loaded one does
// (TestSecondPass in tests/test_web_e2e_workflow.py compares the two).
function clearForm() {
    // Panels the user opened, and the Test connection result
    for (const [el, open] of DETAILS_AT_LOAD) el.open = open;
    hideAuthDiagnostics();
    hideAuthMessage();

    // Clear Step 1 — spreadsheet
    $("spreadsheet-file").value = "";
    hide("spreadsheet-info");
    $("btn-next-1").disabled = false;

    // Clear Step 2 — compose fields
    $("subject-input").value = "";
    $("body-input").value = "";
    setHtml($("email-column"), html`<option value="">-- select --</option>`);
    setHtml($("name-column"), html`<option value="">-- none --</option>`);
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
    clear(document.querySelector("#recipients-table thead"));
    clear(document.querySelector("#recipients-table tbody"));

    // Clear Step 4 (Test)
    $("test-email-input").value = "";
    clear("test-log");
    hide("test-log");
    clear("test-result");

    // Clear Step 5 (Verify)
    clear("verify-log");
    hide("verify-log");
    clear("verify-result");

    // Clear Step 6 (Send)
    $("send-confirm-input").value = "";
    clear("send-log");
    clear("send-result");
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
// Buttons. The template names what each does in a data-action attribute,
// written as a call: data-action="goToStep(2)". No inline onclick handlers:
// the page's Content Security Policy forbids inline script, so that injected
// markup can't run any either. Only the functions listed here can be called,
// with at most one number or quoted-string argument.
// ---------------------------------------------------------------------------
const CLICK_ACTIONS = {
    goToStep, setSendMode, confirmGoBack, changePreviewRecipient, sendTestEmail,
    startSend, stopSend, downloadCsv, newMerge, dismissInterrupted, downloadInterruptedCsv,
    reloadPage: () => window.location.reload(),
};

function runDataAction(text) {
    const m = /^(\w+)\((?:'([^']*)'|(-?\d+))?\)$/.exec(text);
    const action = m && Object.hasOwn(CLICK_ACTIONS, m[1]) ? CLICK_ACTIONS[m[1]] : null;
    if (!action) throw new Error(`Unknown data-action: ${text}`);
    if (m[2] !== undefined) return action(m[2]);
    if (m[3] !== undefined) return action(Number(m[3]));
    return action();
}

document.addEventListener("click", (e) => {
    const el = e.target.closest("[data-action]");
    if (el && !el.disabled) runDataAction(el.dataset.action);
});

// Also on window, for the browser tests and the console.
window.goToStep = goToStep;
window.setSendMode = setSendMode;
window.confirmGoBack = confirmGoBack;
window.changePreviewRecipient = changePreviewRecipient;
window.sendTestEmail = sendTestEmail;
window.startSend = startSend;
window.stopSend = stopSend;
window.downloadCsv = downloadCsv;
window.newMerge = newMerge;
window.dismissInterrupted = dismissInterrupted;
window.downloadInterruptedCsv = downloadInterruptedCsv;

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
            // Only once the dropdowns list a spreadsheet's columns: before
            // an upload they are empty, and saving them would wipe the
            // columns chosen before the app was last closed.
            if ($("email-column").options.length > 1) {
                localStorage.setItem("mm_email_col", $("email-column").value);
                localStorage.setItem("mm_name_col", $("name-column").value);
            }
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
