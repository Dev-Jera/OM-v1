from src.fallback_handler import FallbackHandler


def test_suggest_topics_but_never_offer_human():
    fh = FallbackHandler()
    p = fh.generate_fallback("I have a claim", confidence=0.05)
    assert p["fallback"] is True
    assert p["offer_human"] is False
    assert "claims" in p["suggestions"]

    p2 = fh.generate_fallback("Tell me about product", confidence=0.4)
    assert p2["fallback"] is True
    assert p2["offer_human"] is False
