// Unit tests for src/mail_merge/web/static/wizard-core.js (node --test).
// Run through tests/test_wizard_core_js.py, so `uv run pytest` covers them.
const test = require("node:test");
const assert = require("node:assert/strict");
const C = require("../../src/mail_merge/web/static/wizard-core.js");

function signed(s, signedIn) {
    return Object.assign({}, s, { signedIn });
}

test("initialState is a fresh object each time", () => {
    const a = C.initialState();
    const b = C.initialState();
    assert.notEqual(a, b);
    a.testPassed = true;
    assert.equal(b.testPassed, false);
});

test("Next on steps 4 and 5 follows the flags (model: buttonsMatchFlags)", () => {
    for (const passed of [false, true]) {
        const s = Object.assign(C.initialState(), { testPassed: passed, verifyPassed: passed });
        assert.equal(C.nextEnabled(s, 4), passed);
        assert.equal(C.nextEnabled(s, 5), passed);
    }
});

test("Send test email needs sign-in and no test running (model: sendTestEnabled)", () => {
    const s = C.initialState();
    assert.equal(C.sendTestEnabled(signed(s, true)), true);
    assert.equal(C.sendTestEnabled(signed(s, false)), false);
    s.testRunning = true;
    assert.equal(C.sendTestEnabled(signed(s, true)), false);
});

test("Retry shows after a failed test, not while one runs", () => {
    const s = C.initialState();
    assert.equal(C.retryVisible(s), false);
    s.testFailed = true;
    assert.equal(C.retryVisible(s), true);
    s.testRunning = true;
    assert.equal(C.retryVisible(s), false);
});

test("sign-in is offered on step 4, and on step 6 before sending (model: signInOffered)", () => {
    const s = C.initialState();
    for (const step of [1, 2, 3, 5]) {
        s.currentStep = step;
        assert.equal(C.signInOffered(signed(s, false)), false, `step ${step}`);
    }
    s.currentStep = 4;
    assert.equal(C.signInOffered(signed(s, false)), true);
    assert.equal(C.signInOffered(signed(s, true)), false);
    s.currentStep = 6;
    assert.equal(C.signInOffered(signed(s, false)), true);
    s.sendStarted = true;
    assert.equal(C.signInOffered(signed(s, false)), false);
});

test("Send emails needs sign-in, SEND typed and no send started (model: doSendEnabled)", () => {
    const s = C.initialState();
    assert.equal(C.doSendEnabled(signed(s, true), true), true);
    assert.equal(C.doSendEnabled(signed(s, false), true), false);
    assert.equal(C.doSendEnabled(signed(s, true), false), false);
    s.sendStarted = true;
    assert.equal(C.doSendEnabled(signed(s, true), true), false);
});

test("Back on step 6 works until the send starts (model: back6Usable)", () => {
    const s = C.initialState();
    assert.equal(C.back6Enabled(s), true);
    s.sendStarted = true;
    assert.equal(C.back6Enabled(s), false);
});

test("step 6 shows confirm, then progress, then the outcome", () => {
    const s = C.initialState();
    assert.equal(C.sendPanel(s), "confirm");
    s.sendStarted = true;
    assert.equal(C.sendPanel(s), "progress");
    s.sendOutcome = "error";
    assert.equal(C.sendPanel(s), "done");
});

test("resetTestAndVerify clears both checks and makes running jobs stale", () => {
    let s = Object.assign(C.initialState(), {
        testPassed: true, verifyPassed: true, testRunning: true, testFailed: true,
        testResult: { success: true, message: "ok" }, verifyResult: { success: true, message: "ok" },
    });
    let r = C.startRequest(s, "test");
    s = Object.assign(s, r.patch);
    const testId = r.id;
    r = C.startRequest(s, "send");
    s = Object.assign(s, r.patch);
    const sendId = r.id;
    const after = Object.assign({}, s, C.resetTestAndVerify(s));
    assert.equal(after.testPassed, false);
    assert.equal(after.verifyPassed, false);
    assert.equal(after.testRunning, false);
    assert.equal(after.testFailed, false);
    assert.equal(after.testResult, null);
    assert.equal(after.verifyResult, null);
    assert.equal(C.isCurrent(after, testId), false);
    assert.equal(C.isCurrent(after, sendId), true);
});

