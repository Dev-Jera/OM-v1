from src.error_handler import ErrorHandler


def test_handle_exception_returns_payload():
    eh = ErrorHandler()
    out = eh.handle_exception(Exception("boom"), context={"k": "v"})
    assert out["fallback"] is True
    assert "internal error" in out["message"].lower()
    assert "boom" in out["metadata"]["error"]
