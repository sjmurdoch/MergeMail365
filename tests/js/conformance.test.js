// Client-tier conformance (archive/quint-model-plan.md, step 4): replay traces
// of spec/wizard.qnt (`fixed`) through WizardCore.reduce() and compare
// abstractPage() with the model's page fields after every step.
//
// Traces come from `quint run --mbt --out-itf`, which records each step's
// action (mbt::actionTaken) and nondeterministic picks (mbt::nondetPicks).
// tests/test_conformance.py generates them and runs this file with
// TRACES_DIR set; without it the test is skipped.
//
// This file plays the shell (app.js): it turns each model action into the
// event the page would dispatch, and answers the effects that need the
// server (start-job responses, job completions, /auth/status) from the
// trace. Server-only actions (sendNext, completeOrphan, tokenExpires) have
// no page event; they are checked by the server tier.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
// WIZARD_CORE lets tests/test_conformance.py replay against a mutated copy.
const C = require(process.env.WIZARD_CORE || "../../src/mail_merge/web/static/wizard-core.js");

const TRACES_DIR = process.env.TRACES_DIR;

// --- ITF decoding ---

function decode(v) {
    if (v === null || typeof v !== "object") return v;
    if (Array.isArray(v)) return v.map(decode);
    if ("#bigint" in v) return Number(v["#bigint"]);
    if ("#set" in v) return v["#set"].map(decode);
    if ("#tup" in v) return v["#tup"].map(decode);
    if ("#map" in v) return v["#map"].map(decode);
    if ("tag" in v && "value" in v && Object.keys(v).length === 2) {
        // Enum values (Kind, Status) are variants without payload.
        const value = decode(v.value);
        if (Array.isArray(value) && value.length === 0) return v.tag;
        return { tag: v.tag, value };
    }
    const out = {};
    for (const [k, x] of Object.entries(v)) out[k] = decode(x);
    return out;
}

function loadTrace(file) {
    const raw = JSON.parse(fs.readFileSync(file, "utf8"));
    const sVar = raw.vars.find(v => v.endsWith("::s"));
    return raw.states.map(st => ({
        s: decode(st[sVar]),
        action: st["mbt::actionTaken"],
        picks: Object.fromEntries(Object.entries(decode(st["mbt::nondetPicks"]))
            .filter(([, p]) => p.tag === "Some")
            .map(([k, p]) => [k, p.value])),
    }));
}

// --- The model's view of the page (what abstractPage should equal) ---

function isCurrentJob(m, p) {
    return p.gen === (p.kind === "Test" ? m.testGen : m.verifyGen);
}

/** The model's page fields, with requests reduced to the current ones. */
function modelPage(m) {
    return {
        step: m.step,
        dataLoaded: m.dataLoaded,
        testPassed: m.testPassed,
        verifyPassed: m.verifyPassed,
        sendStarted: m.sendStarted,
        verifyShown: m.verifyShown,
        resultsShown: m.resultsShown,
        btnSendTest: m.btnSendTest,
        btnNext4: m.btnNext4,
        btnNext5: m.btnNext5,
        btnDoSend: m.btnDoSend,
        // Shown only on step 6; elsewhere the model leaves it stale (New
        // merge doesn't reset it), the code derives it (buttonsDerived).
        btnBack6: m.step === 6 ? m.btnBack6 : undefined,
        doneNav: m.doneNav,
        sendReq: m.sendReq.length,
        stopQueued: m.stopQueued,
        authShown: m.authShown,
        interruptedShown: m.interruptedShown,
    };
}

/** /api/config's interrupted_sends for the model's send log. */
function interruptedSends(m) {
    return m.sendLog.map(l => ({ started: null, results: Array.from({ length: l.sent }, () => ({ success: true })) }));
}

// --- The replay ---

const DATA = { columns: ["email"], rows: [{ email: "a@example.com" }], sheets: ["S"], file_name: "r.xlsx", total_rows: 1 };

class Replay {
    constructor(first) {
        this.m = first;          // model state before the current step
        this.next = first;       // model state after it
        this.fresh();
    }

    /** A new page: what app.js has after a load or a server restart. */
    fresh() {
        this.state = C.initialState();
        this.confirmed = false;  // #send-confirm-input says SEND
        this.jobRequests = new Map();    // model job id -> request id (test, dry run)
        this.previewRequests = new Map(); // model preview gen -> request id
        this.sendRequests = new Map();   // model send job id -> request id
        this.versions = new Map();       // model version -> contentVersion
        this.pendingRequest = null;      // { kind, id } created by the last event
        this.effects = [];               // effects of the current step
    }

    dispatch(event) {
        const before = this.state;
        const { state, effects } = C.reduce(before, event);
        this.state = state;
        for (const e of effects) this.effect(e);
    }