test("a new request replaces the previous one of its kind (stale completions)", () => {
    let s = C.initialState();
    const first = C.startRequest(s, "test");
    s = Object.assign(s, first.patch);
    const preview = C.startRequest(s, "preview");
    s = Object.assign(s, preview.patch);
    const second = C.startRequest(s, "test");
    s = Object.assign(s, second.patch);
    assert.equal(C.isCurrent(s, first.id), false);
    assert.equal(C.isCurrent(s, second.id), true);
    assert.equal(C.isCurrent(s, preview.id), true);
    assert.notEqual(first.id, second.id);
    s = Object.assign(s, C.dropRequests(s, ["preview"]));
    assert.equal(C.isCurrent(s, preview.id), false);
    s = Object.assign(s, C.finishRequest(s, second.id));
    assert.equal(C.isCurrent(s, second.id), false);
});

test("requests record the content version they were made for", () => {
    const s = Object.assign(C.initialState(), { contentVersion: 4 });
    const { patch, id } = C.startRequest(s, "verify");
    assert.equal(patch.requests[id].contentVersion, 4);
});

test("a Stop pressed before the start-job response is kept on the send request", () => {
    let s = C.initialState();
    assert.equal(C.pendingRequest(s, "send"), null);
    const { patch, id } = C.startRequest(s, "send");
    s = Object.assign(s, patch);
    assert.equal(C.pendingRequest(s, "send"), id);
    s = Object.assign(s, C.updateRequest(s, id, { stopQueued: true }));
    assert.equal(s.requests[id].stopQueued, true);
    assert.deepEqual(C.updateRequest(s, 999, { stopQueued: true }), {});
});

test("New merge resets everything, drops requests and keeps ids counting", () => {
    let s = Object.assign(C.initialState(), {
        currentStep: 6, sendStarted: true, sendOutcome: "results", testPassed: true, contentVersion: 7,
    });
    const { patch, id } = C.startRequest(s, "test");
    s = Object.assign(s, patch);
    const after = C.newMergeState(s);
    assert.equal(after.currentStep, 1);
    assert.equal(after.sendStarted, false);
    assert.equal(after.sendOutcome, null);
    assert.equal(after.testPassed, false);
    assert.ok(after.contentVersion > s.contentVersion);
    assert.equal(C.isCurrent(after, id), false);
    assert.ok(C.startRequest(after, "test").id > id);
});

// --- reduce(): navigation (spec/wizard.qnt next1..next5, back2..back6, previewResponse) ---

function at(step, fields = {}) {
    return Object.assign(C.initialState(), { currentStep: step, spreadsheetData: { rows: [] } }, fields);
}

test("next1 needs a spreadsheet", () => {
    const r = C.reduce(at(1, { spreadsheetData: null }), C.ACTIONS.next1);
    assert.equal(r.state.currentStep, 1);
    assert.deepEqual(r.effects, [{ type: "alert", message: "Please upload a spreadsheet." }]);
    const ok = C.reduce(at(1), C.ACTIONS.next1);
    assert.equal(ok.state.currentStep, 2);
    assert.deepEqual(ok.effects, [{ type: "initCompose" }]);
});

test("next2 waits for the recipient list; a current response moves to step 3", () => {
    const s = at(2, { contentVersion: 5 });
    const blocked = C.reduce(s, { type: "goTo", to: 3, composeOk: false });
    assert.equal(blocked.state.currentStep, 2);
    assert.deepEqual(blocked.effects, []);
    const r = C.reduce(s, { type: "goTo", to: 3, composeOk: true });
    assert.equal(r.state.currentStep, 2);
    assert.equal(r.effects.length, 1);
    const { type, id } = r.effects[0];
    assert.equal(type, "fetchPreview");
    const done = C.reduce(r.state, { type: "previewResponse", id, ok: true });
    assert.equal(done.state.currentStep, 3);
    assert.equal(done.state.recipientsVersion, 5);
    assert.equal(C.isCurrent(done.state, id), false);
});

test("a preview response after Back or an edit is dropped (noStepJump, previewHonest)", () => {
    const r = C.reduce(at(2), { type: "goTo", to: 3, composeOk: true });
    const id = r.effects[0].id;
    // Back to step 1 before the list arrives.
    const back = C.reduce(r.state, C.ACTIONS.back2);
    const late = C.reduce(back.state, { type: "previewResponse", id, ok: true });
    assert.equal(late.state.currentStep, 1);
    // An edit drops the request.
    const edited = C.reduce(r.state, C.ACTIONS.edit).state;
    const stale = C.reduce(edited, { type: "previewResponse", id, ok: true });
    assert.equal(stale.state.currentStep, 2);
});

