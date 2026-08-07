from src.followup_manager import FollowUpManager


def test_queue_and_retrieve_in_memory():
    f = FollowUpManager()
    state = {}
    f.queue_followup(state, "What product?")
    assert state.get("followups")
    next_q = f.get_next_followup(state)
    assert next_q == "What product?"
    assert state["followups"][0]["asked"] is True


def test_session_queue_and_get():
    class DummySM:
        def __init__(self):
            self.sessions = {}

        def get_session(self, sid):
            return self.sessions.get(sid)

        def update_session(self, sid, updates):
            s = self.sessions.setdefault(sid, {})
            s.update(updates)

    sm = DummySM()
    sm.sessions["s1"] = {}
    f = FollowUpManager()
    f.queue_followup_session("s1", sm, "Clarify?")
    q = f.get_next_followup_session("s1", sm)
    assert q == "Clarify?"
    # subsequent call returns None
    q2 = f.get_next_followup_session("s1", sm)
    assert q2 is None
