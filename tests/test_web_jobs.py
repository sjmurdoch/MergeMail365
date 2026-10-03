"""JobStore: the web UI's job lifecycle (web/jobs.py), without Flask.

Each test names the spec/wizard.qnt action or invariant it exercises.
"""

import threading

import pytest

from mail_merge.sender import SendAborted, SendResult
from mail_merge.web.jobs import JobStatus, JobStore


def ok(email: str) -> SendResult:
    return SendResult(email=email, success=True, status_code=202)


class SteppedRunner:
    """A send_merge() stand-in that sends one email each time step() is called."""

    def __init__(self, emails: list[str]) -> None:
        self.emails = emails
        self.go = threading.Semaphore(0)
        self.sent = threading.Semaphore(0)

    def __call__(self, should_stop, on_result, **kwargs):
        results = []
        for email in self.emails:
            self.go.acquire()
            if should_stop():
                self.sent.release()
                return results
            results.append(ok(email))
            on_result(results[-1])
            self.sent.release()
        return results

    def step(self) -> None:
        self.go.release()
        assert self.sent.acquire(timeout=5)


def run_in_thread(store: JobStore, job, runner) -> threading.Thread:
    thread = threading.Thread(target=store.run, args=(job, {}, runner), daemon=True)
    thread.start()
    return thread


class TestCreate:
    def test_ids_follow_creation_order(self):
        store = JobStore()
        jobs = [store.create(mode) for mode in ("test_email", "dry_run", "send")]
        assert [j.seq for j in jobs] == [0, 1, 2]
        assert store.created == 3

    def test_second_send_refused_while_one_runs(self):
        """noConcurrentSends."""
        store = JobStore()
        first = store.create("send")
        assert store.create("send") is None
        assert store.create("test_email") is not None
        first.status = JobStatus.COMPLETED
        assert store.create("send") is not None

    def test_finished_jobs_are_evicted_when_a_job_is_created(self):
        store = JobStore()
        old = store.create("dry_run")
        old.status = JobStatus.COMPLETED
        store.create("test_email")
        assert old.id not in store.jobs


class TestRun:
    def test_send_counts_each_email_and_completes(self):
        """sendNext, finishSend(false)."""
        store = JobStore()
        job = store.create("send")
        runner = SteppedRunner(["a@x.com", "b@x.com"])
        thread = run_in_thread(store, job, runner)
        assert store.abstract(None)["sendJob"][0]["status"] == "Running"
        runner.step()
        assert store.abstract(None)["sendJob"][0]["sent"] == 1
        runner.step()
        thread.join(5)
        assert store.abstract(None)["sendJob"] == [
            {"id": 0, "sent": 2, "stopRequested": False, "status": "Completed"},
        ]

    def test_stop_ends_the_send_before_the_next_email(self):
        """stopSend, then finishSend: stopHonoured, stoppedReported."""
        store = JobStore()
        job = store.create("send")
        runner = SteppedRunner(["a@x.com", "b@x.com", "c@x.com"])
        thread = run_in_thread(store, job, runner)
        runner.step()
        assert store.request_stop(job.id)
        runner.step()
        thread.join(5)
        assert job.status is JobStatus.STOPPED
        assert job.sent == 1
        assert [r.email for r in job.results] == ["a@x.com"]

    def test_failed_send_keeps_the_results_so_far(self):
        """finishSend(true) after sendNext: failedSendReported."""
        store = JobStore()
        job = store.create("send")

        def fail_after_one(should_stop, on_result, **kwargs):
            on_result(ok("a@x.com"))
            raise SendAborted("Not signed in", [ok("a@x.com")])

        store.run(job, {}, fail_after_one)
        assert job.status is JobStatus.FAILED
        assert job.error == "Not signed in"
        assert [r.email for r in job.results] == ["a@x.com"]
        assert store.abstract(None)["sendJob"][0] == {
            "id": 0, "sent": 1, "stopRequested": False, "status": "Failed",
        }

    def test_job_ends_with_a_sentinel(self):
        store = JobStore()
        job = store.create("dry_run")
        store.run(job, {}, lambda **kwargs: [])
        events = []
        while not job.events.empty():
            events.append(job.events.get())
        assert events[-1] is None
        assert {"type": "completed", "data": {"message": "Job completed"}} in events

    def test_request_stop_for_unknown_job(self):
        assert JobStore().request_stop("nope") is False


class TestActiveJob:
    def test_running_send_wins_over_the_session_job(self):
        """runningSendVisible: a reload finds the send even if the session doesn't name it."""
        store = JobStore()
        send = store.create("send")
        assert store.active_job_id(None) == send.id

    def test_finished_send_of_the_session_is_resumed(self):
        store = JobStore()
        send = store.create("send")
        send.status = JobStatus.COMPLETED
        assert store.active_job_id(send.id) == send.id
        assert store.active_job_id(None) is None

    @pytest.mark.parametrize("mode", ["test_email", "dry_run"])
    def test_test_and_dry_run_are_not_resumed(self, mode):
        """sendScreenHonest."""
        store = JobStore()
        job = store.create(mode)
        assert store.active_job_id(job.id) is None


class TestAbstract:
    def test_model_fields(self):
        store = JobStore()
        assert store.abstract(None) == {"sessionJob": [], "sendJob": [], "nextJobId": 0}
        test = store.create("test_email")
        assert store.abstract(test.id)["sessionJob"] == [{"id": 0, "kind": "Test", "done": False}]
        test.status = JobStatus.FAILED
        assert store.abstract(test.id)["sessionJob"] == [{"id": 0, "kind": "Test", "done": True}]
        verify = store.create("dry_run")
        assert store.abstract(verify.id)["sessionJob"][0]["kind"] == "Verify"
        assert store.abstract(None)["nextJobId"] == 2

    def test_send_job_survives_eviction(self):
        store = JobStore()
        send = store.create("send")
        send.status = JobStatus.COMPLETED
        store.create("test_email")
        assert send.id not in store.jobs
        assert store.abstract(None)["sendJob"][0]["status"] == "Completed"
