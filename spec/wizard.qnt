// -*- mode: Bluespec; -*-
/**
 * Workflow layer of the web UI wizard (src/mail_merge/web/static/app.js and
 * the job/session parts of web/app.py).
 *
 * ROUND counts the rounds of fixes in archive/quint-model-plan.md that are
 * applied: `buggy` (0) is the code before any of them, bugs included;
 * `partial` (1) has the fixes of steps 2, 2b and 2c (bugs 1-9); `fixed` (2)
 * is the current code, which must satisfy every invariant. FIXED gates the
 * round 1 fixes and FIXED2 the round 2 fixes (bugs 10-15).
 *
 * Abstractions:
 * - `version` stands for everything that determines what gets sent
 *   (spreadsheet, sheet, compose fields, options). Any upload or edit bumps it.
 * - A job is started by an action and completed later by a separate action,
 *   so completions can interleave with navigation and reloads. Handlers that
 *   `await` a request whose result changes the page are split the same way
 *   (the recipient preview, starting a send), so clicks can land in between.
 * - Ghost fields (testedVersions, verifiedVersions, ...) record what really
 *   happened; the code never reads them, only the invariants do.
 * - Button fields mirror `disabled` (true = enabled) for buttons whose state
 *   the code sets explicitly.
 */
module wizard {
  const ROUND: int
  pure val FIXED = ROUND >= 1
  pure val FIXED2 = ROUND >= 2

  type Kind = Test | Verify | Send

  type Job = {
    id: int,
    kind: Kind,      // mode sent to /api/start-job
    handler: Kind,   // which completion callback the page attached
    version: int,    // content version the job ran with
    gen: int,        // generation stamp (only checked when FIXED)
  }

  // The job id stored in session["job_id"] and whether it has finished.
  type SessionJob = { id: int, kind: Kind, done: bool }

  // web/app.py JobStatus, for the server's record of a send job.
  type Status = Running | Completed | Failed | Stopped | Killed  // Killed: the server stopped mid-send

  // The server's record of the current send job (web/app.py Job, mode
  // "send"): how many emails the send loop has sent and whether Stop was
  // pressed. `stopEarly` is a ghost: Stop was pressed while emails remained.
  type SendJob = { id: int, sent: int, stopRequested: bool, status: Status, stopEarly: bool }

  // A send whose log on disk outlived the process (web/jobs.py SendLog):
  // the job and the emails it had sent.
  type LoggedSend = { id: int, sent: int }

  // POST /api/get-recipients in flight for goToStep(3): the content version
  // it was sent for and the page's preview generation at the time.
  type PreviewReq = { version: int, gen: int }

  // Recipients in a send. Small, to keep the state space small; three is
  // enough for "stop, then two more emails go out".
  pure val TOTAL = 3

  type State = {
    // --- app.js state ---
    step: int,
    dataLoaded: bool,
    version: int,
    testPassed: bool,
    verifyPassed: bool,
    sendStarted: bool,
    testGen: int,
    verifyGen: int,
    previewGen: int,
    recipientsVersion: int,       // content version the page's recipient list was fetched for; -1 = none
    // --- DOM projection (true = enabled / visible) ---
    btnNext2: bool,
    verifyShown: bool,            // #verify-result shows a dry-run outcome
    resultsShown: bool,           // #send-result shows the per-recipient results table
    interruptedShown: bool,       // #interrupted-send shows a send the last process didn't finish
    progressJob: int,             // send job whose progress #send-progress-text shows; -1 = none
    bccToMerge: int,              // merge in which #bcc-blast-to was typed; -1 = empty
    btnSendTest: bool,
    btnNext4: bool,
    btnNext5: bool,
    btnDoSend: bool,
    btnBack6: bool,
    doneNav: bool,
    // --- requests and completion callbacks pending in the current page ---
    pending: Set[Job],
    previewReq: Set[PreviewReq],
    sendReq: Set[int],            // POST /api/start-job (send) awaiting its response: the job id
    // --- server ---
    sessionJob: Set[SessionJob],  // empty or singleton
    nextJobId: int,
    sendJob: Set[SendJob],        // empty or singleton
    sendLog: Set[LoggedSend],     // FIXED2: interrupted sends on disk, not yet dismissed
    // --- auth ---
    signedIn: bool,               // the token cache has an account with a usable token
    authShown: bool,              // what the page last showed from /auth/status (_auth.isSignedIn)
    // --- ghost ---
    testedVersions: Set[int],
    verifiedVersions: Set[int],
    realSendStarted: bool,
    untestedSend: bool,
    sentAfterStop: int,           // emails the send loop sent after Stop was pressed
    interactiveAuthInJob: bool,   // a job waited for the device-code flow
    mailSignedOut: bool,          // a test email or send was started while the page showed signed
                                  // out, or an email went out without a usable token
    stepJump: bool,               // a response moved the page from a step the user had left
    concurrentSends: bool,        // a send started while another was running
    mergeId: int,                 // counts New merge
    lostSend: bool,               // a server restart killed a send after emails went out
    stopLost: bool,               // "Stop sending" was pressed but reached no running send
    stopQueued: bool,             // FIXED2: Stop pressed before the send's job id was known
  }

  var s: State
  var lastAction: str

  pure val init_state: State = {
    step: 1, dataLoaded: false, version: 0,
    testPassed: false, verifyPassed: false, sendStarted: false,
    testGen: 0, verifyGen: 0, previewGen: 0, recipientsVersion: -1,
    btnNext2: true, verifyShown: false, resultsShown: false, interruptedShown: false, progressJob: -1, bccToMerge: -1,
    btnSendTest: true, btnNext4: false, btnNext5: false,
    btnDoSend: false, btnBack6: true, doneNav: false,
    pending: Set(), previewReq: Set(), sendReq: Set(),
    sessionJob: Set(), nextJobId: 0, sendJob: Set(), sendLog: Set(),
    signedIn: false, authShown: false,
    testedVersions: Set(), verifiedVersions: Set(),
    realSendStarted: false, untestedSend: false, sentAfterStop: 0,
    interactiveAuthInJob: false, mailSignedOut: false,
    stepJump: false, concurrentSends: false, mergeId: 0, lostSend: false,
    stopLost: false, stopQueued: false,
  }

  // ---------------------------------------------------------------------
  // What the page offers. Actions use these as guards and the invariants
  // read them, so the two can't drift apart.
  // ---------------------------------------------------------------------

  // The sign-in button: on step 1 always, and (FIXED) in the callout that
  // steps 4 and 6 show while the page shows signed out.
  pure def signInOffered(st: State): bool =
    st.step == 1
      or (FIXED and not(st.authShown)
          and (st.step == 4 or (st.step == 6 and not(st.sendStarted))))

  // "Send test email" can be clicked. FIXED: also disabled while signed out.
  pure def sendTestEnabled(st: State): bool =
    st.btnSendTest and (not(FIXED) or st.authShown)

  // "Send emails" can be clicked. FIXED: also disabled while signed out.
  pure def doSendEnabled(st: State): bool =
    st.btnDoSend and (not(FIXED) or st.authShown)