test("a failed preview stays on step 2", () => {
    const r = C.reduce(at(2), { type: "goTo", to: 3, composeOk: true });
    const failed = C.reduce(r.state, { type: "previewResponse", id: r.effects[0].id, ok: false });
    assert.equal(failed.state.currentStep, 2);
});

test("next3 enters the test step; next4 and next5 need the checks to have passed", () => {
    assert.deepEqual(C.reduce(at(3), C.ACTIONS.next3).effects, [{ type: "enterTest" }]);
    assert.equal(C.reduce(at(4), C.ACTIONS.next4).state.currentStep, 4);
    const r4 = C.reduce(at(4, { testPassed: true }), C.ACTIONS.next4);
    assert.equal(r4.state.currentStep, 5);
    assert.equal(r4.effects.length, 1);
    assert.deepEqual(r4.effects[0], { type: "startJob", mode: "dry_run", id: r4.effects[0].id });
    assert.equal(C.pendingRequest(r4.state, "verify"), r4.effects[0].id);
    assert.equal(C.reduce(at(5), C.ACTIONS.next5).state.currentStep, 5);
    const r5 = C.reduce(at(5, { verifyPassed: true }), C.ACTIONS.next5);
    assert.equal(r5.state.currentStep, 6);
    assert.deepEqual(r5.effects, [{ type: "prepareSend" }]);
});

test("back from step 4 or later asks first when a check has passed", () => {
    const s = at(4, { testPassed: true });
    assert.equal(C.needsConfirmBack(s), true);
    const declined = C.reduce(s, { type: "back", to: 3, accepted: false });
    assert.equal(declined.state.currentStep, 4);
    assert.equal(declined.state.testPassed, true);
    const accepted = C.reduce(s, { type: "back", to: 3, accepted: true });
    assert.equal(accepted.state.currentStep, 3);
    assert.equal(accepted.state.testPassed, false);
    assert.deepEqual(accepted.effects, [{ type: "clearLogs" }]);
    assert.equal(C.needsConfirmBack(at(4)), false);
});

test("back from step 3 to 2 always resets the checks", () => {
    const r = C.reduce(at(3, { testPassed: true, verifyPassed: true }), C.ACTIONS.back3);
    assert.equal(r.state.currentStep, 2);
    assert.equal(r.state.testPassed, false);
    assert.equal(r.state.verifyPassed, false);
});

test("back6 returns to step 4, not to the dry run", () => {
    const r = C.reduce(at(6), Object.assign({ accepted: true }, C.ACTIONS.back6));
    assert.equal(r.state.currentStep, 4);
});

test("reduce returns a new state and rejects unknown events", () => {
    const s = at(1);
    const r = C.reduce(s, C.ACTIONS.next1);
    assert.notEqual(r.state, s);
    assert.equal(s.currentStep, 1);
    assert.throws(() => C.reduce(s, { type: "nope" }), /Unknown event/);
});

// --- reduce(): sign-in status ---

test("an /auth/status answer updates the sign-in state and asks to show it", () => {
    let s = C.initialState();
    const { patch, id } = C.startRequest(s, "auth");
    s = Object.assign(s, patch);
    const status = { authenticated: true, email: "me@example.com" };
    const r = C.reduce(s, { type: "authStatus", id, status });
    assert.equal(r.state.signedIn, true);
    assert.deepEqual(r.effects, [{ type: "showAuth", status }]);
    assert.equal(C.isCurrent(r.state, id), false);
});

test("an older /auth/status answer arriving last is dropped (R16)", () => {
    let s = C.initialState();
    const older = C.startRequest(s, "auth");
    s = Object.assign(s, older.patch);
    const newer = C.startRequest(s, "auth");
    s = Object.assign(s, newer.patch);
    s = C.reduce(s, { type: "authStatus", id: newer.id, status: { authenticated: false } }).state;
    const late = C.reduce(s, { type: "authStatus", id: older.id, status: { authenticated: true } });
    assert.equal(late.state.signedIn, false);
    assert.deepEqual(late.effects, []);
});

