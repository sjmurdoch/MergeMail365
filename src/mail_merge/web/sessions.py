"""Server-side sessions for the web UI.

The cookie holds only a random session id; the data stays in this process's
memory. Flask's default keeps the data in the cookie itself, and what the
wizard stores there (the spreadsheet's column and sheet names, MSAL's
auth-code flow) can pass the 4 KB a browser accepts: the browser then drops
the cookie without a word and the next request has no session
(docs/review-fixes-plan.md, F14). It also means the PKCE verifier of a
sign-in in progress never leaves the server.

Nothing is lost by keeping sessions in memory: the cookie's signing key is
derived from the startup token, which changes on every start, so sessions
never survived a restart.
"""

import secrets
import threading
import time
from typing import Any

from flask import Flask, Request, Response
from flask.sessions import SessionInterface, SessionMixin
from werkzeug.datastructures import CallbackDict

# Far more than one user's browsers will ever hold; a bound, so that
# requests without a cookie cannot grow the store for ever.
MAX_SESSIONS = 200


class ServerSession(CallbackDict[str, Any], SessionMixin):
    def __init__(self, sid: str, data: dict[str, Any] | None = None, new: bool = False) -> None:
        def on_update(session: "ServerSession") -> None:
            session.modified = True

        super().__init__(data or {}, on_update)
        self.sid = sid
        self.new = new
        self.modified = False


class ServerSideSessions(SessionInterface):
    """Sessions kept in memory, addressed by an unguessable id in the cookie."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, dict[str, Any]]] = {}  # sid -> (expiry, data)
        self._lock = threading.Lock()

    def _lifetime(self, app: Flask) -> float:
        return app.permanent_session_lifetime.total_seconds()

    def _load(self, sid: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._store.get(sid)
            if entry is None:
                return None
            if entry[0] < time.monotonic():
                del self._store[sid]
                return None
            return dict(entry[1])

    def open_session(self, app: Flask, request: Request) -> ServerSession:
        sid = request.cookies.get(self.get_cookie_name(app), "")
        data = self._load(sid) if sid else None
        if data is None:
            return ServerSession(secrets.token_urlsafe(32), new=True)
        return ServerSession(sid, data)

    def adopt(self, session: ServerSession, sid: str) -> bool:
        """Make `session` the existing session `sid`: the cookie being set
        on this host then names the same data as the cookie on another
        (a sign-in moving from 127.0.0.1 to localhost)."""
        data = self._load(sid)
        if data is None:
            return False
        session.clear()
        session.update(data)
        session.sid = sid
        session.new = False
        session.modified = True
        return True

    def save_session(self, app: Flask, session: SessionMixin, response: Response) -> None:
        assert isinstance(session, ServerSession)
        name = self.get_cookie_name(app)
        if not session:
            # Nothing to keep: no entry, and no cookie unless one must go.
            with self._lock:
                self._store.pop(session.sid, None)
            if not session.new:
                response.delete_cookie(
                    name, domain=self.get_cookie_domain(app), path=self.get_cookie_path(app),
                )
            return

        now = time.monotonic()
        expiry = now + self._lifetime(app)
        with self._lock:
            if session.modified or session.sid not in self._store:
                self._store[session.sid] = (expiry, dict(session))
            else:
                # Unchanged: only slide the expiry, so a request that read
                # the session cannot overwrite what another one wrote since.
                self._store[session.sid] = (expiry, self._store[session.sid][1])
            if len(self._store) > MAX_SESSIONS:
                for stale in [s for s, (exp, _) in self._store.items() if exp < now]:
                    del self._store[stale]
                while len(self._store) > MAX_SESSIONS:
                    oldest = min(self._store, key=lambda s: self._store[s][0])
                    del self._store[oldest]

        response.set_cookie(
            name,
            session.sid,
            max_age=int(self._lifetime(app)),
            httponly=self.get_cookie_httponly(app),
            secure=self.get_cookie_secure(app),
            samesite=self.get_cookie_samesite(app),
            domain=self.get_cookie_domain(app),
            path=self.get_cookie_path(app),
        )
        response.vary.add("Cookie")
