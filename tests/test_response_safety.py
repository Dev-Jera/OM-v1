from src.utils.response_safety import looks_truncated, merge_continuation, strip_meta_lead_in


class TestLooksTruncated:
    def test_complete_sentence_is_not_truncated(self):
        assert looks_truncated("Old Mutual is a leading insurer in Uganda.") is False

    def test_empty_text_is_truncated(self):
        assert looks_truncated("") is True

    def test_dangling_and_is_truncated(self):
        assert looks_truncated(
            "Old Mutual offers a comprehensive range of financial services across East Africa, "
            "including insurance and"
        ) is True

    def test_dangling_connector_however_is_truncated(self):
        assert looks_truncated(
            "I understand you're having trouble logging into your self-service portal for the "
            "Unit Trust. Our available information doesn't specifically detail that. However"
        ) is True

    def test_dangling_although_is_truncated(self):
        assert looks_truncated(
            "The Balanced Fund allows flexible withdrawals, which means you can access your "
            "money when you need it, although"
        ) is True

    def test_unbalanced_bold_is_truncated(self):
        assert looks_truncated(
            "The Serenicare plan covers dental, optical, outpatient, and inpatient care across "
            "East Africa, including chronic conditions like diabetes and **HIV/AIDS"
        ) is True

    def test_short_reply_without_punctuation_is_fine(self):
        assert looks_truncated("You can pay via M-Pesa") is False


class TestMergeContinuation:
    def test_removes_overlap(self):
        base = "Old Mutual offers insurance and investment services"
        cont = "investment services across East Africa."
        merged = merge_continuation(base, cont)
        assert merged == "Old Mutual offers insurance and investment services across East Africa."

    def test_returns_base_when_cont_is_contained(self):
        base = "Old Mutual offers insurance and investment services."
        assert merge_continuation(base, "old mutual offers") == base

    def test_returns_base_when_cont_empty(self):
        base = "Old Mutual offers insurance."
        assert merge_continuation(base, "") == base

    def test_joins_without_separator_overlap(self):
        merged = merge_continuation(
            "Old Mutual offers a broad range of services. As a",
            " result, customers can access them under one group.",
        )
        assert merged == "Old Mutual offers a broad range of services. As a result, customers can access them under one group."


class TestStripMetaLeadIn:
    def test_removes_mid_reply_leak_and_trailing_however(self):
        text = (
            "I understand you're having trouble logging into your self-service portal for the "
            "Unit Trust. Our available information doesn't specifically detail a self-service "
            "portal for Unit Trusts or how to troubleshoot login issues for it. However"
        )
        stripped = strip_meta_lead_in(text)
        assert "available information" not in stripped
        assert "however" not in stripped.lower()
        assert stripped == (
            "I understand you're having trouble logging into your self-service portal for the Unit Trust."
        )

    def test_removes_leading_leak_and_dangling_connector(self):
        text = (
            "Our available information doesn't specifically detail monthly minimums. However, "
            "you can fund the Balanced Fund by direct debit, M-Pesa, cheque, or standing order."
        )
        stripped = strip_meta_lead_in(text)
        assert "available information" not in stripped
        assert stripped.startswith("You can fund the Balanced Fund")

    def test_removes_search_results_leak(self):
        text = (
            "Per the search results, the annual premium for travel insurance starts at UGX "
            "180,000. You can also add emergency evacuation."
        )
        stripped = strip_meta_lead_in(text)
        assert "search results" not in stripped
        assert stripped == "You can also add emergency evacuation."

    def test_removes_dangling_but_after_leak(self):
        text = (
            "We offer term life cover and whole life cover. Our available data shows a waiting "
            "period for pre-existing conditions. But"
        )
        stripped = strip_meta_lead_in(text)
        assert "available data" not in stripped
        assert stripped.endswith("whole life cover.")

    def test_clean_reply_unchanged(self):
        text = (
            "You can fund the Balanced Fund by direct debit, M-Pesa, cheque, or standing order - "
            "whichever suits you. Our published guide doesn't call out a fixed monthly minimum."
        )
        assert strip_meta_lead_in(text) == text

    def test_empty_input(self):
        assert strip_meta_lead_in("") == ""