  // A test email or dry run whose completion the page still applies: in the
  // code, its request is still in state.requests (wizard-core.js isCurrent).
  // The generation counters here are that request id: bumping one drops the
  // request.
  pure def isCurrentJob(st: State, p: Job): bool =
    p.gen == (if (p.kind == Test) st.testGen else st.verifyGen)

  // wizard-core.js state.testRunning: a current test email is pending.
  pure def testRunning(st: State): bool =
    st.pending.exists(p => p.kind == Test and p.handler == Test and isCurrentJob(st, p))

  // ---------------------------------------------------------------------
  // Helpers mirroring app.js functions
  // ---------------------------------------------------------------------

  // checkAuthStatus(): GET /auth/status, then the page shows the result.
  pure def checkAuthStatus(st: State): State = { ...st, authShown: st.signedIn }

  // POST /api/start-job, then streamEvents(...) attaches `handler`.
  pure def startJob(st: State, kind: Kind, gen: int): State = {
    val j = { id: st.nextJobId, kind: kind, handler: kind, version: st.version, gen: gen }
    { ...st,
      pending: st.pending.union(Set(j)),
      sessionJob: Set({ id: j.id, kind: kind, done: false }),
      nextJobId: st.nextJobId + 1,
    }
  }

  // state.resetTestAndVerify()
  pure def resetTestAndVerify(st: State): State =
    { ...st,
      testPassed: false, verifyPassed: false,
      btnNext4: false, btnNext5: false, verifyShown: false,
      // FIXED: bump generations so in-flight completions are ignored, and
      // let the user start a fresh test.
      testGen: if (FIXED) st.testGen + 1 else st.testGen,
      verifyGen: if (FIXED) st.verifyGen + 1 else st.verifyGen,
      btnSendTest: if (FIXED) true else st.btnSendTest,
    }

  // startVerify(), called on entry to step 5
  pure def startVerify(st: State): State = {
    val g = st.verifyGen + 1
    { ...startJob(st, Verify, g), verifyGen: g, verifyPassed: false, btnNext5: false, verifyShown: false }
  }

  // prepareSend(), called on entry to step 6
  pure def prepareSend(st: State): State =
    { ...st, sendStarted: false, btnDoSend: false, doneNav: false,
      // Bug: btn-back-6 is disabled by startSend() and never re-enabled.
      btnBack6: if (FIXED) true else st.btnBack6 }

  // goToStep(n). Forward guards that `return` early leave state unchanged.
  // Step 2 -> 3 waits for the recipient list: see next2 and previewResponse.
  // Every navigation bumps previewGen (checked only when FIXED).
  pure def goToStep(st0: State, n: int): State = {
    val st = { ...st0, previewGen: st0.previewGen + 1 }
    if (n > st.step) {
      if (n == 2 and not(st.dataLoaded)) st
      else if (n == 5 and not(st.testPassed)) st
      else if (n == 6 and not(st.verifyPassed)) st
      else {
        val st1 =
          if (n == 4) checkAuthStatus(st)
          else if (n == 5) startVerify(st)
          // FIXED: prepareSend() also refreshes the sign-in display.
          else if (n == 6) { if (FIXED) checkAuthStatus(prepareSend(st)) else prepareSend(st) }
          else st
        { ...st1, step: n }
      }
    } else { ...st, step: n }
  }

  // confirmGoBack(target); `accept` is the answer to the confirm() dialog.
  pure def confirmGoBack(st: State, target: int, accept: bool): State = {
    val needsConfirm = st.step >= 4 and (st.testPassed or st.verifyPassed)
    if (needsConfirm and not(accept)) st
    else {
      val st1 = if (needsConfirm) resetTestAndVerify(st) else st
      val st2 = if (st.step == 3 and target == 2) resetTestAndVerify(st1) else st1
      goToStep(st2, target)
    }
  }

  // Completion of job `j` (SSE "done" + /status) with outcome `ok`.
  pure def complete(st: State, j: Job, ok: bool): State = {
    val st0 = { ...st, pending: st.pending.exclude(Set(j)) }
    // Ghost: what the server actually did.
    val st1 = { ...st0,
      testedVersions: if (ok and j.kind == Test) st0.testedVersions.union(Set(j.version)) else st0.testedVersions,
      verifiedVersions: if (ok and j.kind == Verify) st0.verifiedVersions.union(Set(j.version)) else st0.verifiedVersions,
    }
    match j.handler {
      | Test =>
        if (FIXED and j.gen != st1.testGen) st1
        else if (ok) { ...st1, btnSendTest: true, testPassed: true, btnNext4: true }
        // FIXED: a failed test refreshes the sign-in display, so a test that
        // failed for want of a token shows the sign-in callout.
        else if (FIXED) checkAuthStatus({ ...st1, btnSendTest: true })
        else { ...st1, btnSendTest: true }
      | Verify =>
        if (FIXED and j.gen != st1.verifyGen) st1
        else if (ok) { ...st1, verifyPassed: true, btnNext5: true, verifyShown: true }
        else { ...st1, verifyShown: true }
      // Completed or stopped: fetchAndShowSendResults() shows the table.
      // Bug: a failed send only shows the error (showSendResult), and the
      // job kept no results to show. FIXED2: the job keeps the results so far
      // and the page shows them with the error.
      | Send => { ...st1, doneNav: true,
          resultsShown: ok or (FIXED2 and st1.sendJob.exists(sj => sj.id == j.id and sj.sent > 0)) }
    }
  }

  pure def markSessionJobDone(st: State, id: int): State =
    { ...st, sessionJob: st.sessionJob.map(sj => if (sj.id == id) { ...sj, done: true } else sj) }

  // ---------------------------------------------------------------------
  // Actions
  //
  // Each action names the code it transcribes. `buggy` transcribes the code
  // as it was, faults included; intended behaviour goes only in `fixed`.
  // Every entry point in the UI and server maps to one of these or is
  // excluded with a reason in spec/coverage.toml (tests/test_spec_coverage.py).
  // ---------------------------------------------------------------------

  action init = all { s' = init_state, lastAction' = "init" }

  action act(name: str, st: State): bool = all { s' = st, lastAction' = name }

  // Step 1: upload or change sheet
  // app.js: #spreadsheet-file change, #sheet-select change; web/app.py: api_upload_spreadsheet, api_change_sheet
  // The new data replaces state.spreadsheetData, so the filtered recipient
  // list is gone until the next preview.
  action upload = all { s.step == 1, act("upload", { ...s, dataLoaded: true, version: s.version + 1,
    recipientsVersion: -1, previewGen: s.previewGen + 1 }) }
  // app.js: goToStep(2) (#btn-next-1)
  action next1 = all { s.step == 1, act("next1", goToStep(s, 2)) }