test("New merge keeps the sign-in state", () => {
    assert.equal(C.newMergeState(signed(C.initialState(), true)).signedIn, true);
});

// --- reduce(): reload and New merge ---

test("configLoaded restores the spreadsheet and never the passed checks", () => {
    const s = Object.assign(C.initialState(), { testPassed: true, verifyPassed: true });
    const sheet = { columns: ["email"], rows: [], sheets: ["S"] };
    const r = C.reduce(s, { type: "configLoaded", config: { spreadsheet: sheet, active_job_id: null } });
    assert.equal(r.state.spreadsheetData, sheet);
    assert.equal(r.state.testPassed, false);
    assert.equal(r.state.verifyPassed, false);
    assert.equal(r.state.currentStep, 1);
    assert.deepEqual(r.effects, [{ type: "showSpreadsheet" }]);
});

test("configLoaded with an active send goes to the sending screen and reconnects", () => {
    const r = C.reduce(C.initialState(), { type: "configLoaded", config: { active_job_id: "job-1" } });
    assert.equal(r.state.currentStep, 6);
    assert.equal(r.state.sendStarted, true);
    assert.equal(r.state.sendOutcome, null);
    assert.equal(r.state.currentJobId, "job-1");
    assert.equal(C.sendPanel(r.state), "progress");
    assert.deepEqual(r.effects, [{ type: "reconnectSend", jobId: "job-1" }]);
});

test("newMerge returns to step 1, resets the server and clears the form", () => {
    const s = Object.assign(C.initialState(), { currentStep: 6, sendStarted: true, sendOutcome: "results" });
    const r = C.reduce(s, C.ACTIONS.newMerge);
    assert.equal(r.state.currentStep, 1);
    assert.equal(r.state.sendStarted, false);
    assert.deepEqual(r.effects, [{ type: "resetServer" }, { type: "clearForm" }]);
});

// --- reduce(): content changes ---

test("an edit moves the content version on; an upload also replaces the data", () => {
    const s = C.initialState();
    const edited = C.reduce(s, C.ACTIONS.edit).state;
    assert.equal(edited.contentVersion, s.contentVersion + 1);
    const data = { columns: ["email"], rows: [] };
    const uploaded = C.reduce(edited, Object.assign({ data }, C.ACTIONS.upload)).state;
    assert.equal(uploaded.spreadsheetData, data);
    assert.equal(uploaded.contentVersion, edited.contentVersion + 1);
});

// --- reduce(): test email and dry run ---

function startTest(s) {
    const r = C.reduce(s, Object.assign({ addressOk: true }, C.ACTIONS.sendTestEmail));
    return { state: r.state, effects: r.effects, id: r.effects[0].id };
}

test("sendTestEmail needs an address", () => {
    const r = C.reduce(at(4), { type: "sendTestEmail", addressOk: false });
    assert.equal(r.state.testRunning, false);
    assert.equal(r.effects[0].type, "alert");
});

test("a test email that completes passes the step; a failure checks sign-in", () => {
    const t = startTest(at(4));
    assert.equal(t.state.testRunning, true);
    assert.deepEqual(t.effects, [{ type: "startJob", mode: "test_email", id: t.id }]);
    assert.equal(C.sendTestEnabled(signed(t.state, true)), false);

    const ok = C.reduce(t.state, { type: "jobCompleted", id: t.id, ok: true, message: "sent" });
    assert.equal(ok.state.testPassed, true);
    assert.equal(ok.state.testRunning, false);
    assert.deepEqual(ok.state.testResult, { success: true, message: "sent" });
    assert.deepEqual(ok.effects, [{ type: "saveState" }]);

    const failed = C.reduce(t.state, { type: "jobCompleted", id: t.id, ok: false, message: "no" });
    assert.equal(failed.state.testPassed, false);
    assert.equal(C.retryVisible(failed.state), true);
    assert.deepEqual(failed.effects, [{ type: "checkAuth" }]);
});

test("a stale test completion is ignored (model: completeJob, stale jobs)", () => {
    const first = startTest(at(4));
    const second = startTest(first.state);
    const late = C.reduce(second.state, { type: "jobCompleted", id: first.id, ok: true, message: "" });
    assert.equal(late.state.testPassed, false);
    assert.equal(late.state.testRunning, true);
    // Going back to compose makes the running test stale too.
    const back3 = C.reduce(first.state, { type: "back", to: 3, accepted: true });
    const back = C.reduce(back3.state, C.ACTIONS.back3);
    const after = C.reduce(back.state, { type: "jobCompleted", id: first.id, ok: true, message: "" });
    assert.equal(after.state.testPassed, false);
});

