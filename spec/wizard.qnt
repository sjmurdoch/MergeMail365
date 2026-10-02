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
    // --- ghost ---
    testedVersions: Set[int],
    verifiedVersions: Set[int],
    realSendStarted: bool,
    untestedSend: bool,
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
    sessionJob: Set(), nextJobId: 0,
    testedVersions: Set(), verifiedVersions: Set(),
    realSendStarted: false, untestedSend: false,
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
  // ---------------------------------------------------------------------

  action init = all { s' = init_state, lastAction' = "init" }

  action act(name: str, st: State): bool = all { s' = st, lastAction' = name }

  // Step 1: upload or change sheet
  action upload = all { s.step == 1, act("upload", { ...s, dataLoaded: true, version: s.version + 1 }) }
  action next1 = all { s.step == 1, act("next1", goToStep(s, 2)) }

  // Step 2: edit any compose field
  action edit = all { s.step == 2, act("edit", { ...s, version: s.version + 1 }) }
  action back2 = all { s.step == 2, act("back2", goToStep(s, 1)) }
  action next2 = all { s.step == 2, act("next2", goToStep(s, 3)) }

  // Step 3
  action back3 = all { s.step == 3, act("back3", confirmGoBack(s, 2, true)) }
  action next3 = all { s.step == 3, act("next3", goToStep(s, 4)) }

  // Step 4
  action sendTestEmail = all {
    s.step == 4, s.btnSendTest,
    val g = s.testGen + 1
    act("sendTestEmail", { ...startJob(s, Test, g),
      testGen: g, testPassed: false, btnSendTest: false,
      // Bug: btn-next-4 stays enabled while testPassed is false.
      btnNext4: if (FIXED) false else s.btnNext4 }),
  }
  action back4(accept: bool): bool = all { s.step == 4, act("back4", confirmGoBack(s, 3, accept)) }
  action next4 = all { s.step == 4, s.btnNext4, act("next4", goToStep(s, 5)) }

  // Step 5
  action back5(accept: bool): bool = all { s.step == 5, act("back5", confirmGoBack(s, 4, accept)) }
  action next5 = all { s.step == 5, s.btnNext5, act("next5", goToStep(s, 6)) }

  // Step 6
  action typeSend = all {
    s.step == 6, not(s.sendStarted),
    act("typeSend", { ...s, btnDoSend: true }),
  }
  action startSend = all {
    s.step == 6, not(s.sendStarted), s.btnDoSend,
    val ok = s.testedVersions.contains(s.version) and s.verifiedVersions.contains(s.version)
    act("startSend", { ...startJob(s, Send, 0),
      sendStarted: true, btnBack6: false, btnDoSend: false,
      realSendStarted: true, untestedSend: s.untestedSend or not(ok) }),
  }
  action back6(accept: bool): bool = all {
    s.step == 6, not(s.sendStarted), s.btnBack6,
    act("back6", confirmGoBack(s, 4, accept)),
  }

  // newMerge() — only reachable from send-done-nav
  action newMerge = all {
    s.step == 6, s.doneNav,
    act("newMerge", { ...resetTestAndVerify(s),
      step: 1, dataLoaded: false, version: s.version + 1,
      sendStarted: false, btnDoSend: false, doneNav: false,
      sessionJob: Set(),  // POST /api/reset pops job_id
    }),
  }

  // The server finishes a job; the page's callback (if any) fires.
  action completeJob(ok: bool): bool = all {
    s.pending.size() > 0,
    nondet j = s.pending.oneOf()
    act("complete", markSessionJobDone(complete(s, j, ok), j.id)),
  }

  // Deterministic completion of a specific job, for scenario tests.
  action completeById(id: int, ok: bool): bool = all {
    s.pending.exists(p => p.id == id),
    nondet j = s.pending.filter(p => p.id == id).oneOf()
    act("complete", markSessionJobDone(complete(s, j, ok), j.id)),
  }

  // The server finishes the session's job with nobody listening (its page
  // was reloaded away).
  action completeOrphan = all {
    s.sessionJob.exists(sj => not(sj.done) and s.pending.forall(p => p.id != sj.id)),
    nondet sj = s.sessionJob.oneOf()
    act("completeOrphan", markSessionJobDone(s, sj.id)),
  }

  // Page reload: JS memory and DOM reset; session, temp files, localStorage
  // and server jobs survive. loadConfig() then runs.
  action reload = {
    val fresh = { ...init_state,
      dataLoaded: s.dataLoaded, version: s.version,
      sessionJob: s.sessionJob, nextJobId: s.nextJobId,
      testGen: s.testGen, verifyGen: s.verifyGen,
      testedVersions: s.testedVersions, verifiedVersions: s.verifiedVersions,
      realSendStarted: s.realSendStarted, untestedSend: s.untestedSend,
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
    typeSend, startSend, nondet a = Bool.oneOf() back6(a), newMerge,
    nondet ok = Bool.oneOf() completeJob(ok),
    completeOrphan,
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

  val allInvariants = and {
    noUntestedSend, next4Honest, next5Honest, buttonsMatchFlags,
    back6Usable, sendScreenHonest, sendScreenNotStuck, stepNeedsData,
  }

  // ---------------------------------------------------------------------
  // Scenarios (quint test). Each replays one counterexample; the invariant
  // must fail in the buggy model and hold in the fixed one. Job ids are
  // assigned in start order from 0.
  // ---------------------------------------------------------------------

  pure def bugIff(inv: bool): bool = if (FIXED) inv else not(inv)

  action toStep4 = upload.then(next1).then(next2).then(next3)

  action passTestAndVerify(testId: int): bool =
    sendTestEmail.then(completeById(testId, true))
      .then(next4).then(completeById(testId + 1, true))

  run happyPathTest =
    init.then(toStep4).then(passTestAndVerify(0))
      .then(next5).then(typeSend).then(startSend).then(completeById(2, true))
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
      .then(next5).then(typeSend).then(startSend).then(completeById(2, true))
      .then(reload)
      .expect(bugIff(sendScreenNotStuck))

  /// After New merge, Back on step 6 stays disabled.
  run back6AfterNewMergeTest =
    init.then(toStep4).then(passTestAndVerify(0))
      .then(next5).then(typeSend).then(startSend).then(completeById(2, true))
      .then(newMerge).then(toStep4).then(passTestAndVerify(3)).then(next5)
      .expect(bugIff(back6Usable))
}

module buggy {
  import wizard(FIXED = false).*
}

module fixed {
  import wizard(FIXED = true).*
}
