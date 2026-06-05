"""Analytics: event recording / aggregation and the privacy guarantee that the
client IP is never stored — only a salted one-way hash.
"""
from __future__ import annotations

from colorplate.web import analytics


class _FakeReq:
    def __init__(self, xff=None, host=None):
        self.headers = {"x-forwarded-for": xff} if xff else {}
        self.client = type("C", (), {"host": host})() if host else None


def test_visitor_hash_is_one_way_and_stable():
    h = analytics._visitor_hash("203.0.113.7")
    assert h and h != "203.0.113.7"
    assert len(h) == 16
    assert analytics._visitor_hash("203.0.113.7") == h        # deterministic
    assert analytics._visitor_hash("203.0.113.8") != h        # IP-specific
    assert analytics._visitor_hash(None) is None


def test_client_ip_prefers_first_forwarded_hop():
    assert analytics.client_ip(_FakeReq(xff="9.9.9.9, 10.0.0.1")) == "9.9.9.9"
    assert analytics.client_ip(_FakeReq(host="127.0.0.1")) == "127.0.0.1"
    assert analytics.client_ip(None) is None


def test_record_and_stats(tmp_path, monkeypatch):
    monkeypatch.setattr(analytics, "_DB_PATH", str(tmp_path / "a.db"))
    analytics.init()
    analytics.record("detect", _FakeReq(host="1.1.1.1"), ext="svg")
    analytics.record("detect", _FakeReq(host="2.2.2.2"))
    analytics.record("generate", None, files=5)

    s = analytics.stats()
    assert s["total_events"] == 3
    assert s["totals_by_type"] == {"detect": 2, "generate": 1}
    assert s["unique_visitors_total"] == 2          # two distinct hashed IPs
    assert s["daily"] and s["daily"][0]["events"] >= 1


def test_record_never_raises(monkeypatch, tmp_path):
    """Analytics must never break a request, even if the DB write fails."""
    monkeypatch.setattr(analytics, "_DB_PATH", str(tmp_path / "x.db"))
    analytics.init()
    monkeypatch.setattr(analytics, "_connect", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    analytics.record("detect", None)                # should swallow the error
