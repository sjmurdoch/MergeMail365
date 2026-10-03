// -*- mode: Bluespec; -*-
/**
 * Workflow layer of the web UI wizard (src/mail_merge/web/static/app.js and
 * the job/session parts of web/app.py).
 *
 * FIXED = false models the code as of fb28c33, bugs included.
 * FIXED = true models the proposed fixes, which must satisfy every invariant.
 *
 * Abstractions:
 * - `version` stands for everything that determines what gets sent
 *   (spreadsheet, sheet, compose fields, options). Any upload or edit bumps it.
 * - A job is started by an action and completed later by a separate action,
 *   so completions can interleave with navigation and reloads.
 * - Ghost fields (testedVersions, verifiedVersions, ...) record what really
 *   happened; the code never reads them, only the invariants do.
 * - Button fields mirror `disabled` (true = enabled) for buttons whose state
 *   the code sets explicitly.
 */
module wizard {
  const FIXED: bool

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
  type Status = Running | Completed | Failed | Stopped

  // The server's record of the current send job (web/app.py Job, mode
  // "send"): how many emails the send loop has sent and whether Stop was
  // pressed. `stopEarly` is a ghost: Stop was pressed while emails remained.
  type SendJob = { id: int, sent: int, stopRequested: bool, status: Status, stopEarly: bool }

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
    // --- DOM projection (true = enabled / visible) ---
    btnSendTest: bool,
    btnNext4: bool,
    btnNext5: bool,
    btnDoSend: bool,
    btnBack6: bool,
    doneNav: bool,
    // --- pending completion callbacks in the current page ---
    pending: Set[Job],
    // --- server ---
    sessionJob: Set[SessionJob],  // empty or singleton
    nextJobId: int,
    sendJob: Set[SendJob],        // empty or singleton
    // --- ghost ---
    testedVersions: Set[int],
    verifiedVersions: Set[int],
    realSendStarted: bool,
    untestedSend: bool,
    sentAfterStop: int,           // emails the send loop sent after Stop was pressed
  }

  var s: State
  var lastAction: str

  pure val init_state: State = {
    step: 1, dataLoaded: false, version: 0,
    testPassed: false, verifyPassed: false, sendStarted: false,
    testGen: 0, verifyGen: 0,
    btnSendTest: true, btnNext4: false, btnNext5: false,
    btnDoSend: false, btnBack6: true, doneNav: false,
    pending: Set(),
    sessionJob: Set(), nextJobId: 0, sendJob: Set(),
    testedVersions: Set(), verifiedVersions: Set(),
    realSendStarted: false, untestedSend: false, sentAfterStop: 0,
  }

  // ---------------------------------------------------------------------
  // Helpers mirroring app.js functions
  // ---------------------------------------------------------------------

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
      btnNext4: false, btnNext5: false,
      // FIXED: bump generations so in-flight completions are ignored, and
      // let the user start a fresh test.
      testGen: if (FIXED) st.testGen + 1 else st.testGen,
      verifyGen: if (FIXED) st.verifyGen + 1 else st.verifyGen,
      btnSendTest: if (FIXED) true else st.btnSendTest,
    }

  // startVerify(), called on entry to step 5
  pure def startVerify(st: State): State = {
    val g = st.verifyGen + 1
    { ...startJob(st, Verify, g), verifyGen: g, verifyPassed: false, btnNext5: false }
  }

  // prepareSend(), called on entry to step 6
  pure def prepareSend(st: State): State =
    { ...st, sendStarted: false, btnDoSend: false, doneNav: false,
      // Bug: btn-back-6 is disabled by startSend() and never re-enabled.
      btnBack6: if (FIXED) true else st.btnBack6 }

  // goToStep(n). Forward guards that `return` early leave state unchanged.
  pure def goToStep(st: State, n: int): State =
    if (n > st.step) {
      if (n == 2 and not(st.dataLoaded)) st
      else if (n == 5 and not(st.testPassed)) st
      else if (n == 6 and not(st.verifyPassed)) st
      else {
        val st1 = if (n == 5) startVerify(st) else if (n == 6) prepareSend(st) else st
        { ...st1, step: n }
      }
    } else { ...st, step: n }

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
        else { ...st1, btnSendTest: true }
      | Verify =>
        if (FIXED and j.gen != st1.verifyGen) st1
        else if (ok) { ...st1, verifyPassed: true, btnNext5: true }
        else st1
      | Send => { ...st1, doneNav: true }
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
  action upload = all { s.step == 1, act("upload", { ...s, dataLoaded: true, version: s.version + 1 }) }
  // app.js: goToStep(2) (#btn-next-1)
  action next1 = all { s.step == 1, act("next1", goToStep(s, 2)) }

  // Step 2: edit any compose field
  // app.js: onTemplateChange() and the compose input listeners, setSendMode()
  action edit = all { s.step == 2, act("edit", { ...s, version: s.version + 1 }) }
  // app.js: goToStep(1) (step 2 Back)
  action back2 = all { s.step == 2, act("back2", goToStep(s, 1)) }
  // app.js: goToStep(3) (#btn-next-2); web/app.py: api_get_recipients
  action next2 = all { s.step == 2, act("next2", goToStep(s, 3)) }

  // Step 3
  // app.js: confirmGoBack(2) (step 3 Back)
  action back3 = all { s.step == 3, act("back3", confirmGoBack(s, 2, true)) }
  // app.js: goToStep(4) (#btn-next-3)
  action next3 = all { s.step == 3, act("next3", goToStep(s, 4)) }

  // Step 4
  // app.js: sendTestEmail() (#btn-send-test, #btn-retry-test); web/app.py: api_start_job (mode test_email)
  action sendTestEmail = all {
    s.step == 4, s.btnSendTest,
    val g = s.testGen + 1
    act("sendTestEmail", { ...startJob(s, Test, g),
      testGen: g, testPassed: false, btnSendTest: false,
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
  // app.js: startSend() (#btn-do-send); web/app.py: api_start_job (mode send)
  action startSend = all {
    s.step == 6, not(s.sendStarted), s.btnDoSend,
    val ok = s.testedVersions.contains(s.version) and s.verifiedVersions.contains(s.version)
    act("startSend", { ...startJob(s, Send, 0),
      sendStarted: true, btnBack6: false, btnDoSend: false,
      sendJob: Set({ id: s.nextJobId, sent: 0, stopRequested: false, status: Running, stopEarly: false }),
      realSendStarted: true, untestedSend: s.untestedSend or not(ok) }),
  }
  // app.js: confirmGoBack(4) (#btn-back-6)
  action back6(accept: bool): bool = all {
    s.step == 6, not(s.sendStarted), s.btnBack6,
    act("back6", confirmGoBack(s, 4, accept)),
  }

  // "Stop sending" is inside #send-progress, shown from startSend() until the
  // results replace it. It posts to the current job, which while sending is
  // the send job.
  // app.js: stopSend() (#btn-stop-send); web/app.py: api_job_stop
  action stopSend = all {
    s.step == 6, s.sendStarted, not(s.doneNav),
    act("stopSend", { ...s,
      sendJob: s.sendJob.map(j =>
        if (j.status == Running)
          { ...j, stopRequested: true, stopEarly: j.stopEarly or j.sent < TOTAL }
        else j) }),
  }

  // newMerge() — only reachable from send-done-nav
  // app.js: newMerge() (#btn-new-merge); web/app.py: api_reset
  action newMerge = all {
    s.step == 6, s.doneNav,
    act("newMerge", { ...resetTestAndVerify(s),
      step: 1, dataLoaded: false, version: s.version + 1,
      sendStarted: false, btnDoSend: false, doneNav: false,
      sessionJob: Set(),  // POST /api/reset pops job_id
    }),
  }

  // The server finishes a test or dry-run job; the page's callback (if any)
  // fires. Send jobs finish through the send loop below instead.
  // environment: web/app.py api_start_job._run_job; app.js streamEvents() completion
  action completeJob(ok: bool): bool = all {
    s.pending.exists(p => p.kind != Send),
    nondet j = s.pending.filter(p => p.kind != Send).oneOf()
    act("complete", markSessionJobDone(complete(s, j, ok), j.id)),
  }

  // Deterministic completion of a specific job, for scenario tests.
  action completeById(id: int, ok: bool): bool = all {
    s.pending.exists(p => p.id == id and p.kind != Send),
    nondet j = s.pending.filter(p => p.id == id).oneOf()
    act("complete", markSessionJobDone(complete(s, j, ok), j.id)),
  }

  // The server finishes the session's test or dry-run job with nobody
  // listening (its page was reloaded away).
  // environment: web/app.py api_start_job._run_job
  action completeOrphan = all {
    s.sessionJob.exists(sj => not(sj.done) and sj.kind != Send and s.pending.forall(p => p.id != sj.id)),
    nondet sj = s.sessionJob.oneOf()
    act("completeOrphan", markSessionJobDone(s, sj.id)),
  }

  // One iteration of the send loop: send_one() for the next recipient.
  // Bug: neither loop reads job.stop_requested, so Stop does nothing.
  // FIXED: the loop checks the job's should_stop() before each email.
  // environment: sender.py send_all() / send_bcc_blast() loop body
  action sendNext = all {
    s.sendJob.exists(j => j.status == Running and j.sent < TOTAL
      and (not(FIXED) or not(j.stopRequested))),
    nondet j = s.sendJob.oneOf()
    act("sendNext", { ...s,
      sendJob: Set({ ...j, sent: j.sent + 1 }),
      sentAfterStop: if (j.stopRequested) s.sentAfterStop + 1 else s.sentAfterStop }),
  }

  // The send job's thread ends: the loop ran out of recipients, stopped
  // early (FIXED only), or send_merge() raised. The page's send callback, if
  // one is attached, then fetches the status and shows the results.
  // environment: web/app.py api_start_job._run_job; app.js streamEvents() completion
  action finishSend(failed: bool): bool = all {
    s.sendJob.exists(j => j.status == Running
      and (failed or j.sent == TOTAL or (FIXED and j.stopRequested))),
    nondet j = s.sendJob.oneOf()
    val status = if (failed) Failed else if (j.sent == TOTAL) Completed else Stopped
    val st1 = { ...s, sendJob: Set({ ...j, status: status }) }
    val st2 = s.pending.filter(p => p.id == j.id).fold(st1, (acc, p) => complete(acc, p, not(failed)))
    act("finishSend", markSessionJobDone(st2, j.id)),
  }

  // Page reload: JS memory and DOM reset; session, temp files, localStorage
  // and server jobs survive. loadConfig() then runs.
  // app.js: DOMContentLoaded, loadConfig(); web/app.py: api_config
  action reload = {
    val fresh = { ...init_state,
      dataLoaded: s.dataLoaded, version: s.version,
      sessionJob: s.sessionJob, nextJobId: s.nextJobId, sendJob: s.sendJob,
      testGen: s.testGen, verifyGen: s.verifyGen,
      testedVersions: s.testedVersions, verifiedVersions: s.verifiedVersions,
      realSendStarted: s.realSendStarted, untestedSend: s.untestedSend,
      sentAfterStop: s.sentAfterStop,
    }
    // Bug: /api/config reports session["job_id"] as active whenever it is
    // still in _jobs, whatever its mode and even if it has finished.
    val active =
      if (FIXED) s.sessionJob.filter(sj => sj.kind == Send)
      else s.sessionJob
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
          if (FIXED) { ...reconnected, doneNav: true } else reconnected
        } else {
          // Reattach the send-step callback to whatever job this is.
          { ...reconnected, pending: Set({
              id: sj.id, kind: sj.kind, handler: Send, version: s.version, gen: 0 }) }
        }
      }
    act("reload", after)
  }

  action step = any {
    upload, next1, edit, back2, next2, back3, next3,
    sendTestEmail, nondet a = Bool.oneOf() back4(a), next4,
    nondet a = Bool.oneOf() back5(a), next5,
    typeSend, startSend, nondet a = Bool.oneOf() back6(a), stopSend, newMerge,
    nondet ok = Bool.oneOf() completeJob(ok),
    completeOrphan,
    sendNext, nondet failed = Bool.oneOf() finishSend(failed),
    reload,
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

  /// Before sending, the user can always go back from step 6.
  val back6Usable = (s.step == 6 and not(s.sendStarted)) implies s.btnBack6

  /// The "sending" screen only appears for a real send.
  val sendScreenHonest = (s.step == 6 and s.sendStarted) implies s.realSendStarted

  /// The sending screen always eventually offers a way out: either a callback
  /// is pending or the done navigation is shown.
  val sendScreenNotStuck =
    (s.step == 6 and s.sendStarted)
      implies (s.doneNav or s.pending.exists(p => p.handler == Send))

  val stepNeedsData = s.step >= 2 implies s.dataLoaded

  /// No email is sent after Stop is pressed. An email already being sent when
  /// Stop is pressed counts as sent before it, because sendNext is atomic.
  val stopHonoured = s.sentAfterStop == 0

  /// A send stopped while emails remained ends as Stopped (unless it failed),
  /// never as Completed.
  val stoppedReported = s.sendJob.forall(j =>
    (j.stopEarly and j.status != Running and j.status != Failed) implies j.status == Stopped)

  val allInvariants = and {
    noUntestedSend, next4Honest, next5Honest, buttonsMatchFlags,
    back6Usable, sendScreenHonest, sendScreenNotStuck, stepNeedsData,
    stopHonoured, stoppedReported,
  }

  // ---------------------------------------------------------------------
  // Scenarios (quint test). Each replays one counterexample; the invariant
  // must fail in the buggy model and hold in the fixed one. Job ids are
  // assigned in start order from 0.
  // ---------------------------------------------------------------------

  pure def bugIff(inv: bool): bool = if (FIXED) inv else not(inv)

  action toStep4 = upload.then(next1).then(next2).then(next3)

  // The send loop sends every email, then the job finishes.
  action sendAll = sendNext.then(sendNext).then(sendNext).then(finishSend(false))

  action passTestAndVerify(testId: int): bool =
    sendTestEmail.then(completeById(testId, true))
      .then(next4).then(completeById(testId + 1, true))

  run happyPathTest =
    init.then(toStep4).then(passTestAndVerify(0))
      .then(next5).then(typeSend).then(startSend).then(sendAll)
      .expect(allInvariants and s.doneNav)

  /// A test that completes after the user went back and edited enables Next.
  run staleTestCompletionTest =
    init.then(toStep4).then(sendTestEmail).then(back4(true)).then(back3)
      .then(completeById(0, true)).then(edit).then(next2).then(next3)
      .expect(bugIff(next4Honest))

  /// An old dry run completing during a newer one enables Next on step 5.
  run staleVerifyCompletionTest =
    init.then(toStep4).then(sendTestEmail).then(completeById(0, true))
      .then(next4)                                   // dry run 1 starts
      .then(back5(true)).then(back4(true)).then(back3).then(edit)
      .then(next2).then(next3).then(sendTestEmail).then(completeById(2, true))
      .then(next4)                                   // dry run 3 starts
      .then(completeById(1, true))                   // stale dry run 1 finishes
      .expect(bugIff(next5Honest))

  /// Re-sending a test leaves Next enabled while testPassed is false.
  run retestLeavesNextEnabledTest =
    init.then(toStep4).then(sendTestEmail).then(completeById(0, true)).then(sendTestEmail)
      .expect(bugIff(buttonsMatchFlags))

  /// Reloading during a test email jumps to the Send step.
  run reloadDuringTestTest =
    init.then(toStep4).then(sendTestEmail).then(reload)
      .expect(bugIff(sendScreenHonest))

  /// Reloading after a test email finished leaves the page stuck on "Sending".
  run reloadAfterTestTest =
    init.then(toStep4).then(sendTestEmail).then(completeById(0, true)).then(reload)
      .expect(bugIff(sendScreenNotStuck))

  /// Reloading after a real send finished also gets stuck.
  run reloadAfterSendTest =
    init.then(toStep4).then(passTestAndVerify(0))
      .then(next5).then(typeSend).then(startSend).then(sendAll)
      .then(reload)
      .expect(bugIff(sendScreenNotStuck))

  /// Stop sending does nothing: the loop keeps sending (bug 7). Fixed: the
  /// loop stops before the next email and the job ends as Stopped.
  run stopIgnoredTest =
    init.then(toStep4).then(passTestAndVerify(0))
      .then(next5).then(typeSend).then(startSend).then(sendNext).then(stopSend)
      .then(any { all { FIXED, finishSend(false) }, all { not(FIXED), sendNext } })
      .expect(bugIff(stopHonoured)
        and (FIXED implies (s.doneNav and s.sendJob.forall(j => j.status == Stopped and j.sent == 1))))

  /// A stopped send reports Completed once every email has gone out.
  run stoppedReportedTest =
    init.then(toStep4).then(passTestAndVerify(0))
      .then(next5).then(typeSend).then(startSend).then(stopSend)
      .then(any { all { FIXED, finishSend(false) }, all { not(FIXED), sendAll } })
      .expect(bugIff(stoppedReported))

  /// After New merge, Back on step 6 stays disabled.
  run back6AfterNewMergeTest =
    init.then(toStep4).then(passTestAndVerify(0))
      .then(next5).then(typeSend).then(startSend).then(sendAll)
      .then(newMerge).then(toStep4).then(passTestAndVerify(3)).then(next5)
      .expect(bugIff(back6Usable))
}

module buggy {
  import wizard(FIXED = false).*
}

module fixed {
  import wizard(FIXED = true).*
}