  // Step 2: edit any compose field. `bcc`: the field is #bcc-blast-to.
  // Editing bumps previewGen (checked only when FIXED).
  // app.js: onTemplateChange() and the compose input listeners, setSendMode()
  action edit(bcc: bool): bool = all { s.step == 2, act("edit", { ...s, version: s.version + 1,
    previewGen: s.previewGen + 1,
    bccToMerge: if (bcc) s.mergeId else s.bccToMerge }) }
  // app.js: goToStep(1) (step 2 Back)
  action back2 = all { s.step == 2, act("back2", goToStep(s, 1)) }
  // goToStep(3) awaits loadPreview(), which disables Next and posts the
  // current filters to /api/get-recipients.
  // app.js: goToStep(3) (#btn-next-2), loadPreview(); web/app.py: api_get_recipients
  action next2 = all {
    s.step == 2, s.btnNext2,
    val g = s.previewGen + 1
    act("next2", { ...s, btnNext2: false, previewGen: g,
      previewReq: s.previewReq.union(Set({ version: s.version, gen: g })) }),
  }

  // The recipient list arrives (`ok`) or the request fails (an alert). Next
  // is re-enabled either way.
  // Bug: loadPreview() writes the list into whatever state.spreadsheetData
  // now is, and goToStep() then sets step 3 wherever the page is, so a Back,
  // an edit or a new upload while waiting is overridden.
  // FIXED2: a response whose preview generation is stale is dropped.
  // environment: app.js loadPreview() and goToStep(3) after `await`; web/app.py api_get_recipients
  action previewResponse(ok: bool): bool = all {
    s.previewReq.size() > 0,
    nondet r = s.previewReq.oneOf()
    val st = { ...s, previewReq: s.previewReq.exclude(Set(r)), btnNext2: true }
    val current = not(FIXED2) or (r.gen == s.previewGen and s.step == 2)
    act("previewResponse",
      if (ok and current)
        { ...st, recipientsVersion: r.version, step: 3,
          stepJump: s.stepJump or s.step != 2 }
      else st),
  }

  // Step 3
  // app.js: confirmGoBack(2) (step 3 Back)
  action back3 = all { s.step == 3, act("back3", confirmGoBack(s, 2, true)) }
  // app.js: goToStep(4) (#btn-next-3)
  action next3 = all { s.step == 3, act("next3", goToStep(s, 4)) }

  // Step 4
  // app.js: sendTestEmail() (#btn-send-test, #btn-retry-test); web/app.py: api_start_job (mode test_email)
  action sendTestEmail = all {
    s.step == 4, sendTestEnabled(s),
    val g = s.testGen + 1
    act("sendTestEmail", { ...startJob(s, Test, g),
      testGen: g, testPassed: false, btnSendTest: false,
      mailSignedOut: s.mailSignedOut or not(s.authShown),
      // Bug: btn-next-4 stays enabled while testPassed is false.
      btnNext4: if (FIXED) false else s.btnNext4 }),
  }
  // app.js: confirmGoBack(3) (step 4 Back)
  action back4(accept: bool): bool = all { s.step == 4, act("back4", confirmGoBack(s, 3, accept)) }
  // app.js: goToStep(5) (#btn-next-4), startVerify(); web/app.py: api_start_job (mode dry_run)
  action next4 = all { s.step == 4, s.btnNext4, act("next4", goToStep(s, 5)) }

  // Step 5
  // app.js: confirmGoBack(4) (step 5 Back)
  action back5(accept: bool): bool = all { s.step == 5, act("back5", confirmGoBack(s, 4, accept)) }
  // app.js: goToStep(6) (#btn-next-5), prepareSend()
  action next5 = all { s.step == 5, s.btnNext5, act("next5", goToStep(s, 6)) }

  // Step 6
  // app.js: #send-confirm-input input listener
  action typeSend = all {
    s.step == 6, not(s.sendStarted),
    act("typeSend", { ...s, btnDoSend: true }),
  }
  // startSend() switches to the sending screen and awaits POST
  // /api/start-job. The server creates the job and its thread at once; the
  // session cookie naming the job and the page's callback only arrive with
  // the response (startSendResponse).
  // Bug: progress text from an earlier send stays until the first log line.
  // FIXED2: startSend() resets it.
  // app.js: startSend() (#btn-do-send); web/app.py: api_start_job (mode send)
  action startSend = all {
    s.step == 6, not(s.sendStarted), doSendEnabled(s),
    val ok = s.testedVersions.contains(s.version) and s.verifiedVersions.contains(s.version)
    act("startSend", { ...s,
      sendStarted: true, btnBack6: false, btnDoSend: false, resultsShown: false,
      progressJob: if (FIXED2) -1 else s.progressJob,
      stopQueued: false,
      sendReq: Set(s.nextJobId), nextJobId: s.nextJobId + 1,
      sendJob: Set({ id: s.nextJobId, sent: 0, stopRequested: false, status: Running, stopEarly: false }),
      concurrentSends: s.concurrentSends or s.sendJob.exists(j => j.status == Running),
      realSendStarted: true, untestedSend: s.untestedSend or not(ok),
      mailSignedOut: s.mailSignedOut or not(s.authShown) }),
  }

  // The start-job response: the session now names the job, and
  // streamEvents() attaches the send callback. A job that has already
  // finished (a token failure can end it at once) delivers its queued
  // events, so the callback fires straight away.
  // FIXED2: a Stop pressed while waiting is sent now.
  // environment: app.js startSend() after `await`; web/app.py api_start_job response
  action startSendResponse = all {
    s.sendReq.size() > 0,
    nondet id = s.sendReq.oneOf()
    val done = s.sendJob.exists(j => j.id == id and j.status != Running)
    val job = { id: id, kind: Send, handler: Send, version: s.version, gen: 0 }
    val st1 = { ...s, sendReq: Set(), sessionJob: Set({ id: id, kind: Send, done: done }) }
    val st2 =
      if (FIXED2 and s.stopQueued) { ...st1, stopQueued: false,
        sendJob: st1.sendJob.map(j => if (j.id == id and j.status == Running)
          { ...j, stopRequested: true, stopEarly: j.stopEarly or j.sent < TOTAL } else j) }
      else st1
    val failed = s.sendJob.exists(j => j.id == id and j.status == Failed)
    act("startSendResponse",
      if (done) complete({ ...st2, pending: st2.pending.union(Set(job)) }, job, not(failed))
      else { ...st2, pending: st2.pending.union(Set(job)) }),
  }
  // app.js: confirmGoBack(4) (#btn-back-6)
  action back6(accept: bool): bool = all {
    s.step == 6, not(s.sendStarted), s.btnBack6,
    act("back6", confirmGoBack(s, 4, accept)),
  }

  // "Stop sending" is inside #send-progress, shown from startSend() until the
  // results replace it. It posts to state.currentJobId.
  // Bug: until the start-job response arrives, currentJobId is still the dry
  // run's id, so a Stop pressed then reaches no send.
  // FIXED2: the page remembers it and posts it once the job id is known.
  // app.js: stopSend() (#btn-stop-send); web/app.py: api_job_stop
  action stopSend = all {
    s.step == 6, s.sendStarted, not(s.doneNav),
    act("stopSend",
      if (s.sendReq.size() > 0) {
        if (FIXED2) { ...s, stopQueued: true }
        else { ...s, stopLost: s.stopLost or s.sendJob.exists(j => j.status == Running) }
      } else { ...s,
        sendJob: s.sendJob.map(j =>
          if (j.status == Running)
            { ...j, stopRequested: true, stopEarly: j.stopEarly or j.sent < TOTAL }
          else j) }),
  }

