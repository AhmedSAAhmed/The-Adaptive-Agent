from app.core.models import Assumption, Step
from app.core.world import AssumptionMonitor, FlapDetector, WorldModel


def test_assumption_ops() -> None:
    assert Assumption(key="k", op="in", value=["a", "b"]).holds("a") is True
    assert Assumption(key="k", op="in", value=["a", "b"]).holds("c") is False
    assert Assumption(key="k", op="gte", value="22:00").holds("21:00") is False
    assert Assumption(key="k", op="gte", value=6).holds(8) is True
    assert Assumption(key="k", op="eq", value=1).holds(None) is None  # unknown is not "broken"


def test_monitor_only_checks_changed_key_and_pending_steps() -> None:
    world = WorldModel({"order.X.status": "picked_up", "branch.b.open_until": "23:00"})
    done = Step(tool="t", status="done", assumptions=[Assumption(key="order.X.status", op="eq", value="preparing")])
    pending = Step(tool="t", assumptions=[Assumption(key="order.X.status", op="eq", value="preparing")])
    assert AssumptionMonitor.broken([done], world) == []
    assert len(AssumptionMonitor.broken([pending], world)) == 1
    assert AssumptionMonitor.broken([pending], world, only_key="branch.b.open_until") == []


def test_self_state_only_checked_at_precommit() -> None:
    world = WorldModel({"booking.active_hold": "olaya@20:00"})
    step = Step(tool="confirm_booking", assumptions=[Assumption(key="booking.active_hold", op="eq", value="king_fahd@20:00")])
    assert AssumptionMonitor.broken([step], world) == []
    assert len(AssumptionMonitor.broken([step], world, include_self=True)) == 1


def test_flap_detector() -> None:
    f = FlapDetector(window_s=30, threshold=3)
    for i, v in enumerate(["a", "b", "a", "b"]):
        f.record("k", v, now=100 + i)
    assert f.is_flapping("k")
    g = FlapDetector(window_s=30, threshold=3)
    for i, v in enumerate(["a", "b", "a", "b"]):
        g.record("k", v, now=100 + i * 20)  # slow changes fall out of the window
    assert not g.is_flapping("k")


def test_default_llm_chain_puts_groq_first(monkeypatch) -> None:
    from app import config

    monkeypatch.delenv("LLM_CHAIN", raising=False)
    for var in ("GROQ_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.setenv(var, "test-key")
    assert [p.name for p in config._providers()] == ["groq", "openrouter", "gemini"]
    monkeypatch.setenv("LLM_CHAIN", "gemini,groq")
    assert [p.name for p in config._providers()] == ["gemini", "groq"]
