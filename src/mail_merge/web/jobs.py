"""Background jobs of the web UI: their lifecycle, with no Flask.

`JobStore` holds the jobs and makes every state change the wizard model
(spec/wizard.qnt) describes for them: creating a job (one send at a time),
recording each email sent, Stop, finishing, and the job a reloaded page
should reconnect to. `run()` drives a job with an injectable runner
(`send_merge()` by default), so tests can control the send loop.
`abstract()` maps the store onto the model's server fields for conformance
testing.
"""

import enum
import logging
import queue
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from mail_merge.sender import SendResult

logger = logging.getLogger(__name__)


class JobStatus(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


FINISHED_STATUSES = (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.STOPPED)


@dataclass
class Job:
    id: str
    mode: str = ""  # "dry_run", "test_email" or "send"
    status: JobStatus = JobStatus.PENDING
    events: queue.Queue[dict[str, Any] | None] = field(default_factory=queue.Queue)
    results: list[SendResult] | None = None
    error: str | None = None
    stop_requested: bool = False
    # Set when the send loop saw stop_requested and stopped early.
    stopped_early: bool = False
    # Emails (or BCC batches' recipients) the loop has finished with so far.
    sent: int = 0
    # Creation order in the store: the model's job id.
    seq: int = 0


class JobLogHandler(logging.Handler):
    """Captures mail_merge logger output into a job's event queue."""

    def __init__(self, job: Job) -> None:
        super().__init__()
        self.job = job

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.job.events.put({
                "type": "log",
                "data": {
                    "message": self.format(record),
                    "level": record.levelname,
                    "timestamp": time.strftime("%H:%M:%S", time.localtime(record.created)),
                },
            })
        except Exception:
            pass


# The model's names for job modes and statuses (spec/wizard.qnt Kind, Status).
_MODEL_KIND = {"test_email": "Test", "dry_run": "Verify", "send": "Send"}
_MODEL_STATUS = {
    JobStatus.PENDING: "Running",
    JobStatus.RUNNING: "Running",
    JobStatus.COMPLETED: "Completed",
    JobStatus.FAILED: "Failed",
    JobStatus.STOPPED: "Stopped",
}


class JobStore:
    """The web UI's jobs. One instance per process: the app has one user."""

    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()
        self.created = 0
        # The latest send job, kept after eviction for abstract().
        self.last_send: Job | None = None

    def running_send(self) -> Job | None:
        """The send job still in progress, if any.

        Checked across sessions: a page whose start-job response never
        arrived has no job id in its session cookie (runningSendVisible).
        """
        for job in self.jobs.values():
            if job.mode == "send" and job.status not in FINISHED_STATUSES:
                return job
        return None

    def create(self, mode: str) -> Job | None:
        """A new job, or None if `mode` is "send" and a send is running
        (noConcurrentSends). Finished jobs are evicted first."""
        with self.lock:
            if mode == "send" and self.running_send():
                return None
            for jid in list(self.jobs):
                if self.jobs[jid].status in FINISHED_STATUSES:
                    del self.jobs[jid]
            job = Job(id=str(uuid.uuid4()), mode=mode, seq=self.created)
            self.created += 1
            self.jobs[job.id] = job
            if mode == "send":
                self.last_send = job
            return job

    def get(self, job_id: str | None) -> Job | None:
        return self.jobs.get(job_id) if job_id else None

    def request_stop(self, job_id: str) -> bool:
        """Ask the job's send loop to stop before its next email (stopSend)."""
        job = self.jobs.get(job_id)
        if job is None:
            return False
        job.stop_requested = True
        return True

    @staticmethod
    def should_stop(job: Job) -> bool:
        """Checked by the send loop before each email or batch (stopHonoured)."""
        if job.stop_requested:
            job.stopped_early = True
            return True
        return False

    @staticmethod
    def record_sent(job: Job, _result: SendResult) -> None:
        """Called by the send loop after each email (sendNext)."""
        job.sent += 1

    def active_job_id(self, session_job_id: str | None) -> str | None:
        """The job a reloaded page reconnects to: any running send, else the
        session's job if it is a send (sendScreenHonest, runningSendVisible)."""
        running = self.running_send()
        if running:
            return running.id
        job = self.get(session_job_id)
        return job.id if job and job.mode == "send" else None

    def run(self, job: Job, kwargs: dict[str, Any],
            runner: Callable[..., list[SendResult]] | None = None) -> None:
        """Run the job to the end in this thread (finishSend, completeJob)."""
        job.status = JobStatus.RUNNING
        logger.debug("Job %s started (mode=%r)", job.id, job.mode)
        handler = JobLogHandler(job)
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(message)s"))
        mm_logger = logging.getLogger("mail_merge")
        mm_logger.addHandler(handler)
        try:
            if runner is None:
                from mail_merge.api import send_merge
                runner = send_merge
            results = runner(
                **kwargs,
                should_stop=lambda: self.should_stop(job),
                on_result=lambda result: self.record_sent(job, result),
            )
            job.results = results
            if job.stopped_early:
                job.status = JobStatus.STOPPED
                job.events.put({"type": "stopped", "data": {"message": "Job stopped"}})
            else:
                job.status = JobStatus.COMPLETED
                job.events.put({"type": "completed", "data": {"message": "Job completed"}})
        except Exception as exc:
            logger.debug("send_merge job failed", exc_info=True)
            from mail_merge.sender import SendAborted
            if isinstance(exc, SendAborted):
                # Keep the emails that went out before the error
                # (spec/wizard.qnt, failedSendReported).
                job.results = exc.results
            job.error = str(exc)
            job.status = JobStatus.FAILED
            job.events.put({"type": "error", "data": {"message": str(exc)}})
        finally:
            mm_logger.removeHandler(handler)
            job.events.put(None)  # Sentinel

    def start(self, job: Job, kwargs: dict[str, Any]) -> threading.Thread:
        """Run the job in a daemon thread named after it."""
        thread = threading.Thread(
            target=self.run, args=(job, kwargs), name=f"job-{job.id[:8]}", daemon=True,
        )
        thread.start()
        return thread

    def abstract(self, session_job_id: str | None) -> dict[str, Any]:
        """The model's server fields (spec/wizard.qnt State): sessionJob,
        sendJob and nextJobId, with job ids as creation order."""
        session_job = self.get(session_job_id)
        send = self.last_send
        return {
            "sessionJob": [] if session_job is None else [{
                "id": session_job.seq,
                "kind": _MODEL_KIND[session_job.mode],
                "done": session_job.status in FINISHED_STATUSES,
            }],
            "sendJob": [] if send is None else [{
                "id": send.seq,
                "sent": send.sent,
                "stopRequested": send.stop_requested,
                "status": _MODEL_STATUS[send.status],
            }],
            "nextJobId": self.created,
        }