  // newMerge() — only reachable from send-done-nav
  // app.js: newMerge() (#btn-new-merge); web/app.py: api_reset
  // Bug: #bcc-blast-to keeps the previous merge's address. FIXED2: cleared.
  action newMerge = all {
    s.step == 6, s.doneNav,
    act("newMerge", { ...resetTestAndVerify(s),
      step: 1, dataLoaded: false, version: s.version + 1,
      sendStarted: false, btnDoSend: false, doneNav: false, resultsShown: false,
      recipientsVersion: -1, mergeId: s.mergeId + 1,
      bccToMerge: if (FIXED2) -1 else s.bccToMerge,
      sessionJob: Set(),  // POST /api/reset pops job_id
    }),
  }
  // Dismiss the interrupted-send report: the log is deleted.
  // app.js: dismissInterrupted() (#btn-dismiss-interrupted); web/app.py: api_dismiss_interrupted
  action dismissInterrupted = all {
    s.step == 1, s.interruptedShown,
    act("dismissInterrupted", { ...s, sendLog: Set(), interruptedShown: false }),
  }


  // A test email needs a token. Without one, the job's token provider
  // (web/app.py _make_token_provider) calls auth.acquire_token(), which falls
  // back to the device-code flow: the prompt goes to the job log and the
  // job blocks until the code expires, then fails.
  // FIXED: the provider is silent-only and fails at once.
  pure def finishJob(st: State, j: Job, ok: bool): State = {
    val noToken = j.kind == Test and not(st.signedIn)
    val st1 = { ...st,
      interactiveAuthInJob: st.interactiveAuthInJob or (noToken and not(FIXED)) }
    markSessionJobDone(complete(st1, j, ok and not(noToken)), j.id)
  }

  // The server finishes a test or dry-run job; the page's callback (if any)
  // fires. Send jobs finish through the send loop below instead.
  // environment: web/app.py api_start_job._run_job; app.js streamEvents() completion
  action completeJob(ok: bool): bool = all {
    s.pending.exists(p => p.kind != Send),
    nondet j = s.pending.filter(p => p.kind != Send).oneOf()
    act("complete", finishJob(s, j, ok)),
  }

  // Deterministic completion of a specific job, for scenario tests.
  action completeById(id: int, ok: bool): bool = all {
    s.pending.exists(p => p.id == id and p.kind != Send),
    nondet j = s.pending.filter(p => p.id == id).oneOf()
    act("complete", finishJob(s, j, ok)),
  }

  // The server finishes the session's test or dry-run job with nobody
  // listening (its page was reloaded away).
  // environment: web/app.py api_start_job._run_job
  action completeOrphan = all {
    s.sessionJob.exists(sj => not(sj.done) and sj.kind != Send and s.pending.forall(p => p.id != sj.id)),
    nondet sj = s.sessionJob.oneOf()
    act("completeOrphan", markSessionJobDone({ ...s,
      interactiveAuthInJob: s.interactiveAuthInJob
        or (sj.kind == Test and not(s.signedIn) and not(FIXED)) }, sj.id)),
  }

  // One iteration of the send loop: send_one() for the next recipient.
  // Bug: neither loop reads job.stop_requested, so Stop does nothing.
  // FIXED: the loop checks the job's should_stop() before each email.
  // environment: sender.py send_all() / send_bcc_blast() loop body
  action sendNext = all {
    s.signedIn,
    s.sendJob.exists(j => j.status == Running and j.sent < TOTAL
      and (not(FIXED) or not(j.stopRequested))),
    nondet j = s.sendJob.oneOf()
    act("sendNext", { ...s,
      sendJob: Set({ ...j, sent: j.sent + 1 }),
      // The "Sending [i/n]" log line updates the progress text if the page
      // is listening to this job.
      progressJob: if (s.pending.exists(p => p.id == j.id and p.handler == Send)) j.id else s.progressJob,
      sentAfterStop: if (j.stopRequested) s.sentAfterStop + 1 else s.sentAfterStop,
      // Unreachable while the guard above holds; kept so that relaxing it
      // shows up in signedInBeforeMail.
      mailSignedOut: s.mailSignedOut or not(s.signedIn) }),
  }

  // The send job's thread ends: the loop ran out of recipients, stopped
  // early (FIXED only), or send_merge() raised. The page's send callback, if
  // one is attached, then fetches the status and shows the results.
  // environment: web/app.py api_start_job._run_job; app.js streamEvents() completion
  action finishSend(failed: bool): bool = all {
    s.sendJob.exists(j => j.status == Running
      and (failed or j.sent == TOTAL or (FIXED and j.stopRequested))),
    nondet j = s.sendJob.oneOf()
    act("finishSend", finishSendJob(s, j, failed)),
  }

  pure def finishSendJob(st: State, j: SendJob, failed: bool): State = {
    val status = if (failed) Failed else if (j.sent == TOTAL) Completed else Stopped
    val st1 = { ...st, sendJob: Set({ ...j, status: status }) }
    val st2 = st.pending.filter(p => p.id == j.id).fold(st1, (acc, p) => complete(acc, p, not(failed)))
    markSessionJobDone(st2, j.id)
  }

  // The send loop needs a token for the next email and the cache has none.
  // Bug: the token provider falls into the device-code flow and the job
  // blocks (it fails later, through finishSend, when the code expires).
  // FIXED: the provider raises at once and the job fails.
  // environment: sender.py send_one() -> get_token(); web/app.py _make_token_provider
  action sendWithoutToken = all {
    not(s.signedIn),
    s.sendJob.exists(j => j.status == Running and j.sent < TOTAL
      and (not(FIXED) or not(j.stopRequested))),
    nondet j = s.sendJob.oneOf()
    act("sendWithoutToken",
      if (FIXED) finishSendJob(s, j, true)
      else { ...s, interactiveAuthInJob: true }),
  }

  // Sign in. Browser mode redirects to Microsoft and back, which reloads the
  // page; desktop mode starts the system-browser flow and polls /auth/status
  // until it finishes. Only the successful outcome is modelled: a cancelled
  // or failed sign-in leaves the state as it was.
  // app.js: #btn-sign-in click (signed out), the sign-in poll timer; FIXED also #btn-sign-in-4, #btn-sign-in-6;
  // web/app.py: auth_login, auth_callback, auth_interactive, auth_status
  action signIn(desktop: bool): bool = all {
    signInOffered(s), not(s.authShown),
    act("signIn",
      if (desktop) { ...s, signedIn: true, authShown: true }
      else reloadState({ ...s, signedIn: true })),
  }

