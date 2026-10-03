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

            // Background job tracking
            currentJobId: null,
            // Generation counters for test and dry-run jobs. Starting a job or
            // resetting results bumps the counter; a job whose stamp no longer
            // matches is stale and its completion is ignored (spec/wizard.qnt).
            testGen: 0,
            verifyGen: 0,
            // Bumped by any navigation or edit, so a recipient preview that
            // arrives after the user has moved on or changed the content is
            // dropped (spec/wizard.qnt, noStepJump and previewHonest).
            previewGen: 0,
            // "Stop sending" pressed before the start-job response gave the
            // send's job id; sent once the id is known (spec/wizard.qnt,
            // stopHonoured).
            stopQueued: false,
            sendResults: null,
        };
    }

    /** Fields to change when the test and dry-run results stop applying. */
    function resetTestAndVerify(s) {
        return {
            testPassed: false,
            verifyPassed: false,
            testGen: s.testGen + 1,
            verifyGen: s.verifyGen + 1,
            // Let the user start a fresh test even if an old one is running.
            testRunning: false,
            testFailed: false,
            testResult: null,
            verifyResult: null,
        };
    }

    /** The state after "New merge". Counters keep counting so stale jobs and
     *  responses from the previous merge stay stale. */
    function newMergeState(s) {
        return Object.assign(initialState(), {
            contentVersion: s.contentVersion + 1,
            testGen: s.testGen + 1,
            verifyGen: s.verifyGen + 1,
            previewGen: s.previewGen + 1,
        });
    }

    // --- Selectors. `auth` is { signedIn }, what the page last fetched from
    // /auth/status (the model's authShown). ---

    /** "Send test email" can be clicked (model: sendTestEnabled). */
    function sendTestEnabled(s, auth) {
        return auth.signedIn && !s.testRunning;
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
    function signInOffered(s, auth) {
        return !auth.signedIn && (s.currentStep === 4 || (s.currentStep === 6 && !s.sendStarted));
    }

    /** "Send emails" can be clicked; `confirmed` is whether SEND was typed
     *  (model: doSendEnabled). */
    function doSendEnabled(s, auth, confirmed) {
        return auth.signedIn && confirmed && !s.sendStarted;
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