test("jobStarted records the job id only for a current request", () => {
    const t = startTest(at(4));
    assert.equal(C.reduce(t.state, { type: "jobStarted", id: t.id, jobId: "j" }).state.currentJobId, "j");
    assert.equal(C.reduce(t.state, { type: "jobStarted", id: 999, jobId: "j" }).state.currentJobId, null);
});

test("a dry run that completes passes step 5", () => {
    const r = C.reduce(at(4, { testPassed: true }), C.ACTIONS.next4);
    const id = r.effects[0].id;
    const done = C.reduce(r.state, { type: "jobCompleted", id, ok: true, message: "ready" });
    assert.equal(done.state.verifyPassed, true);
    assert.equal(C.nextEnabled(done.state, 5), true);
    const failed = C.reduce(r.state, { type: "jobCompleted", id, ok: false, message: "bad" });
    assert.equal(failed.state.verifyPassed, false);
    assert.deepEqual(failed.state.verifyResult, { success: false, message: "bad" });
});

// --- reduce(): the send ---

test("startSend shows progress and waits for the job id", () => {
    const r = C.reduce(at(6, { verifyPassed: true }), C.ACTIONS.startSend);
    assert.equal(C.sendPanel(r.state), "progress");
    assert.equal(r.state.currentJobId, null);
    assert.equal(C.back6Enabled(r.state), false);
    assert.equal(r.effects[0].type, "startSendJob");
    const resp = C.reduce(r.state, { type: "startSendResponse", id: r.effects[0].id, jobId: "s" });
    assert.equal(resp.state.currentJobId, "s");
    assert.deepEqual(resp.effects, [{ type: "streamSend", jobId: "s" }]);
});

test("Stop before the job id is known is sent once it is (model: stopHonoured)", () => {
    const r = C.reduce(at(6), C.ACTIONS.startSend);
    const stopped = C.reduce(r.state, C.ACTIONS.stopSend);
    assert.deepEqual(stopped.effects, []);
    const resp = C.reduce(stopped.state, { type: "startSendResponse", id: r.effects[0].id, jobId: "s" });
    assert.deepEqual(resp.effects, [{ type: "postStop", jobId: "s" }, { type: "streamSend", jobId: "s" }]);
    assert.deepEqual(C.reduce(resp.state, C.ACTIONS.stopSend).effects, [{ type: "postStop", jobId: "s" }]);
});

test("a send that can't start shows the error", () => {
    const r = C.reduce(at(6), C.ACTIONS.startSend);
    const resp = C.reduce(r.state, { type: "startSendResponse", id: r.effects[0].id, error: "busy" });
    assert.equal(C.sendPanel(resp.state), "done");
    assert.deepEqual(resp.effects, [{ type: "showSendError", message: "busy" }]);
});

test("a send lists its results if any email went out (model: failedSendReported)", () => {
    const s = at(6, { sendStarted: true, currentJobId: "s" });
    const cases = [
        [{ status: "completed" }, "fetchResults"],
        [{ status: "stopped" }, "fetchResults"],
        [{ status: "failed", error: "x", results: [{}] }, "fetchResults"],
        [{ status: "failed", error: "x", results: [] }, "showSendError"],
    ];
    for (const [result, effect] of cases) {
        const r = C.reduce(s, Object.assign({ jobId: "s", result }, C.ACTIONS.finishSend));
        assert.equal(r.effects[0].type, effect);
    }
    const listed = C.reduce(s, { type: "sendResults", data: { results: [{ email: "a" }] } });
    assert.equal(C.sendPanel(listed.state), "done");
    assert.deepEqual(listed.state.sendResults, [{ email: "a" }]);
});

test("every event is reachable from a model action or is a shell-only step", () => {
    const fromActions = new Set(Object.values(C.ACTIONS).map(a => a.type));
    // Shell-only: the job id arriving, and the send's results or error being
    // fetched after finishSend; none changes the model's state.
    const shellOnly = new Set(["jobStarted", "sendResults", "sendError"]);
    for (const e of C.EVENTS) {
        assert.ok(fromActions.has(e) || shellOnly.has(e), e);
    }
});