    effect(e) {
        this.effects.push(e);
        switch (e.type) {
            case "fetchPreview":
                this.pendingRequest = { kind: "preview", id: e.id };
                break;
            case "startJob":
                this.pendingRequest = { kind: "job", id: e.id };
                // The start-job response names the job straight away: the
                // model creates the job and the page's callback in one step.
                this.dispatch({ type: "jobStarted", id: e.id, jobId: `job-${this.m.nextJobId}` });
                break;
            case "startSendJob":
                this.pendingRequest = { kind: "send", id: e.id };
                break;
            case "enterTest":
            case "checkAuth":
                this.answerAuth();
                break;
            case "prepareSend":
                this.confirmed = false;  // prepareSend() empties the input
                this.answerAuth();
                break;
            case "clearForm":
                this.confirmed = false;
                break;
            case "streamSend":
            case "reconnectSend":
                // A finished job's stream ends at once (startSendResponse
                // and reload of a finished send, in the model).
                this.finishedJobEnds(e.jobId);
                break;
            case "fetchResults": {
                const j = this.sendJob(e.jobId, this.next);
                this.dispatch({ type: "sendResults", data: { status: j.status.toLowerCase(), results: [] } });
                break;
            }
            default:
                // alert, initCompose, saveState, clearLogs, showAuth,
                // showSpreadsheet, resetServer, postStop, showResults,
                // showSendError: no state the model tracks.
        }
    }

    answerAuth() {
        const { patch, id } = C.startRequest(this.state, "auth");
        this.state = Object.assign({}, this.state, patch);
        this.dispatch({ type: "authStatus", id, status: { authenticated: this.next.signedIn } });
    }

    sendJob(jobId, m) {
        const id = Number(String(jobId).replace("job-", ""));
        return m.sendJob.find(j => j.id === id);
    }

    finishedJobEnds(jobId) {
        const j = this.sendJob(jobId, this.m);
        if (j && j.status !== "Running") this.sendCompleted(jobId, j);
    }

    sendCompleted(jobId, j) {
        const result = {
            status: j.status === "Completed" ? "completed" : j.status === "Stopped" ? "stopped" : "failed",
            results: Array.from({ length: j.sent }, () => ({})),
            error: j.status === "Failed" ? "failed" : undefined,
        };
        this.dispatch({ type: "sendCompleted", jobId, result });
    }

    /** /api/config after a reload, as JobStore.active_job_id answers it. */
    reload(m) {
        this.fresh();
        const running = m.sendJob.filter(j => j.status === "Running");
        const sessionSend = m.sessionJob.filter(sj => sj.kind === "Send");
        const active = running.length > 0 ? running[0].id : sessionSend.length > 0 ? sessionSend[0].id : null;
        this.dispatch({
            type: "configLoaded",
            config: {
                spreadsheet: m.dataLoaded ? DATA : null,
                active_job_id: active === null ? null : `job-${active}`,
                interrupted_sends: interruptedSends(m),
            },
        });
        this.answerAuth();
    }

    step(m, next, action, picks) {
        this.m = m;
        this.next = next;
        this.pendingRequest = null;
        this.effects = [];
        const event = (name, extra = {}) => this.dispatch(Object.assign({}, C.ACTIONS[name], extra));
        switch (action) {
            case "upload":
                event("upload", { data: DATA });
                break;
            case "edit":
                event("edit");
                break;
            case "next1": case "back2": case "next3": case "next4": case "next5":
                event(action);
                break;
            case "next2":
                event(action, { composeOk: true });
                break;
            case "back3":
                event(action, { accepted: true });
                break;
            case "back4": case "back5": case "back6":
                event(action, { accepted: picks.a });
                break;
            case "previewResponse": {
                const id = this.previewRequests.get(picks.r.gen);
                if (id !== undefined) this.dispatch({ type: "previewResponse", id, ok: picks.ok });
                break;
            }
            case "sendTestEmail":
                event(action, { addressOk: true });
                break;
            case "completeJob": {
                const j = picks.j;
                const id = this.jobRequests.get(j.id);
                // finishJob: a test email without a token fails.
                const ok = picks.ok && !(j.kind === "Test" && !m.signedIn);
                if (id !== undefined) this.dispatch({ type: "jobCompleted", id, ok, message: "" });
                break;
            }
            case "typeSend":
                this.confirmed = true;
                break;
            case "startSend":
                event(action);
                break;
            case "startSendResponse": {
                const id = this.sendRequests.get(picks.id);
                this.dispatch({ type: "startSendResponse", id, jobId: `job-${picks.id}` });
                break;
            }
            case "stopSend":
                event(action);
                break;
            case "finishSend":
            case "sendWithoutToken": {
                // The page's send callback fires if it is listening to the job.
                const j = picks.j;
                if (m.pending.some(p => p.id === j.id && p.handler === "Send")) {
                    this.sendCompleted(`job-${j.id}`, this.sendJob(`job-${j.id}`, next));
                }
                break;
            }
            case "newMerge":
            case "dismissInterrupted":
                event(action);
                break;
            case "signIn":
                if (picks.desktop) this.answerAuth();
                else this.reload(next);
                break;
            case "signOut":
                this.answerAuth();
                break;
            case "reload":
                this.reload(m);
                break;
            case "serverRestart":
                // The page starts again against a server with no session.
                this.fresh();
                this.dispatch({
                    type: "configLoaded",
                    config: { spreadsheet: null, active_job_id: null, interrupted_sends: interruptedSends(next) },
                });
                this.answerAuth();
                break;
            case "completeOrphan": case "sendNext": case "tokenExpires":
                break;  // server only
            default:
                throw new Error(`no driver for model action ${action}`);
        }
        this.recordRequest(m, next, action);
    }