  // app.js: #btn-sign-in click (signed in), doSignOut(); web/app.py: auth_logout
  action signOut = all {
    s.step == 1, s.authShown,
    act("signOut", { ...s, signedIn: false, authShown: false }),
  }

  // The server process ends mid-session: the desktop app is quit or crashes,
  // or the terminal running mergemail365-web is closed. Running jobs die
  // with it; the token cache and the emails already sent remain. The user
  // starts again from a new page with a new startup token and session.
  // Bug: the record of a running send's emails is lost with it (R15).
  // FIXED2: a running send's log on disk survives, and the new page reports
  // it until dismissed.
  // environment: process exit (web/__init__.py main)
  action serverRestart = {
    val logged = if (FIXED2) s.sendLog.union(
      s.sendJob.filter(j => j.status == Running).map(j => { id: j.id, sent: j.sent })) else Set()
    act("serverRestart", { ...init_state,
    signedIn: s.signedIn, authShown: s.signedIn,
    nextJobId: s.nextJobId, version: s.version + 1, mergeId: s.mergeId + 1,
    sendLog: logged, interruptedShown: logged.size() > 0,
    sendJob: s.sendJob.map(j => if (j.status == Running) { ...j, status: Killed } else j),
    testedVersions: s.testedVersions, verifiedVersions: s.verifiedVersions,
    realSendStarted: s.realSendStarted, untestedSend: s.untestedSend,
    sentAfterStop: s.sentAfterStop, interactiveAuthInJob: s.interactiveAuthInJob,
    stepJump: s.stepJump, concurrentSends: s.concurrentSends, stopLost: s.stopLost,
    lostSend: s.lostSend or (not(FIXED2) and s.sendJob.exists(j => j.status == Running and j.sent > 0)),
  })
  }

  // The cached token stops working: no usable refresh token, consent
  // revoked, or a sign-out from another window or the CLI. The page keeps
  // showing what it last fetched.
  // environment: MSAL token cache (auth.py)
  action tokenExpires = all {
    s.signedIn,
    act("tokenExpires", { ...s, signedIn: false }),
  }

  // Page reload: JS memory and DOM reset; session, temp files, localStorage,
  // the token cache and server jobs survive. loadConfig() and
  // checkAuthStatus() then run.
  // app.js: DOMContentLoaded, loadConfig(); web/app.py: api_config
  action reload = act("reload", reloadState(s))

  pure def reloadState(st: State): State = {
    val fresh = { ...init_state,
      dataLoaded: st.dataLoaded, version: st.version,
      sessionJob: st.sessionJob, nextJobId: st.nextJobId, sendJob: st.sendJob,
      sendLog: st.sendLog, interruptedShown: st.sendLog.size() > 0,
      testGen: st.testGen, verifyGen: st.verifyGen,
      signedIn: st.signedIn, authShown: st.signedIn,
      testedVersions: st.testedVersions, verifiedVersions: st.verifiedVersions,
      realSendStarted: st.realSendStarted, untestedSend: st.untestedSend,
      sentAfterStop: st.sentAfterStop, interactiveAuthInJob: st.interactiveAuthInJob,
      stepJump: st.stepJump, concurrentSends: st.concurrentSends, mergeId: st.mergeId,
      lostSend: st.lostSend, stopLost: st.stopLost,
    }
    // Bug: /api/config reports session["job_id"] as active whenever it is
    // still in _jobs, whatever its mode and even if it has finished; and only
    // that job, so a send whose start-job response never reached the page
    // (and so never set the session cookie) runs unseen.
    // FIXED: only send jobs. FIXED2: and a running send job even if the
    // session doesn't name it (the app has one user).
    val running = st.sendJob.filter(j => j.status == Running)
      .map(j => { id: j.id, kind: Send, done: false })
    val active =
      if (FIXED2 and running.size() > 0) running
      else if (FIXED) st.sessionJob.filter(sj => sj.kind == Send)
      else st.sessionJob
    val after =
      if (active.size() == 0) fresh
      else {
        val sj = active.fold(
          { id: -1, kind: Send, done: false }, (acc, x) => x)
        val reconnected = { ...fresh,
          step: 6, sendStarted: true, btnBack6: false, doneNav: false }
        if (sj.done) {
          // Bug: the job's event queue was drained by the previous page,
          // so the new SSE stream only gets keepalives and never "done".
          // FIXED: the server ends the stream of a finished job with an
          // empty queue, so the page fetches and shows the results.
          if (FIXED) { ...reconnected, doneNav: true,
            resultsShown: st.sendJob.exists(j => j.id == sj.id and (j.status != Failed or (FIXED2 and j.sent > 0))) }
          else reconnected
        } else {
          // Reattach the send-step callback to whatever job this is.
          { ...reconnected, pending: Set({
              id: sj.id, kind: sj.kind, handler: Send, version: st.version, gen: 0 }) }
        }
      }
    after
  }

  action step = any {
    upload, next1, nondet bcc = Bool.oneOf() edit(bcc), back2, next2,
    nondet ok = Bool.oneOf() previewResponse(ok), back3, next3,
    sendTestEmail, nondet a = Bool.oneOf() back4(a), next4,
    nondet a = Bool.oneOf() back5(a), next5,
    typeSend, startSend, startSendResponse, nondet a = Bool.oneOf() back6(a), stopSend, newMerge,
    dismissInterrupted,
    nondet ok = Bool.oneOf() completeJob(ok),
    completeOrphan,
    sendNext, nondet failed = Bool.oneOf() finishSend(failed), sendWithoutToken,
    nondet desktop = Bool.oneOf() signIn(desktop), signOut, tokenExpires,
    reload, serverRestart,
  }


  // ---------------------------------------------------------------------
  // Invariants
  // ---------------------------------------------------------------------

  /// A real send only starts for content that was test-sent and dry-run.
  val noUntestedSend = not(s.untestedSend)

  /// Next on step 4 (when it actually advances) means the current content was test-sent.
  val next4Honest =
    (s.step == 4 and s.btnNext4 and s.testPassed) implies s.testedVersions.contains(s.version)

  /// Next on step 5 (when it actually advances) means the current content was dry-run.
  val next5Honest =
    (s.step == 5 and s.btnNext5 and s.verifyPassed) implies s.verifiedVersions.contains(s.version)

  /// An enabled Next button does something.
  val buttonsMatchFlags =
    (s.step == 4 implies s.btnNext4 == s.testPassed)
    and (s.step == 5 implies s.btnNext5 == s.verifyPassed)

  /// FIXED2: the buttons are functions of the workflow state, as
  /// wizard-core.js computes them (nextEnabled, sendTestEnabled,
  /// back6Enabled), so the separate btn* fields add nothing. They stay in the
  /// model as the record of bugs 5, 6 and 14 in `buggy` and `partial`.
  val buttonsDerived = FIXED2 implies and {
    s.btnNext4 == s.testPassed,
    s.btnNext5 == s.verifyPassed,
    s.btnSendTest == not(testRunning(s)),
    s.step == 6 implies s.btnBack6 == not(s.sendStarted),
  }

