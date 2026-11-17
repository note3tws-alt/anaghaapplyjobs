import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from jobbot import telegram_bot
from jobbot.db import DB


@pytest.fixture
def fake_telegram(monkeypatch):
    state = {"sent": [], "updates": [], "answers": []}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
            method = self.path.rsplit("/", 1)[-1]
            result = True
            if method == "sendMessage":
                state["sent"].append(body); result = {"message_id": len(state["sent"])}
            elif method == "getUpdates":
                result = [u for u in state["updates"] if u["update_id"] >= body.get("offset", 0)]
            elif method == "answerCallbackQuery":
                state["answers"].append(body["text"])
            out = json.dumps({"ok": True, "result": result}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(out)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("TELEGRAM_API_BASE", f"http://127.0.0.1:{srv.server_address[1]}")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "111")
    yield state
    srv.shutdown()


def test_send_and_approve_only_from_her_chat(fake_telegram):
    db = DB()
    a, _ = db.upsert_job({"job_key": "k1", "company": "Demo", "title": "Medical Coder", "url": "https://x"})
    db.set_status(a, "ready_for_review", "t")
    assert telegram_bot.send_review_requests(db) == 1
    assert telegram_bot.send_review_requests(db) == 0           # not sent twice
    sent = fake_telegram["sent"][0]
    assert sent["chat_id"] == "111" and sent["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == f"approve:{a}"
    fake_telegram["updates"] = [
        {"update_id": 5, "callback_query": {"id": "x", "data": f"approve:{a}", "message": {"message_id": 1, "chat": {"id": 999}}}},
    ]
    telegram_bot.process_updates(db)
    assert db.get_job(a)["status"] == "ready_for_review"         # stranger ignored
    fake_telegram["updates"] = [
        {"update_id": 6, "callback_query": {"id": "y", "data": f"approve:{a}", "message": {"message_id": 1, "chat": {"id": 111}}}},
    ]
    telegram_bot.process_updates(db)
    assert db.get_job(a)["status"] == "approved" and "Approved" in fake_telegram["answers"][-1]


def test_off_without_config(monkeypatch):
    assert not telegram_bot.configured()
    assert telegram_bot.send_review_requests(DB()) == 0
