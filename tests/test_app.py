"""UI smoke tests: drive the Streamlit app headlessly through the storyboard flows (replay, no API key)."""
from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")
APP = str(Path(__file__).resolve().parent.parent / "app" / "streamlit_app.py")


@pytest.fixture(autouse=True)
def _temp_logs(tmp_path, monkeypatch):
    """Keep test runs out of the real logs/ folder."""
    monkeypatch.setenv("SECOND_LOOK_LOG_DIR", str(tmp_path))
    import app.logger
    monkeypatch.setattr(app.logger, "LOG_DIR", tmp_path)


def start(scenario=None, mode=None):
    at = st_testing.AppTest.from_file(APP, default_timeout=60).run()
    if mode:
        [r for r in at.radio if r.label == "What the user sees"][0].set_value(mode).run()
    if scenario:
        box = [s for s in at.selectbox if s.label == "Replay scenario"][0]
        box.select_index([i for i, o in enumerate(box.options) if o.startswith(scenario)][0]).run()
    for label in ("Continue", "Confirm", "Get suggestions"):
        button(at, label).click().run()
    assert not at.exception, at.exception
    return at


def button(at, label, i=0):
    return [b for b in at.button if b.label.startswith(label)][i]


def cards(at):
    return [m.value for m in at.markdown if "**" in m.value and "·" in m.value]


def test_scenario_2_flags_remove_undo_regenerate_accept():
    at = start("scenario_2")
    assert [c.split("]")[0] for c in cards(at)] == [":red-background[Look again", ":orange-background[Review",
                                                    ":green-background[Checked"]
    assert any("within 5 years" in w.value for w in at.warning)  # H0
    button(at, "Remove").click().run()
    assert any(m.value.startswith("**Your plan after your changes") for m in at.markdown)
    button(at, "Undo").click().run()
    assert not any(m.value.startswith("**Your plan after your changes") for m in at.markdown)
    button(at, "Suggest again").click().run()
    assert all("Checked" in c for c in cards(at))
    button(at, "Accept").click().run()
    assert at.success and not at.exception


def test_scenario_3_profile_repair():
    at = start("scenario_3")
    button(at, "Update horizon years to 1").click().run()
    assert "1-year" in at.info[0].value
    button(at, "Confirm").click().run()
    assert not at.exception and all("Checked" in c for c in cards(at))


def test_disclaimer_mode_hides_checks():
    at = start("scenario_2", mode="disclaimer")
    assert all("background" not in c for c in cards(at))
    assert any("not financial advice" in i.value for i in at.info)
    assert not at.warning  # no H0 in the comparison condition
    assert [b.label for b in at.button].count("Remove") == 3


def test_live_groq_replay_shows_recorded_run():
    at = start("live_groq")
    assert sum("Review" in c for c in cards(at)) == 3
    assert any("Replay of a live run" in c.value for c in at.caption)


def test_checked_card_offers_why_only():
    at = start("scenario_1")  # F09 has a false claim (Review) and an unverifiable 'growth' claim
    labels = [b.label for b in at.button]
    assert labels.count("Why?") == 1 and labels.count("Remove") == 1 and labels.count("Keep anyway") == 1


def test_request_panel_reduced_without_explanation():
    at = start("scenario_4")
    assert any("at least 50% in technology" in m.value for m in at.markdown)
    assert any("did not say why" in w.value for w in at.warning)
    assert any("allows up to 30%" in c.value for c in at.caption)
    button(at, "Suggest again").click().run()
    assert any("Model's explanation (not checked)" in i.value for i in at.info)


def test_model_list_failure_falls_back_to_env(monkeypatch):
    import streamlit as st
    import app.llm_client

    def no_network(provider):
        raise ConnectionError("offline")
    monkeypatch.setattr(app.llm_client, "list_models", no_network)  # never call a real API in tests
    monkeypatch.setenv("GROQ_MODEL", "some-model")
    st.cache_data.clear()
    at = st_testing.AppTest.from_file(APP, default_timeout=60).run()
    [s for s in at.selectbox if s.label == "Model provider"][0].set_value("groq").run()
    assert not at.exception
    picker = [s for s in at.selectbox if s.label == "Model"][0]  # live list unknown -> verified list
    assert "openai/gpt-oss-120b" in picker.options and "allam-2-7b" not in picker.options


def test_model_picker_lists_only_verified_models_still_served(monkeypatch):
    import streamlit as st
    import app.llm_client
    # live list: two verified models, one unverified, one speech model; one verified model has been retired
    monkeypatch.setattr(app.llm_client, "list_models",
                        lambda p: ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "allam-2-7b"])
    monkeypatch.setenv("GROQ_MODEL", "qwen/qwen3.8-27b")
    st.cache_data.clear()
    at = st_testing.AppTest.from_file(APP, default_timeout=60).run()
    [s for s in at.selectbox if s.label == "Model provider"][0].set_value("groq").run()
    picker = [s for s in at.selectbox if s.label == "Model"][0]
    assert picker.options == ["openai/gpt-oss-120b", "qwen/qwen3.8-27b"]  # allam: unverified; gpt-oss-20b: retired
    assert picker.value == "qwen/qwen3.8-27b"


def test_keep_current_profile_gives_a_plan_not_a_loop():
    at = start("scenario_3")  # first model output proposes a profile change
    button(at, "Keep my current profile").click().run()
    assert not at.exception
    assert "10-year" in [m.value for m in at.markdown if m.value.startswith("**Profile:**")][0]
    assert cards(at), "a plan for the unchanged profile is shown"


def test_request_followed_but_over_profile_limit_is_not_shown_as_good():
    at = start("live_groq_v4_ai")  # 55% technology requested and given; medium profile allows 30% in one sector
    assert not at.success
    assert any("gives you what you asked for, but 55%" in w.value and "30%" in w.value for w in at.warning)
