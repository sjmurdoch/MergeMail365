// Unit tests for src/mail_merge/web/static/wizard-core.js (node --test).
// Run through tests/test_wizard_core_js.py, so `uv run pytest` covers them.
const test = require("node:test");
const assert = require("node:assert/strict");
const C = require("../../src/mail_merge/web/static/wizard-core.js");

const signedIn = { signedIn: true };
const signedOut = { signedIn: false };

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
    assert.equal(C.sendTestEnabled(s, signedIn), true);
    assert.equal(C.sendTestEnabled(s, signedOut), false);
    s.testRunning = true;
    assert.equal(C.sendTestEnabled(s, signedIn), false);
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
        assert.equal(C.signInOffered(s, signedOut), false, `step ${step}`);
    }
    s.currentStep = 4;
    assert.equal(C.signInOffered(s, signedOut), true);
    assert.equal(C.signInOffered(s, signedIn), false);
    s.currentStep = 6;
    assert.equal(C.signInOffered(s, signedOut), true);
    s.sendStarted = true;
    assert.equal(C.signInOffered(s, signedOut), false);
});

test("Send emails needs sign-in, SEND typed and no send started (model: doSendEnabled)", () => {
    const s = C.initialState();
    assert.equal(C.doSendEnabled(s, signedIn, true), true);
    assert.equal(C.doSendEnabled(s, signedOut, true), false);
    assert.equal(C.doSendEnabled(s, signedIn, false), false);
    s.sendStarted = true;
    assert.equal(C.doSendEnabled(s, signedIn, true), false);
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