    /** What the page asked of the server matches what the model's server did. */
    checkServerEffects(m, next, where) {
        const started = this.effects.filter(e => e.type === "startJob" || e.type === "startSendJob").length;
        assert.equal(started, next.nextJobId - m.nextJobId, `${where}: jobs started`);
        const posted = new Set(this.effects.filter(e => e.type === "postStop").map(e => e.jobId));
        for (const j of next.sendJob) {
            const before = m.sendJob.find(x => x.id === j.id);
            if (j.stopRequested && !(before && before.stopRequested)) {
                assert.ok(posted.has(`job-${j.id}`), `${where}: Stop for job ${j.id} was not posted`);
            }
        }
    }

    /** Pair the request the event created with the model's job or preview. */
    recordRequest(m, next, action) {
        const r = this.pendingRequest;
        if (!r) return;
        if (r.kind === "preview") this.previewRequests.set(next.previewGen, r.id);
        if (r.kind === "job") this.jobRequests.set(m.nextJobId, r.id);
        if (r.kind === "send") this.sendRequests.set(m.nextJobId, r.id);
        void action;
    }

    /** Model versions and the page's content versions correspond one to one. */
    sameVersion(modelVersion, pageVersion, where) {
        if (modelVersion === -1 || pageVersion === -1) {
            assert.equal(pageVersion, modelVersion, where);
            return;
        }
        if (this.versions.has(modelVersion)) {
            assert.equal(pageVersion, this.versions.get(modelVersion), where);
        } else {
            for (const [mv, pv] of this.versions) {
                assert.ok(pv !== pageVersion, `${where}: page version ${pageVersion} is model version ${mv} and ${modelVersion}`);
            }
            this.versions.set(modelVersion, pageVersion);
        }
    }

    /** The model's pure defs that guard user actions equal the selectors
     *  render() uses for the same controls. */
    compareGuards(m, where) {
        const s = this.state;
        assert.deepEqual({
            sendTestEnabled: C.sendTestEnabled(s),
            doSendEnabled: C.doSendEnabled(s, this.confirmed),
            // The header's sign-in button (step 1) is outside the selector.
            signInOffered: m.step === 1 || C.signInOffered(s),
        }, {
            sendTestEnabled: m.btnSendTest && m.authShown,
            doSendEnabled: m.btnDoSend && m.authShown,
            signInOffered: m.step === 1 || (!m.authShown && (m.step === 4 || (m.step === 6 && !m.sendStarted))),
        }, `${where}: guards`);
    }

    compare(m, where) {
        const page = C.abstractPage(this.state, this.confirmed);
        const expected = modelPage(m);
        const actual = {};
        for (const k of Object.keys(expected)) actual[k] = expected[k] === undefined ? undefined : page[k];
        assert.deepEqual(actual, expected, where);
        this.compareGuards(m, where);
        this.sameVersion(m.version, page.version, `${where}: version`);
        this.sameVersion(m.recipientsVersion, page.recipientsVersion, `${where}: recipientsVersion`);
        const pending = m.pending.filter(p => p.kind !== "Send" && p.handler === p.kind && isCurrentJob(m, p));
        assert.deepEqual(page.pending.map(p => p.kind).sort(), pending.map(p => p.kind).sort(), `${where}: pending`);
        for (const p of pending) {
            const q = page.pending.find(x => x.kind === p.kind);
            this.sameVersion(p.version, q.version, `${where}: pending ${p.kind} version`);
        }
        const previews = m.previewReq.filter(r => r.gen === m.previewGen);
        assert.equal(page.previewReq.length, previews.length, `${where}: previewReq`);
        for (const [i, r] of previews.entries()) {
            this.sameVersion(r.version, page.previewReq[i].version, `${where}: previewReq version`);
        }
    }
}

function replayTrace(file) {
    const trace = loadTrace(file);
    const replay = new Replay(trace[0].s);
    replay.compare(trace[0].s, `${path.basename(file)} init`);
    for (let i = 1; i < trace.length; i++) {
        const { s, action, picks } = trace[i];
        const where = `${path.basename(file)} step ${i} (${trace.slice(1, i + 1).map(t => t.action).join(" ")})`;
        replay.step(trace[i - 1].s, s, action, picks);
        replay.checkServerEffects(trace[i - 1].s, s, where);
        replay.compare(s, where);
    }
    return trace.length - 1;
}

test("client conformance: replay model traces through reduce()", { skip: !TRACES_DIR && "TRACES_DIR not set" }, () => {
    const files = fs.readdirSync(TRACES_DIR).filter(f => f.endsWith(".itf.json")).sort();
    assert.ok(files.length > 0, `no traces in ${TRACES_DIR}`);
    let steps = 0;
    for (const f of files) steps += replayTrace(path.join(TRACES_DIR, f));
    assert.ok(steps > 0);
});

module.exports = { decode, loadTrace, Replay, replayTrace };