  /// Before sending, the user can always go back from step 6.
  val back6Usable = (s.step == 6 and not(s.sendStarted)) implies s.btnBack6

  /// The "sending" screen only appears for a real send.
  val sendScreenHonest = (s.step == 6 and s.sendStarted) implies s.realSendStarted

  /// The sending screen always eventually offers a way out: the start-job
  /// response or a callback is pending, or the done navigation is shown.
  val sendScreenNotStuck =
    (s.step == 6 and s.sendStarted)
      implies (s.doneNav or s.sendReq.size() > 0 or s.pending.exists(p => p.handler == Send))

  val stepNeedsData = s.step >= 2 implies s.dataLoaded

  /// No email is sent after Stop is pressed. An email already being sent when
  /// Stop is pressed counts as sent before it, because sendNext is atomic.
  /// A Stop pressed before the start-job response arrives still stops it.
  val stopHonoured = s.sentAfterStop == 0 and not(s.stopLost)

  /// A send stopped while emails remained ends as Stopped (unless it failed),
  /// never as Completed.
  val stoppedReported = s.sendJob.forall(j => not(j.stopEarly and j.status == Completed))

  /// On step 4, while the page shows signed out, "Send test email" is
  /// disabled and the sign-in button is offered on the step.
  val testNeedsSignIn =
    (s.step == 4 and not(s.authShown)) implies (not(sendTestEnabled(s)) and signInOffered(s))

  /// "Send emails" can only be clicked while the page shows signed in, and
  /// step 6 offers sign-in before sending while it shows signed out.
  val sendNeedsSignIn =
    (s.step == 6 and not(s.sendStarted))
      implies ((doSendEnabled(s) implies s.authShown) and (s.authShown or signInOffered(s)))

  /// No email is attempted before the user has signed in: a test email or a
  /// send only starts while the page shows signed in, and each email the
  /// send loop sends goes out with a usable token. (A token that runs out
  /// after the click is allowed: the job then fails before its first email,
  /// see noInteractiveAuthInJob and the staleSignIn witness.)
  val signedInBeforeMail = not(s.mailSignedOut)

  /// No web job ever waits for interactive sign-in input.
  val noInteractiveAuthInJob = not(s.interactiveAuthInJob)

  /// Dead-end check, from the same guards the actions use: on steps 4 and 6
  /// the user can finish the step from the step itself, without going back.
  /// Steps 1-3 always offer their forward action; a failed dry run on step 5
  /// is fixed upstream (the content is wrong), so Back is the right way out.
  val canProgress =
    (s.step == 4 implies (
        s.pending.exists(p => p.handler == Test)
        or (s.btnNext4 and s.testPassed)
        or (sendTestEnabled(s) and s.authShown)
        or signInOffered(s)))
    and (s.step == 5 implies (s.pending.exists(p => p.handler == Verify) or s.verifyShown))
    and ((s.step == 6 and not(s.sendStarted)) implies (s.authShown or signInOffered(s)))

  /// The page only moves where the user last sent it: a response to an
  /// earlier request never moves it from a step the user has since left.
  val noStepJump = not(s.stepJump)

  /// The recipients shown on steps 3 to 6 were fetched for the current content.
  val previewHonest = (s.step >= 3 and not(s.sendStarted)) implies s.recipientsVersion == s.version

  /// A running send is always on screen, and there is only one at a time.
  val runningSendVisible =
    s.sendJob.exists(j => j.status == Running) implies (s.step == 6 and s.sendStarted)
  val noConcurrentSends = not(s.concurrentSends)

  /// After a send ends, the page lists which emails went out, even if it
  /// failed part-way.
  val failedSendReported =
    (s.step == 6 and s.doneNav) implies (s.resultsShown or s.sendJob.forall(j => j.sent == 0))

  /// The progress text describes the send under way.
  val progressHonest =
    (s.step == 6 and s.sendStarted and s.progressJob >= 0)
      implies s.sendJob.exists(j => j.id == s.progressJob)

  /// New merge clears every input the previous merge filled in.
  val newMergeClears = s.bccToMerge < 0 or s.bccToMerge == s.mergeId

  val allInvariants = and {
    noUntestedSend, next4Honest, next5Honest, buttonsMatchFlags,
    back6Usable, sendScreenHonest, sendScreenNotStuck, stepNeedsData,
    stopHonoured, stoppedReported,
    testNeedsSignIn, sendNeedsSignIn, noInteractiveAuthInJob, canProgress,
    noStepJump, previewHonest, runningSendVisible, noConcurrentSends,
    failedSendReported, progressHonest, newMergeClears, buttonsDerived,
    restartReported, interruptedVisible, signedInBeforeMail,
  }

  // ---------------------------------------------------------------------
  // Witnesses (quint run --witnesses): states that are allowed but worth a
  // look. spec/requirements.md records how often each is reached and why it
  // is acceptable.
  // ---------------------------------------------------------------------

  /// The page shows signed in on step 4 or 6, but the token is gone.
  val staleSignIn = (s.step == 4 or s.step == 6) and s.authShown and not(s.signedIn)

  /// A job is running on the server with no page listening for it.
  val orphanJob = s.sessionJob.exists(sj => not(sj.done) and s.pending.forall(p => p.id != sj.id))

  /// A send failed after some emails went out.
  val partialFailedSend = s.sendJob.exists(j => j.status == Failed and j.sent > 0)

  /// A server restart killed a send after some emails went out: nothing
  /// records which.
  val restartLostSend = s.lostSend

  /// A server restart never loses the record of a send's emails (R15):
  /// a running send's log on disk survives it (FIXED2).
  val restartReported = not(s.lostSend)

  /// While an interrupted send's log is on disk, the page reports it.
  val interruptedVisible = s.sendLog.size() > 0 implies s.interruptedShown

  // ---------------------------------------------------------------------
  // Scenarios (quint test). Each replays one counterexample; the invariant
  // must fail in the buggy model and hold in the fixed one. Job ids are
  // assigned in start order from 0.
  // ---------------------------------------------------------------------

  pure def bugIff(inv: bool): bool = if (FIXED) inv else not(inv)

  // For round 2 bugs, which are present in both `buggy` and `partial`.
  pure def bugIff2(inv: bool): bool = if (FIXED2) inv else not(inv)

  // Next on step 2, and the recipient list arrives.
  action preview = next2.then(previewResponse(true))

  // "Send emails", and the start-job response arrives.
  action send = startSend.then(startSendResponse)

  action toStep4 = upload.then(next1).then(preview).then(next3)

  // Start signed in (desktop sign-in on step 1).
  action start = init.then(signIn(true))

  // The send loop sends every email, then the job finishes.
  action sendAll = sendNext.then(sendNext).then(sendNext).then(finishSend(false))

  action passTestAndVerify(testId: int): bool =
    sendTestEmail.then(completeById(testId, true))
      .then(next4).then(completeById(testId + 1, true))

  run happyPathTest =
    start.then(toStep4).then(passTestAndVerify(0))
      .then(next5).then(typeSend).then(send).then(sendAll)
      .expect(allInvariants and s.doneNav)

