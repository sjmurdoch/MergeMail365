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
    const s = Object.assign(C.initialState(), {
        testPassed: true, verifyPassed: true, testRunning: true, testFailed: true,
        testResult: { success: true, message: "ok" }, verifyResult: { success: true, message: "ok" },
        testGen: 3, verifyGen: 5,
    });
    const after = Object.assign({}, s, C.resetTestAndVerify(s));
    assert.equal(after.testPassed, false);
    assert.equal(after.verifyPassed, false);
    assert.equal(after.testRunning, false);
    assert.equal(after.testFailed, false);
    assert.equal(after.testResult, null);
    assert.equal(after.verifyResult, null);
    assert.equal(after.testGen, 4);
    assert.equal(after.verifyGen, 6);
});

test("New merge resets everything but keeps the counters counting", () => {
    const s = Object.assign(C.initialState(), {
        currentStep: 6, sendStarted: true, sendOutcome: "results", testPassed: true,
        contentVersion: 7, testGen: 2, verifyGen: 2, previewGen: 9,
    });
    const after = C.newMergeState(s);
    assert.equal(after.currentStep, 1);
    assert.equal(after.sendStarted, false);
    assert.equal(after.sendOutcome, null);
    assert.equal(after.testPassed, false);
    assert.ok(after.contentVersion > s.contentVersion);
    assert.ok(after.testGen > s.testGen);
    assert.ok(after.verifyGen > s.verifyGen);
    assert.ok(after.previewGen > s.previewGen);
});
