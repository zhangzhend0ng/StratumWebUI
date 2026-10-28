"""Stratum conversation harness — the agent LOOP lives HERE (spec §3/§6),
not in the page and not in server.py's HTTP layer.

Composition: server.py imports this module and injects every dependency
(TurnDeps) — this module imports NOTHING from server or the plugin (red
line, spec §2; grep-tested). _CHAT_LOCK discipline (red line): the model
HTTP segment is the ONLY locked stretch and the lock lives in server.py's
model_fn; tool execution and host waits below never take it.
"""

import json
import secrets
import threading
import time

MAX_STEPS = 6
MAX_CALLS = 8
HOST_CALL_TIMEOUT_S = 300.0
TURN_HISTORY_TURNS = 50
CONV_TTL_S = 1800.0
EVENT_LOG_KEEP = 400


class Conversation(object):
    """One user question's turn: an ordered event log (cursor = seq), the
    pending host-call slots, and done-state for stream close."""

    def __init__(self, question, token, history):
        self.id = secrets.token_hex(8)
        self.token = token
        self.question = question
        self.history = (history or [])[-TURN_HISTORY_TURNS:]
        self.events = []
        self.seq = 0
        self.cond = threading.Condition()
        self.done = False
        self.created = time.time()
        self.host_pending = {}

    def publish(self, type_, **kw):
        with self.cond:
            self.seq += 1
            ev = dict(kw)
            ev["seq"] = self.seq
            ev["type"] = type_
            self.events.append(ev)
            if len(self.events) > EVENT_LOG_KEEP:
                del self.events[:EVENT_LOG_KEEP // 2]
            self.cond.notify_all()
            return ev

    def events_since(self, cursor):
        return [e for e in self.events if e["seq"] > cursor]

    def reserve_host(self, call_id):
        slot = {"event": threading.Event(), "result": None}
        self.host_pending[call_id] = slot
        return slot

    def resolve_host(self, call_id, ok, result=None, error=None):
        slot = self.host_pending.get(call_id)
        if slot is None:
            return False
        slot["result"] = {"ok": bool(ok), "result": result, "error": error}
        slot["event"].set()
        return True

    def finish(self):
        with self.cond:
            self.done = True
            self.cond.notify_all()


class Store(object):
    """Conversations + one-time tickets. Tickets exist because EventSource
    cannot carry X-Stratum-UI (spec §6): a GET's only bearer is the ticket;
    poll rotation hands out a fresh one per response."""

    def __init__(self):
        self.lock = threading.Lock()
        self.convs = {}
        self.tickets = {}

    def create(self, question, token, history):
        conv = Conversation(question, token, history)
        with self.lock:
            self.convs[conv.id] = conv
        return conv

    def get(self, conv_id):
        with self.lock:
            return self.convs.get(conv_id)

    def issue_ticket(self, conv_id):
        t = secrets.token_hex(12)
        with self.lock:
            self.tickets[t] = conv_id
        return t

    def consume_ticket(self, ticket):
        with self.lock:
            return self.convs.get(self.tickets.pop(ticket, None))

    def sweep(self):
        now = time.time()
        with self.lock:
            dead = [cid for cid, c in self.convs.items()
                    if c.done and now - c.created > CONV_TTL_S]
            # crash residue: a turn that never finished but is far past any
            # budget (TTL*2 >> MAX_STEPS rounds); never drop live turns
            stuck = [cid for cid, c in self.convs.items()
                     if not c.done and now - c.created > 2 * CONV_TTL_S]
            for cid in dead + stuck:
                self.convs.pop(cid, None)
            self.tickets = {t: c for t, c in self.tickets.items()
                            if c in self.convs}


HARNESS_STORE = Store()