  /// A test that completes after the user went back and edited enables Next.
  run staleTestCompletionTest =
    start.then(toStep4).then(sendTestEmail).then(back4(true)).then(back3)
      .then(completeById(0, true)).then(edit(false)).then(preview).then(next3)
      .expect(bugIff(next4Honest))

  /// An old dry run completing during a newer one enables Next on step 5.
  run staleVerifyCompletionTest =
    start.then(toStep4).then(sendTestEmail).then(completeById(0, true))
      .then(next4)                                   // dry run 1 starts
      .then(back5(true)).then(back4(true)).then(back3).then(edit(false))
      .then(preview).then(next3).then(sendTestEmail).then(completeById(2, true))
      .then(next4)                                   // dry run 3 starts
      .then(completeById(1, true))                   // stale dry run 1 finishes
      .expect(bugIff(next5Honest))

  /// Re-sending a test leaves Next enabled while testPassed is false.
  run retestLeavesNextEnabledTest =
    start.then(toStep4).then(sendTestEmail).then(completeById(0, true)).then(sendTestEmail)
      .expect(bugIff(buttonsMatchFlags))

  /// Reloading during a test email jumps to the Send step.
  run reloadDuringTestTest =
    start.then(toStep4).then(sendTestEmail).then(reload)
      .expect(bugIff(sendScreenHonest))

  /// Reloading after a test email finished leaves the page stuck on "Sending".
  run reloadAfterTestTest =
    start.then(toStep4).then(sendTestEmail).then(completeById(0, true)).then(reload)
      .expect(bugIff(sendScreenNotStuck))

  /// Reloading after a real send finished also gets stuck.
  run reloadAfterSendTest =
    start.then(toStep4).then(passTestAndVerify(0))
      .then(next5).then(typeSend).then(send).then(sendAll)
      .then(reload)
      .expect(bugIff(sendScreenNotStuck))

  /// Stop sending does nothing: the loop keeps sending (bug 7). Fixed: the
  /// loop stops before the next email and the job ends as Stopped.
  run stopIgnoredTest =
    start.then(toStep4).then(passTestAndVerify(0))
      .then(next5).then(typeSend).then(send).then(sendNext).then(stopSend)
      .then(any { all { FIXED, finishSend(false) }, all { not(FIXED), sendNext } })
      .expect(bugIff(stopHonoured)
        and (FIXED implies (s.doneNav and s.sendJob.forall(j => j.status == Stopped and j.sent == 1))))

  /// A stopped send reports Completed once every email has gone out.
  run stoppedReportedTest =
    start.then(toStep4).then(passTestAndVerify(0))
      .then(next5).then(typeSend).then(send).then(stopSend)
      .then(any { all { FIXED, finishSend(false) }, all { not(FIXED), sendAll } })
      .expect(bugIff(stoppedReported))

  /// A signed-out user reaches step 4 with no way to sign in there (bug 8).
  run signedOutStep4Test =
    init.then(toStep4)
      .expect(bugIff(testNeedsSignIn and canProgress))

  /// Fixed: signing in from the step 4 callout enables the test email.
  run signInOnStep4Test =
    init.then(toStep4)
      .then(any { all { FIXED, signIn(true) }, all { not(FIXED), back4(true).then(back3).then(back2).then(signIn(true)).then(next1).then(preview).then(next3) } })
      .expect(s.step == 4 and sendTestEnabled(s) and allInvariants)

  /// A test email sent after the token expired waits in the device-code
  /// flow (bug 9). Fixed: it fails at once and the page offers sign-in.
  run testWithoutTokenTest =
    start.then(toStep4).then(tokenExpires).then(sendTestEmail).then(completeById(0, true))
      .expect(bugIff(noInteractiveAuthInJob)
        and not(s.testPassed)
        and (FIXED implies (signInOffered(s) and not(sendTestEnabled(s)))))

  /// A send whose token expires mid-way waits in the device-code flow.
  /// Fixed: the job fails at once.
  run sendWithoutTokenTest =
    start.then(toStep4).then(passTestAndVerify(0))
      .then(next5).then(typeSend).then(send).then(sendNext).then(tokenExpires)
      .then(sendWithoutToken)
      .expect(bugIff(noInteractiveAuthInJob)
        and (FIXED implies (s.doneNav and s.sendJob.forall(j => j.status == Failed))))

  /// Signed out, a test email can be started on step 4 (bug 8). Fixed: it
  /// can't be clicked until the user signs in from the step.
  run mailBeforeSignInTest =
    init.then(toStep4)
      .expect(FIXED implies not(sendTestEnabled(s)))
      .then(if (FIXED) signIn(true).then(sendTestEmail) else sendTestEmail)
      .expect(bugIff(signedInBeforeMail))

  /// The token runs out after the page last checked it, and the user starts
  /// the send: allowed, because the page showed signed in, but no email goes
  /// out (fixed: the job fails at once).
  run tokenExpiresBeforeSendTest =
    start.then(toStep4).then(passTestAndVerify(0))
      .then(next5).then(typeSend).then(tokenExpires).then(send)
      .then(sendWithoutToken)
      .expect(signedInBeforeMail and s.sendJob.forall(j => j.sent == 0)
        and (FIXED implies (allInvariants and s.doneNav)))

  /// Vacuity: reaches the actions no other scenario takes, so a guard that
  /// can never be true is caught. completeOrphan is only reachable in fixed:
  /// the buggy reload reattaches every unfinished job.
  run remainingActionsTest =
    start.then(toStep4).then(passTestAndVerify(0)).then(next5)
      .then(back6(false)).then(back6(true))
      .then(sendTestEmail).then(completeJob(true))
      .then(back4(true)).then(back3).then(back2).then(signOut).then(signIn(true))
      .then(next1).then(preview).then(next3).then(sendTestEmail)
      .then(any { all { FIXED, reload.then(completeOrphan) }, all { not(FIXED), reload } })
      .expect(FIXED implies (s.step == 1 and allInvariants))

  /// Back while the recipient preview loads: the page still jumps to step 3
  /// when the list arrives (bug 10).
  run previewJumpTest =
    start.then(upload).then(next1).then(next2).then(back2).then(previewResponse(true))
      .expect(bugIff2(noStepJump) and (FIXED2 implies (s.step == 1 and s.btnNext2)))

  /// Editing (or re-uploading) while the preview loads: the list shown is
  /// for the old content (bug 10).
  run previewStaleTest =
    start.then(upload).then(next1).then(next2).then(edit(false)).then(previewResponse(true))
      .expect(bugIff2(previewHonest) and (FIXED2 implies (s.step == 2 and s.btnNext2)))

  /// A reload before the start-job response arrives leaves the send running
  /// unseen (bug 11). In `buggy` the old reload bug (bug 3) masks it: the page
  /// reattaches to the finished dry run and shows "Sending…".
  run sendUnseenAfterReloadTest =
    start.then(toStep4).then(passTestAndVerify(0))
      .then(next5).then(typeSend).then(startSend).then(reload)
      .expect(if (FIXED2) runningSendVisible else if (FIXED) not(runningSendVisible) else true)

