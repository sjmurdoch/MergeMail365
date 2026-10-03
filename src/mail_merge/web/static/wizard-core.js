/* MergeMail365 — wizard core: state and selectors, no DOM and no fetch.
 *
 * The page loads this as a classic script (window.WizardCore) before
 * app.js; Node tests load it with require(). Selector names follow the pure
 * defs in spec/wizard.qnt (sendTestEnabled, doSendEnabled, signInOffered),
 * so the code and the model can be compared definition by definition.
 * app.js's render() reads only these selectors to set button and panel state.
 */
((root) => {
    /** The wizard's workflow state for a fresh page. */
    function initialState() {
        return {
            // Wizard navigation
            currentStep: 1,

            // Spreadsheet data: { columns, rows, sheets, file_name, total_rows }
            spreadsheetData: null,

            // Preview navigation index
            previewIndex: 0,

            // "individual" | "bcc"
            sendMode: "individual",

            // Counts changes to what would be sent (spreadsheet, sheet,
            // compose fields, options): the model's `version`.
            contentVersion: 0,
            // The content version the filtered recipient list (step 3) was
            // fetched for; null before the first preview.
            recipientsVersion: null,

            // Step 4: a test email is being sent; the last one failed;
            // the result shown ({ success, message } or null).
            testPassed: false,
            testRunning: false,
            testFailed: false,
            testResult: null,

            // Step 5: the dry-run result shown ({ success, message } or null).
            verifyPassed: false,
            verifyResult: null,

            // Step 6: the send was started; how it ended
            // (null while confirming or sending, "results" or "error").
            sendStarted: false,
            sendOutcome: null,

            // What the page last learnt from /auth/status (the model's
            // authShown): the token cache may have changed since.
            signedIn: false,

            // Background job tracking
            currentJobId: null,
            sendResults: null,

            // What the page is waiting for, by request id: { kind,
            // contentVersion } plus, for a send, stopQueued (Stop pressed
            // before the start-job response named the job). A response or job
            // completion whose request is no longer here is stale and is
            // dropped: a new request of the same kind, going back, an edit
            // or New merge removes the old one (spec/wizard.qnt: stale
            // completions, noStepJump, previewHonest, stopHonoured).
            requests: {},
            nextRequestId: 1,
        };
    }

    /** Fields to change when the test and dry-run results stop applying.
     *  Test emails and dry runs still running become stale. */
    function resetTestAndVerify(s) {
        return {
            testPassed: false,
            verifyPassed: false,
            requests: dropRequests(s, ["test", "verify"]).requests,
            // Let the user start a fresh test even if an old one is running.
            testRunning: false,
            testFailed: false,
            testResult: null,
            verifyResult: null,
        };
    }

    /** The state after "New merge". Counters keep counting, so nothing from
     *  the previous merge can match the new one; sign-in is unaffected. */
    function newMergeState(s) {
        return Object.assign(initialState(), {
            contentVersion: s.contentVersion + 1,
            nextRequestId: s.nextRequestId,
            signedIn: s.signedIn,
        });
    }

    // --- Requests. Each returns the fields to change. ---

    /** Start waiting for a request of `kind` ("test", "verify", "preview" or
     *  "send"). A new test, dry run or preview replaces the previous one of
     *  its kind, which becomes stale. Returns { patch, id }. */
    function startRequest(s, kind) {
        const id = s.nextRequestId;
        const requests = {};
        for (const [key, r] of Object.entries(s.requests)) {
            if (r.kind !== kind || kind === "send") requests[key] = r;
        }
        requests[id] = { kind, contentVersion: s.contentVersion };
        return { patch: { requests, nextRequestId: id + 1 }, id };
    }

    /** Whether a response or completion for request `id` still applies. */
    function isCurrent(s, id) {
        return Object.hasOwn(s.requests, id);
    }

    function updateRequest(s, id, fields) {
        if (!isCurrent(s, id)) return {};
        return { requests: Object.assign({}, s.requests, { [id]: Object.assign({}, s.requests[id], fields) }) };
    }

    function finishRequest(s, id) {
        const requests = Object.assign({}, s.requests);
        delete requests[id];
        return { requests };
    }

    /** Make every request of these kinds stale. */
    function dropRequests(s, kinds) {
        const requests = {};
        for (const [key, r] of Object.entries(s.requests)) {
            if (!kinds.includes(r.kind)) requests[key] = r;
        }
        return { requests };
    }

    /** The id of a pending request of `kind`, or null. */
    function pendingRequest(s, kind) {
        for (const [key, r] of Object.entries(s.requests)) {
            if (r.kind === kind) return Number(key);
        }
        return null;
    }

    // --- Events. reduce(state, event) returns { state, effects }: the new
    // state (a new object) and what the shell (app.js) must do, as data.
    // Event types and the spec/wizard.qnt actions they implement are listed
    // in ACTIONS below. ---

    /** Going back from this step asks for confirmation first: it discards a
     *  passed test email or dry run. */
    function needsConfirmBack(s) {
        return s.currentStep >= 4 && (s.testPassed || s.verifyPassed);
    }

    /** goToStep(to). Moving forward is guarded; moving back always works.
     *  `composeOk` is whether the compose fields are valid (checked by the
     *  shell, which reads the form). */
    function goTo(s0, event) {
        const to = event.to;
        // Any navigation makes a pending recipient preview stale.
        const s = Object.assign({}, s0, dropRequests(s0, ["preview"]));
        const stay = (effects = []) => ({ state: s, effects });
        const effects = [];
        if (to > s.currentStep) {
            if (to === 2 && s.currentStep === 1) {
                if (!s.spreadsheetData) {
                    return stay([{ type: "alert", message: "Please upload a spreadsheet." }]);
                }
                effects.push({ type: "initCompose" });
            }
            if (to === 3 && s.currentStep === 2) {
                if (!event.composeOk) return stay();
                // Wait for the recipient list: previewResponse moves on.
                const { patch, id } = startRequest(s, "preview");
                return { state: Object.assign(s, patch), effects: [{ type: "fetchPreview", id }] };
            }
            if (to === 4) effects.push({ type: "enterTest" });
            if (to === 5) {
                if (!s.testPassed) return stay();
                effects.push({ type: "startVerify" });
            }
            if (to === 6) {
                if (!s.verifyPassed) return stay();
                effects.push({ type: "prepareSend" });
            }
        }
        return { state: Object.assign(s, { currentStep: to }), effects };
    }

    /** confirmGoBack(to). `accepted` is the answer to the confirmation, if
     *  needsConfirmBack() asked for one. */
    function back(s0, event) {
        const s = Object.assign({}, s0);
        const effects = [];
        if (needsConfirmBack(s)) {
            if (!event.accepted) return { state: s, effects };
            Object.assign(s, resetTestAndVerify(s));
            effects.push({ type: "clearLogs" });
        }
        // Back from the preview to compose: the content may change.
        if (s.currentStep === 3 && event.to === 2) {
            Object.assign(s, resetTestAndVerify(s));
            effects.push({ type: "clearLogs" });
        }
        const nav = goTo(s, { to: event.to });
        return { state: nav.state, effects: effects.concat(nav.effects) };
    }

    /** The recipient list for preview request `id` arrived (`ok`) or failed.
     *  Applied only if the request is current and the page is still on step 2. */
    function previewResponse(s0, event) {
        const request = s0.requests[event.id];
        const current = isCurrent(s0, event.id) && s0.currentStep === 2;
        const s = Object.assign({}, s0, finishRequest(s0, event.id));
        if (!current || !event.ok) return { state: s, effects: [] };
        return {
            state: Object.assign(s, { currentStep: 3, recipientsVersion: request.contentVersion }),
            effects: [],
        };
    }

    /** An /auth/status answer for request `id`. A newer check supersedes an
     *  older one, so answers arriving out of order can't leave a stale
     *  display (spec/requirements.md, R16). `status` is the response body. */
    function authStatus(s0, event) {
        if (!isCurrent(s0, event.id)) return { state: Object.assign({}, s0), effects: [] };
        const s = Object.assign({}, s0, finishRequest(s0, event.id), {
            signedIn: Boolean(event.status.authenticated),
        });
        return { state: s, effects: [{ type: "showAuth", status: event.status }] };
    }

    /** /api/config answered on page load (the model's reload). Test and
     *  dry-run passes never survive a reload; a send still running, or
     *  finished but not yet shown, takes the page straight to step 6. */
    function configLoaded(s0, event) {
        const config = event.config;
        const s = Object.assign({}, s0, { testPassed: false, verifyPassed: false });
        const effects = [];
        if (config.spreadsheet) {
            s.spreadsheetData = config.spreadsheet;
            effects.push({ type: "showSpreadsheet" });
        }
        if (config.active_job_id) {
            Object.assign(s, {
                currentJobId: config.active_job_id,
                sendStarted: true,
                sendOutcome: null,
                currentStep: 6,
            });
            effects.push({ type: "reconnectSend", jobId: config.active_job_id });
        }
        return { state: s, effects };
    }

    /** "New merge": everything back to step 1, the server's session data
     *  and temp files cleared, and every form field emptied. */
    function newMerge(s0) {
        return {
            state: Object.assign({}, s0, newMergeState(s0)),
            effects: [{ type: "resetServer" }, { type: "clearForm" }],
        };
    }

    const REDUCERS = { goTo, back, previewResponse, authStatus, configLoaded, newMerge };

    function reduce(s, event) {
        const reducer = REDUCERS[event.type];
        if (!reducer) throw new Error(`Unknown event: ${event.type}`);
        return reducer(s, event);
    }

    /** spec/wizard.qnt actions and the events that implement them. */
    const ACTIONS = {
        next1: { type: "goTo", to: 2 },
        back2: { type: "goTo", to: 1 },
        next2: { type: "goTo", to: 3 },
        previewResponse: { type: "previewResponse" },
        back3: { type: "back", to: 2 },
        next3: { type: "goTo", to: 4 },
        back4: { type: "back", to: 3 },
        next4: { type: "goTo", to: 5 },
        back5: { type: "back", to: 4 },
        next5: { type: "goTo", to: 6 },
        back6: { type: "back", to: 4 },
        newMerge: { type: "newMerge" },
        reload: { type: "configLoaded" },
    };

    // --- Selectors. s.signedIn is what the page last fetched from
    // /auth/status (the model's authShown). ---

    /** "Send test email" can be clicked (model: sendTestEnabled). */
    function sendTestEnabled(s) {
        return s.signedIn && !s.testRunning;
    }

    /** "Retry" is shown after a failed test email. */
    function retryVisible(s) {
        return s.testFailed && !s.testRunning;
    }

    /** Next on step 4 or 5 is enabled exactly when it would advance
     *  (model: buttonsMatchFlags holds by construction). */
    function nextEnabled(s, step) {
        if (step === 4) return s.testPassed;
        if (step === 5) return s.verifyPassed;
        return true;
    }

    /** The sign-in callout on steps 4 and 6 (model: signInOffered, beyond step 1). */
    function signInOffered(s) {
        return !s.signedIn && (s.currentStep === 4 || (s.currentStep === 6 && !s.sendStarted));
    }

    /** "Send emails" can be clicked; `confirmed` is whether SEND was typed
     *  (model: doSendEnabled). */
    function doSendEnabled(s, confirmed) {
        return s.signedIn && confirmed && !s.sendStarted;
    }

    /** Back on step 6 works until the send starts (model: back6Usable). */
    function back6Enabled(s) {
        return !s.sendStarted;
    }

    /** Which part of step 6 is shown: "confirm", "progress" or "done". */
    function sendPanel(s) {
        if (!s.sendStarted) return "confirm";
        return s.sendOutcome === null ? "progress" : "done";
    }

    const WizardCore = {
        initialState,
        resetTestAndVerify,
        newMergeState,
        reduce,
        needsConfirmBack,
        EVENTS: Object.keys(REDUCERS),
        ACTIONS,
        startRequest,
        isCurrent,
        updateRequest,
        finishRequest,
        dropRequests,
        pendingRequest,
        sendTestEnabled,
        retryVisible,
        nextEnabled,
        signInOffered,
        doSendEnabled,
        back6Enabled,
        sendPanel,
    };

    if (typeof module === "object" && module.exports) {
        module.exports = WizardCore;
    } else {
        root.WizardCore = WizardCore;
    }
})(typeof globalThis !== "undefined" ? globalThis : this);
