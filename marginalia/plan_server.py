"""A tiny HTTP endpoint on 127.0.0.1 for agents that can't run our command line:

    curl --data-binary @plan.md http://127.0.0.1:47321/plan/<project>            replace the project's plan
    curl --data-binary @- http://127.0.0.1:47321/plan/<project>/<category>       replace one category
    curl http://127.0.0.1:47321/plan/<project>                                   read it back (JSON)

Requests that carry an Origin header (sent by browsers) are refused, so a web page can't post to it.
"""
from __future__ import annotations

import json
import logging
from typing import Callable
from urllib.parse import unquote, urlsplit

from PySide6.QtCore import QCoreApplication, QEvent, QObject
from PySide6.QtNetwork import QHostAddress, QTcpServer, QTcpSocket

log = logging.getLogger(__name__)
MAX_BODY = 256 * 1024


class PlanServer(QObject):
    def __init__(self, on_plan: Callable[[dict], dict], on_read: Callable[[str], dict | None]):
        super().__init__()
        self._on_plan, self._on_read = on_plan, on_read
        self._server = QTcpServer(self)
        self._server.newConnection.connect(self._accept)
        self._buf: dict[QTcpSocket, bytes] = {}

    def listen(self, port: int) -> bool:
        self._server.close()
        if not port:
            return False
        ok = self._server.listen(QHostAddress.LocalHost, port)
        if not ok:
            log.warning('plan endpoint: cannot listen on 127.0.0.1:%s (%s)', port, self._server.errorString())
        return ok

    def port(self) -> int:
        return self._server.serverPort() if self._server.isListening() else 0

    def close(self) -> None:
        """Stop listening and drop open connections. Their deferred deletion is carried out now: deleting the
        server later would otherwise delete them a second time."""
        self._server.close()
        for s in list(self._buf):
            s.abort()
        self._buf.clear()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def _accept(self) -> None:
        while self._server.hasPendingConnections():
            s = self._server.nextPendingConnection()
            self._buf[s] = b''
            s.readyRead.connect(lambda s=s: self._read(s))
            s.disconnected.connect(lambda s=s: (self._buf.pop(s, None), s.deleteLater()))

    def _read(self, s: QTcpSocket) -> None:
        data = self._buf.get(s, b'') + bytes(s.readAll())
        self._buf[s] = data
        head, sep, body = data.partition(b'\r\n\r\n')
        if not sep:
            if len(data) > 16384:
                self._reply(s, 431, 'headers too large')
            return
        lines = head.decode('latin-1').split('\r\n')
        try:
            method, target, _ = lines[0].split(' ', 2)
        except ValueError:
            self._reply(s, 400, 'bad request')
            return
        headers = {k.strip().lower(): v.strip() for k, _, v in (ln.partition(':') for ln in lines[1:])}
        if 'origin' in headers:
            self._reply(s, 403, 'requests from web pages are not accepted')
            return
        length = int(headers.get('content-length') or 0)
        if length > MAX_BODY:
            self._reply(s, 413, 'too large')
            return
        if len(body) < length:
            return                                    # wait for the rest
        parts = [unquote(p) for p in urlsplit(target).path.split('/') if p]
        if not parts or parts[0] != 'plan' or len(parts) < 2:
            self._reply(s, 404, 'use /plan/<project>[/<category>]')
            return
        project, category = parts[1], (parts[2] if len(parts) > 2 else None)
        if method == 'GET':
            got = self._on_read(project)
            self._reply(s, 200 if got else 404, json.dumps(got or {}, ensure_ascii=False), 'application/json')
        elif method in ('POST', 'PUT'):
            text = body[:length].decode('utf-8', errors='replace')
            pid = headers.get('x-marginalia-pid', '')
            res = self._on_plan({'project': project, 'category': category, 'text': text,
                                 'pids': [int(pid)] if pid.isdigit() else [], 'agent': headers.get('user-agent', '')})
            self._reply(s, 200, json.dumps(res, ensure_ascii=False), 'application/json')
        else:
            self._reply(s, 405, 'GET or POST')

    def _reply(self, s: QTcpSocket, code: int, text: str, ctype: str = 'text/plain') -> None:
        reason = {200: 'OK', 400: 'Bad Request', 403: 'Forbidden', 404: 'Not Found', 405: 'Method Not Allowed',
                  413: 'Payload Too Large', 431: 'Request Header Fields Too Large'}.get(code, '')
        body = (text + '\n').encode()
        s.write(f'HTTP/1.1 {code} {reason}\r\nContent-Type: {ctype}; charset=utf-8\r\nContent-Length: {len(body)}'
                f'\r\nConnection: close\r\n\r\n'.encode() + body)
        s.flush()
        s.disconnectFromHost()
        self._buf.pop(s, None)