  /// Stop pressed before the start-job response arrives is lost (bug 12).
  run earlyStopTest =
    start.then(toStep4).then(passTestAndVerify(0))
      .then(next5).then(typeSend).then(startSend).then(stopSend).then(startSendResponse)
      .expect(bugIff2(stopHonoured)
        and (FIXED2 implies s.sendJob.forall(j => j.stopRequested)))

  /// A send that fails part-way shows only the error, not which emails went
  /// out (bug 13).
  run failedSendTest =
    start.then(toStep4).then(passTestAndVerify(0))
      .then(next5).then(typeSend).then(send).then(sendNext).then(finishSend(true))
      .expect(bugIff2(failedSendReported))

  /// The second send's progress text starts with the first send's count
  /// (bug 14).
  run staleProgressTest =
    start.then(toStep4).then(passTestAndVerify(0))
      .then(next5).then(typeSend).then(send).then(sendAll)
      .then(newMerge).then(toStep4).then(passTestAndVerify(3))
      .then(next5).then(typeSend).then(startSend)
      .expect(bugIff2(progressHonest))

  /// New merge leaves the BCC To address in place (bug 15).
  run bccToLeftTest =
    start.then(upload).then(next1).then(edit(true)).then(preview).then(next3)
      .then(passTestAndVerify(0))
      .then(next5).then(typeSend).then(send).then(sendAll).then(newMerge)
      .expect(bugIff2(newMergeClears))

  /// Restarting the server mid-send loses the record of what went out
  /// (R15). FIXED2: the send log reports it on the new page until dismissed.
  run restartMidSendTest =
    start.then(toStep4).then(passTestAndVerify(0))
      .then(next5).then(typeSend).then(send).then(sendNext).then(serverRestart)
      .expect(bugIff2(restartReported) and s.step == 1
        and (FIXED2 implies (allInvariants and s.interruptedShown
          and s.sendLog.exists(l => l.sent == 1))))
      .then(reload)
      .expect(FIXED2 implies s.interruptedShown)
      .then(if (FIXED2) dismissInterrupted else reload)
      .expect(not(s.interruptedShown) and s.sendLog.size() == 0)

  /// After New merge, Back on step 6 stays disabled.
  run back6AfterNewMergeTest =
    start.then(toStep4).then(passTestAndVerify(0))
      .then(next5).then(typeSend).then(send).then(sendAll)
      .then(newMerge).then(toStep4).then(passTestAndVerify(3)).then(next5)
      .expect(bugIff(back6Usable))
}

module buggy {
  import wizard(ROUND = 0).*
}

module partial {
  import wizard(ROUND = 1).*
}

module fixed {
  import wizard(ROUND = 2).*
}

// Trace generation for the conformance tests (tests/test_conformance.py),
// not for checking. The same actions as `step` in `fixed`, but an action
// that undoes progress (going back, editing, re-uploading, a reload, sign-out,
// a token running out, a server restart, a request or job failing) is only taken after GAP steps that
// didn't (Back moves don't count), so random traces climb to the send step and fall back from every
// depth. Uniform choice among the enabled actions of `step` almost never
// gets past step 3.
module conformance {
  import wizard(ROUND = 2).*

  var quiet: int  // steps since the last action that undid progress
  pure val GAP = 8

  action cInit = all { init, quiet' = 0 }
  action fwd(a: bool): bool = all { a, quiet' = quiet + 1 }
  action undo(a: bool): bool = all { quiet >= GAP, a, quiet' = 0 }
  // Back moves don't reset the count, so they can follow one another (a job
  // finishing between two Backs is a case worth replaying).
  action backUp(a: bool): bool = all { quiet >= GAP, a, quiet' = quiet }

  action cStep = any {
    // The first upload moves forward; a later one starts the merge again.
    if (s.dataLoaded) undo(upload) else fwd(upload),
    fwd(next1), nondet bcc = Bool.oneOf() undo(edit(bcc)), backUp(back2), fwd(next2),
    nondet ok = Bool.oneOf() if (ok) fwd(previewResponse(true)) else undo(previewResponse(false)),
    backUp(back3), fwd(next3),
    fwd(sendTestEmail), nondet a = Bool.oneOf() backUp(back4(a)), fwd(next4),
    nondet a = Bool.oneOf() backUp(back5(a)), fwd(next5),
    fwd(typeSend), fwd(startSend), fwd(startSendResponse),
    nondet a = Bool.oneOf() backUp(back6(a)), fwd(stopSend), fwd(newMerge), fwd(dismissInterrupted),
    nondet ok = Bool.oneOf() if (ok) fwd(completeJob(true)) else undo(completeJob(false)),
    fwd(completeOrphan),
    fwd(sendNext), nondet failed = Bool.oneOf() if (failed) undo(finishSend(true)) else fwd(finishSend(false)),
    undo(sendWithoutToken),
    nondet desktop = Bool.oneOf() fwd(signIn(desktop)),
    undo(signOut), undo(tokenExpires), undo(reload), undo(serverRestart),
  }
  // For the browser tier: the same, but a pending recipient preview or
  // start-job response is answered before anything else (the browser tier
  // doesn't hold responses; the await windows are covered by the client
  // tier and tests/test_web_e2e_workflow.py), and no server restart (it
  // keeps one server).
  action settled(a: bool): bool = all { s.previewReq.size() == 0, s.sendReq.size() == 0, a }
  action eStep = any {
    // The first upload moves forward; a later one starts the merge again.
    if (s.dataLoaded) undo(settled(upload)) else fwd(settled(upload)),
    fwd(settled(next1)), nondet bcc = Bool.oneOf() undo(settled(edit(bcc))), backUp(settled(back2)), fwd(settled(next2)),
    nondet ok = Bool.oneOf() if (ok) fwd(previewResponse(true)) else undo(previewResponse(false)),
    backUp(settled(back3)), fwd(settled(next3)),
    fwd(settled(sendTestEmail)), nondet a = Bool.oneOf() backUp(settled(back4(a))), fwd(settled(next4)),
    nondet a = Bool.oneOf() backUp(settled(back5(a))), fwd(settled(next5)),
    fwd(settled(typeSend)), fwd(settled(startSend)), fwd(startSendResponse),
    nondet a = Bool.oneOf() backUp(settled(back6(a))), fwd(settled(stopSend)), fwd(settled(newMerge)),
    fwd(settled(dismissInterrupted)),
    nondet ok = Bool.oneOf() if (ok) fwd(settled(completeJob(true))) else undo(settled(completeJob(false))),
    fwd(settled(completeOrphan)),
    fwd(settled(sendNext)), nondet failed = Bool.oneOf() if (failed) undo(settled(finishSend(true))) else fwd(settled(finishSend(false))),
    undo(settled(sendWithoutToken)),
    nondet desktop = Bool.oneOf() fwd(settled(signIn(desktop))),
    undo(settled(signOut)), undo(settled(tokenExpires)), undo(settled(reload))
  }

}
