"""
Conversational mode - RAG-powered free-form chat
"""

from typing import Any, Dict, List, Optional
from datetime import datetime, timezone, timedelta
import logging
import re
import time

logger = logging.getLogger(__name__)


def _time_greeting_eat() -> str:
    """Return 'Good morning', 'Good afternoon', or 'Good evening' in EAT (UTC+3)."""
    eat = timezone(timedelta(hours=3))
    hour = datetime.now(eat).hour
    if hour < 12:
        return "Good morning"
    elif hour < 18:
        return "Good afternoon"
    else:
        return "Good evening"


def _derive_name_from_email(email: str) -> Optional[str]:
    """Extract a human-readable first name from an email address.

    Examples:
        john.doe@company.com  → 'John'
        jane_smith@company.com → 'Jane'
        john@company.com       → 'John'
        info@company.com       → None (too generic)
    """
    local = (email or "").split("@")[0]
    parts = re.split(r"[._\-]+", local)
    skip = {"info", "admin", "support", "hello", "contact", "enquiry", "enquiries", "office", "team", "hr"}
    name_parts = [p for p in parts if p.isalpha() and p.lower() not in skip and len(p) > 1]
    if name_parts:
        return name_parts[0].capitalize()
    return None


def _is_greeting(message: str) -> bool:
    m = (message or "").strip().lower()
    if not m:
        return False
    # Keep it strict so we don't mis-classify real questions.
    return m in {"hi", "hello", "hey", "hey!", "hello!", "hi!", "good morning", "good afternoon", "good evening"}


def _is_memory_question(message: str) -> bool:
    """Recognize a visitor asking whether Mia remembers them.

    This is handled deterministically so personal identity never needs to
    be sent to the language model or reconstructed from conversation history.
    """
    m = (message or "").strip().lower()
    return bool(
        re.search(r"\b(do you still remember me|do you remember me|remember me|know my name)\b", m)
    )


def _random_greeting(name: str | None = None) -> str:
    """Return a varied greeting string from a curated list.
    
    Keeps the bot's opening tone fresh across sessions without
    altering any logic or guardrails. Includes user name when available.
    For new users (no name), avoids "Welcome back" phrasing.
    """
    # Treat empty string as None
    if not name:
        name = None
    if name:
        GREETING_VARIANTS = [
            f"Great to see you, {name}! How can I assist?",
            f"Welcome back, {name}! What can I help you with today?",
            f"Hi {name}! What's on your mind?",
            f"Good to see you again, {name}! What can I do for you?",
            f"Hey {name}! What's on your mind?",
        ]
    else:
        # For new users: no "Welcome back" phrasing
        GREETING_VARIANTS = [
            "Great to see you! How can I assist?",
            "Hi there! What's on your mind?",
            "Good to see you! What can I do for you?",
            "Hey! What's on your mind?",
            "Thanks for reaching out! How can I help?",
        ]
    return random.choice(GREETING_VARIANTS)


def _identity_question_kind(message: str) -> str | None:
    """Classify identity questions without sending them to the LLM."""
    m = (message or "").strip().lower()
    asks_mia = bool(re.search(r"\b(who are you|what are you|tell me about yourself)\b", m))
    asks_user = bool(
        re.search(
            r"\b(who am i|what(?:'s|s| is) my name|what are my names|do you know who i am)\b",
            m,
        )
    )
    if asks_mia and asks_user:
        return "both"
    if asks_mia:
        return "assistant"
    if asks_user:
        return "user"
    return None


# --------------------------------------------------------------------------- #
# Identity capture (greeting flow)
#
# When a new user greets us, Mia asks for their name and email. The name is
# never surfaced anywhere (masked as CLIENT_NAME_MASK); the email is stored on
# the user record and used for follow-up only.
# --------------------------------------------------------------------------- #
CLIENT_NAME_MASK = ":clients_name"
import random

IDENTITY_ASK_PROMPT = (
    "{time_greeting}, I'm Mia, your Old Mutual assistant. Could you share your email address "
    "so I can know you better and follow up with you if needed?"
)
IDENTITY_ASK_EMAIL_PROMPT = "Thanks! Could you also share your email address so we can follow up with you?"
IDENTITY_CONFIRMED_PROMPT = _random_greeting()
IDENTITY_WELCOME_BACK_PROMPT = _random_greeting()
ASSISTANT_IDENTITY_PROMPT = (
    "I'm Mia, your Old Mutual Uganda virtual assistant. I can help with our products, "
    "coverage, benefits, quotes, and support."
)
USER_IDENTITY_UNKNOWN_PROMPT = (
    "I don't know your name yet. Please share your email address so I can recognize you next time."
)

# --------------------------------------------------------------------------- #
# Conversation completion (goodbye flow)
#
# Before a conversation ends, Mia asks whether every question was answered so
# we can label the conversation as resolved or unresolved (honest outcome data
# instead of inferring resolution from escalations alone).
# --------------------------------------------------------------------------- #
COMPLETION_ASK_PROMPT = "Did I answer everything you needed today?"
COMPLETION_RESOLVED_PROMPT = "Great to hear! If you have anything else, I'm here for you."
COMPLETION_UNRESOLVED_PROMPT = (
    "I'm sorry I couldn't help with everything. Would you like me to connect you with a human agent?"
)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _extract_email(text: Optional[str]) -> Optional[str]:
    m = _EMAIL_RE.search(text or "")
    return m.group(0) if m else None


def _extract_name(text: Optional[str], email: Optional[str] = None) -> Optional[str]:
    t = (text or "").strip()
    if email:
        t = t.replace(email, " ")
    t = re.sub(r"[,.;:!?]+", " ", t).strip()
    m = re.search(r"\b(?:my name is|i am|i'm|call me)\s+([A-Za-z][A-Za-z' -]{1,50})", t, re.IGNORECASE)
    if m:
        candidate = re.split(r"\s+and\s+", m.group(1).strip(), flags=re.IGNORECASE)[0].strip()
        if candidate:
            return candidate[:60]
    tokens = [
        tok
        for tok in re.split(r"\s+", t)
        if tok and re.fullmatch(r"[A-Za-z][A-Za-z'.-]*", tok)
        and tok.lower() not in {"my", "name", "is", "am", "i", "email", "address", "the", "and", "to"}
    ]
    if tokens:
        return " ".join(tokens[:2])[:60]
    return None


def _looks_like_question(text: Optional[str]) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    low = t.lower()
    if t.endswith("?"):
        return True
    if any(
        low.startswith(w)
        for w in (
            "what", "how", "why", "which", "when", "where",
            "can ", "tell", "give", "do you", "is there", "are there",
            "explain", "recommend", "i need", "i want",
        )
    ):
        return True
    return len(t) > 70


def _detect_section_intent(message: str) -> str | None:
    m = (message or "").lower()
    # Benefits
    if any(k in m for k in ["benefit", "benefits", "advantages", "what do i get", "what do you cover"]):
        return "show_benefits"
    # Coverage
    if any(k in m for k in ["coverage", "covered", "what is covered", "what's covered", "what is included", "included"]):
        return "show_coverage"
    # Exclusions
    if any(k in m for k in ["exclusion", "exclusions", "not covered", "what is not covered", "what isn't covered", "limitations"]):
        return "show_exclusions"
    # Eligibility
    if any(k in m for k in ["eligibility", "eligible", "qualify", "requirements", "who can apply", "who is it for"]):
        return "show_eligibility"
    # Pricing
    if any(k in m for k in ["premium", "price", "pricing", "cost", "how much"]):
        return "show_pricing"
    return None


def _detect_digital_flow(message: str) -> str | None:
    m = (message or "").lower()
    if any(k in m for k in ["personal accident", "pa cover", "accident insurance", "accident cover", "pa insurance"]):
        return "personal_accident"
    if any(k in m for k in ["serenicare"]):
        return "serenicare"
    if any(k in m for k in ["motor private", "car insurance", "vehicle insurance", "motor insurance"]):
        return "motor_private"
    if any(k in m for k in ["travel insurance", "travel sure", "travel cover", "travel policy"]):
        return "travel_insurance"
    return None


def _digital_flow_search_hint(digital_flow: str | None) -> str | None:
    if digital_flow == "motor_private":
        return "Motor Insurance"
    if digital_flow == "travel_insurance":
        return "Travel Insurance"
    if digital_flow == "personal_accident":
        return "Personal Accident"
    if digital_flow == "serenicare":
        return "Serenicare"
    return None


def _resolve_doc_ids_for_digital_flow(product_matcher: Any, digital_flow: str | None, *, max_results: int = 2) -> List[str]:
    """Resolve likely product doc_ids for a detected guided flow.

    This is a fallback path when lexical product matching misses short queries
    like "car insurance" but we can still detect the intended flow.
    """
    if not digital_flow or product_matcher is None:
        return []

    direct_aliases = [
        digital_flow,
        digital_flow.replace("_", "-"),
        digital_flow.replace("_", " "),
    ]
    resolved: List[str] = []
    for alias in direct_aliases:
        try:
            if hasattr(product_matcher, "resolve_doc_id"):
                doc_id = product_matcher.resolve_doc_id(alias)
                if doc_id and doc_id not in resolved:
                    resolved.append(doc_id)
        except Exception:
            # Best effort only; continue with index-scoring fallback.
            continue
    if resolved:
        return resolved[:max_results]

    index = getattr(product_matcher, "product_index", None)
    if not isinstance(index, dict) or not index:
        return []

    alias_map: Dict[str, List[str]] = {
        "motor_private": ["motor private", "motor insurance", "car insurance", "vehicle insurance", "motor-insurance"],
        "travel_insurance": ["travel insurance", "travel sure", "travel policy", "travel cover"],
        "personal_accident": ["personal accident", "accident insurance", "accident cover", "pa cover"],
        "serenicare": ["serenicare", "health insurance", "medical cover"],
    }
    penalties: Dict[str, List[str]] = {
        # Prevent "car insurance" from drifting to business/commercial products.
        "motor_private": ["commercial", "business"],
    }

    candidates: List[tuple[int, str]] = []
    aliases = alias_map.get(digital_flow, [digital_flow.replace("_", " ")])
    negative_terms = penalties.get(digital_flow, [])

    for item in index.values():
        if not isinstance(item, dict):
            continue
        doc_id = item.get("doc_id") or item.get("product_id")
        if not doc_id:
            continue

        haystack = " ".join(
            [
                str(item.get("name") or ""),
                str(item.get("slug") or ""),
                str(item.get("product_key") or ""),
                str(item.get("doc_id") or ""),
            ]
        ).lower()
        score = 0
        for alias in aliases:
            alias_l = alias.lower()
            if alias_l and alias_l in haystack:
                score += 4 if " " in alias_l else 2
        for bad in negative_terms:
            if bad in haystack:
                score -= 3
        if score > 0:
            candidates.append((score, str(doc_id)))

    candidates.sort(key=lambda pair: pair[0], reverse=True)
    for _, doc_id in candidates:
        if doc_id not in resolved:
            resolved.append(doc_id)
        if len(resolved) >= max_results:
            break
    return resolved


def _is_broad_product_query(message: str) -> bool:
    m = (message or "").lower()
    if not m:
        return False
    broad_markers = [
        "policies",
        "policy",
        "options",
        "products",
        "plans",
        "covers",
        "types of",
        "available",
    ]
    if any(k in m for k in broad_markers):
        return True
    if "can i get" in m and any(k in m for k in ["insurance", "cover", "policy"]):
        return True
    return False


def _is_affirmative(message: str) -> bool:
    m = (message or "").strip().lower()
    if not m:
        return False

    exact_matches = {"yes", "y", "yeah", "yep", "sure", "ok", "okay", "please", "go ahead", "go on"}
    if m in exact_matches:
        return True

    affirmative_prefixes = (
        "yes ",
        "yeah ",
        "yep ",
        "sure ",
        "ok ",
        "okay ",
        "please ",
        "go ahead ",
        "go on ",
    )
    if m.startswith(affirmative_prefixes):
        return True

    share_phrases = {
        "share",
        "share it",
        "share them",
        "share that",
        "please share",
        "show me",
        "show them",
        "tell me",
        "tell me more",
    }
    return m in share_phrases


def _is_negative(message: str) -> bool:
    m = (message or "").strip().lower()
    return m in {"no", "n", "nope", "not now", "later", "maybe later"}


# Explicit user request to talk to a human agent (spec condition "user asks").
# Deliberately narrow so ordinary chat never trips it: the user must actually
# ask to speak/connect with an agent/representative/human.
_AGENT_REQUEST_RE = re.compile(
    r"(?:"
    r"\b(talk|speak|chat|see|reach|contact)\b[^.!?\n]{0,40}\b(agent|representative|advisor|human)\b"
    r"|"
    r"\b(connect|transfer|put|get)\b[^.!?\n]{0,20}\b(agent|representative|advisor|human|person)\b"
    r"|"
    r"\b(human|live|real|actual)\s+(agent|representative|advisor)\b"
    r"|"
    r"\b(i want|i need|i would like|i'd like|i wish|please)\b[^.!?\n]{0,30}\b(agent|representative|advisor)\b"
    r"|"
    r"\b(speak|talk)\s+to\s+(someone|a human)\b"
    r")",
    re.IGNORECASE,
)


def _is_agent_request(message: str) -> bool:
    """True when the user explicitly asks to be connected to a human agent."""
    m = (message or "").strip().lower()
    if not m:
        return False
    # Refusals / complaints about agents must never escalate.
    if re.search(r"\b(don'?t|do not|won'?t|will not|can'?t|cannot|not)\s+(want|need|wish|like)\b", m):
        return False
    if re.search(r"\b(no need|no thanks|never|stop)\b", m):
        return False
    return bool(_AGENT_REQUEST_RE.search(m))


def _is_explicit_guided_intent(message: str) -> bool:
    m = (message or "").strip().lower()
    if not m:
        return False
    explicit_triggers = [
        "get a quote",
        "get a quotation",
        "get quotation",
        "can i get a quote",
        "can i get a quotation",
        "can i get quotation",
        "give me a quote",
        "provide a quote",
        "i want to apply",
        "i want to buy",
        "i want to purchase",
        "help me apply",
        "help me buy",
    ]
    if any(trigger in m for trigger in explicit_triggers):
        return True

    wants_quote = any(word in m for word in ["want", "need", "get"]) and any(word in m for word in ["quote", "quotation"])
    wants_purchase = any(word in m for word in ["want", "need", "help me", "can i"]) and any(word in m for word in ["apply", "buy", "purchase"])
    return wants_quote or wants_purchase


def _has_confident_product_switch(products: List[Any], topic: Dict[str, Any]) -> bool:
    """Detect when the user has clearly moved to a different product topic."""
    if not products or not topic or not topic.get("doc_id"):
        return False

    top_score = float(products[0][0] or 0.0)
    second_score = float(products[1][0] or 0.0) if len(products) > 1 else 0.0
    is_confident = (top_score >= 1.2) and (top_score >= second_score + 0.5)
    top_doc_id = products[0][2].get("product_id") or products[0][2].get("doc_id")
    return bool(is_confident and top_doc_id and top_doc_id != topic.get("doc_id"))


def _should_reuse_product_topic(message: str, topic: Dict[str, Any]) -> bool:
    if not topic or not topic.get("doc_id"):
        return False

    m = (message or "").strip().lower()
    if not m or _detect_digital_flow(m):
        return False

    if _detect_section_intent(m):
        return True

    contextual_phrases = [
        "what about",
        "how about",
        "what if",
        "tell me more",
        "more about",
        "is it",
        "does it",
        "can it",
        "would it",
        "that one",
        "this one",
        "what else",
        "how much is it",
        "is it expensive",
        "waiting period",
    ]
    if any(phrase in m for phrase in contextual_phrases):
        return True

    if re.search(r"\b(it|this|that|they|them|those|these)\b", m):
        return True

    follow_up_keywords = [
        "benefits",
        "coverage",
        "covered",
        "exclusions",
        "eligibility",
        "premium",
        "pricing",
        "price",
        "cost",
        "claim",
        "claims",
        "limit",
        "limits",
    ]
    tokens = re.findall(r"\b[\w']+\b", m)
    return len(tokens) <= 8 and any(keyword in m for keyword in follow_up_keywords)


def _augment_query_with_topic(message: str, topic_name: Optional[str], *, use_topic: bool) -> str:
    if not use_topic or not topic_name:
        return message

    topic_lower = topic_name.lower()
    message_lower = (message or "").lower()
    if topic_lower in message_lower:
        return message
    return f"{topic_name} {message}".strip()


def _is_followup_message(message: str) -> bool:
    m = (message or "").strip().lower()
    if not m:
        return False
    if _is_greeting(m):
        return False

    followup_starts = (
        "and ",
        "also ",
        "what about",
        "how about",
        "what if",
        "then ",
    )
    if m.startswith(followup_starts):
        return True

    clarification_patterns = (
        r"\bwhat do you mean\b",
        r"\bwhat did you mean\b",
        r"\bwhat does .{1,40}?\bmean\b",
        r"\bwhat is meant by\b",
        r"\bmeaning of\b",
        r"\bcan you explain\b",
        r"\bcould you explain\b",
        r"^explain\b",
        r"\bclarify\b",
        r"\belaborate\b",
        r"\bi don'?t understand\b",
        r"\bin other words\b",
    )
    if any(re.search(p, m) for p in clarification_patterns):
        return True

    if re.search(r"\b(it|this|that|they|them|those|these)\b", m):
        return True

    tokens = re.findall(r"\b[\w']+\b", m)
    if len(tokens) <= 7 and any(k in m for k in ["waiting period", "limit", "limits", "eligible", "price", "cost", "premium"]):
        return True

    return False


def _last_user_turn(conversation_history: List[Dict[str, Any]]) -> Optional[str]:
    for msg in reversed(conversation_history or []):
        role = (msg.get("role") or "").strip().lower()
        content = (msg.get("content") or "").strip()
        if role == "user" and content:
            return content
    return None


def _last_assistant_turn(conversation_history: List[Dict[str, Any]]) -> Optional[str]:
    for msg in reversed(conversation_history or []):
        role = (msg.get("role") or "").strip().lower()
        content = (msg.get("content") or "").strip()
        if role == "assistant" and content:
            return content
    return None


_AUGMENT_ASSISTANT_CHARS = 400


def _augment_query_with_history(message: str, conversation_history: List[Dict[str, Any]], *, use_history: bool) -> str:
    if not use_history:
        return message

    previous_user_turn = _last_user_turn(conversation_history)
    previous_assistant_turn = _last_assistant_turn(conversation_history)
    if not previous_user_turn and not previous_assistant_turn:
        return message

    lowered = message.lower()
    if previous_user_turn and previous_user_turn.lower() in lowered:
        return message

    parts = []
    if previous_user_turn:
        parts.append(f"user previously asked: {previous_user_turn}")
    if previous_assistant_turn:
        condensed = " ".join(previous_assistant_turn.split())
        if len(condensed) > _AUGMENT_ASSISTANT_CHARS:
            condensed = condensed[: _AUGMENT_ASSISTANT_CHARS - 3].rstrip() + "..."
        parts.append(f"assistant answered: {condensed}")
    context_text = "; ".join(parts)
    return f"Context - {context_text}. Follow-up question: {message}"


def _is_fallback_like_answer(answer: str) -> bool:
    lowered = (answer or "").strip().lower()
    if not lowered:
        return True
    fallback_markers = [
        "i'm having trouble retrieving",
        "i am having trouble retrieving",
        "i'm not sure based on the available information",
        "please try again in a moment",
        "please rephrase",
        "can't answer that",
        "cannot answer that",
        "i can't answer that",
        "connect you with an agent",
        "connect you to an agent",
        "not covered in our published guide",
    ]
    return any(marker in lowered for marker in fallback_markers)


def _is_incomplete_smalltalk_reply(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return True

    tokens = re.findall(r"\b[\w']+\b", cleaned.lower())
    if not tokens:
        return True

    dangling_last_words = {
        "to",
        "for",
        "with",
        "about",
        "and",
        "or",
        "the",
        "a",
        "an",
        "of",
        "our",
        "your",
    }
    if tokens[-1] in dangling_last_words:
        return True

    if len(tokens) <= 4 and cleaned[-1] not in ".!?":
        return True

    return False


def _estimate_response_confidence(
    response: Dict[str, Any],
    retrieval_results: List[Dict[str, Any]],
    products: List[Any],
    filters: Dict[str, Any],
) -> float:
    answer = (response.get("answer") or "").strip()
    response_conf = response.get("confidence")

    if isinstance(response_conf, (int, float)):
        confidence = float(response_conf)
    else:
        if retrieval_results:
            scores = [float(h.get("score") or 0.0) for h in retrieval_results]
            avg_score = sum(scores) / len(scores) if scores else 0.0
            coverage = min(len(retrieval_results) / 5.0, 1.0)
        else:
            avg_score = 0.0
            coverage = 0.0

        min_score = 0.55
        if avg_score <= 0:
            score_norm = 0.0
        else:
            score_norm = (avg_score - min_score) / max(1.0 - min_score, 0.01)
            score_norm = max(0.0, min(1.0, score_norm))

        confidence = (0.7 * score_norm) + (0.3 * coverage)

    if _is_fallback_like_answer(answer):
        confidence = min(confidence, 0.25)
    elif not retrieval_results:
        confidence = min(confidence, 0.35)

    return round(max(0.05, min(confidence, 0.95)), 2)


def _build_section_query(product_name: str, section: str) -> str:
    base = product_name or "this insurance product"
    if section == "show_benefits":
        return f"List the key benefits of {base}. Keep it clear and structured."
    if section == "show_eligibility":
        return f"Explain eligibility requirements for {base}. Include who it is for and common requirements."
    if section == "show_coverage":
        return f"Explain what is covered under {base}. Provide a clear coverage summary."
    if section == "show_exclusions":
        return f"Explain common exclusions and what is not covered for {base}."
    if section == "show_pricing":
        return f"Explain how pricing/premiums work for {base}. If exact prices are not available, explain the factors that affect cost."
    return f"Explain {base} insurance product, its benefits, coverage, and eligibility."


def _build_overview_query(product_name: str) -> str:
    base = product_name or "this insurance product"
    return f"Explain {base} insurance product, its benefits, coverage, and eligibility."


def _build_product_aware_clarification(topic_name: Optional[str]) -> str:
    base = (topic_name or "this product").strip()
    return (
        f"Are you still asking about {base}? "
        f"I can help with its benefits, coverage, exclusions, eligibility, or pricing."
    )


def _build_product_choice_clarification(topic_label: Optional[str], options: List[str]) -> str:
    clean_options = [str(option).strip() for option in (options or []) if str(option).strip()]
    base = (topic_label or "that area").strip()
    if clean_options:
        choices = ", ".join(clean_options[:4])
        return f"Which {base} option do you mean? I can tell you more about {choices}."
    return f"Which {base} product do you mean? Tell me the option you want more detail on."


def _is_ambiguous_motor_query(message: str) -> bool:
    m = (message or "").strip().lower()
    if not m:
        return False

    mentions_motor = any(term in m for term in ["motor", "car", "vehicle", "auto"])
    if not mentions_motor:
        return False

    explicit_motor_products = [
        "motor private",
        "motor commercial",
        "private motor",
        "commercial motor",
        "private vehicle",
        "commercial vehicle",
        "trucksure",
        "general cartage",
        "own goods",
        "passenger service vehicle",
        "psv",
        "tractor",
    ]
    if any(term in m for term in explicit_motor_products):
        return False

    ambiguous_triggers = [
        "motor insurance",
        "motor cover",
        "motor accident",
    ]
    return any(term in m for term in ambiguous_triggers)


def _is_vague_selection_reply(message: str) -> bool:
    m = (message or "").strip().lower()
    return m in {
        "any",
        "none",
        "neither",
        "either",
        "those",
        "these",
        "that",
        "them",
    }


def _build_vague_selection_clarification() -> str:
    return (
        "Could you clarify what you mean? "
        "If none of those options fit, tell me the type of cover you want, or name the product you want to know more about."
    )


def _infer_recommendation_hint(message: str) -> str | None:
    m = (message or "").lower()
    if "accident" in m:
        return "personal accident"
    if any(k in m for k in ["travel", "trip"]):
        return "travel insurance"
    if any(k in m for k in ["motor", "car", "vehicle", "auto"]):
        return "motor private"
    if any(k in m for k in ["medical", "health", "hospital"]):
        return "serenicare"
    return None


def _next_section_offer(action: str, *, is_digital: bool) -> tuple[str | None, str | None]:
    order = {
        "show_benefits": ("show_eligibility", "eligibility"),
        "show_eligibility": ("show_coverage", "coverage"),
        "show_coverage": ("show_exclusions", "exclusions"),
        "show_exclusions": ("show_pricing", "pricing"),
        "show_pricing": ("get_quote", "a quick quote") if is_digital else ("how_to_access", "how to access it"),
    }
    return order.get(action, (None, None))


# metrics functions
def _emit_metrics(db, metrics: list[Dict[str, Any]]) -> None:
    if db is None:
        return
    if not metrics:
        return
    try:
        from datetime import datetime
        if hasattr(db, "add_rag_metrics"):
            now = datetime.utcnow()
            for metric in metrics:
                metric.setdefault("created_at", now)
            db.add_rag_metrics(metrics)
        elif hasattr(db, "add_rag_metric"):
            now = datetime.utcnow()
            for metric in metrics:
                metric.setdefault("created_at", now)
                db.add_rag_metric(**metric)
        else:
            logger.warning("[metrics] DB adapter missing add_rag_metrics; count=%s", len(metrics))
    except Exception as exc:
        logger.warning("[metrics] Failed to record metrics: %s", exc)


def _metric_payload(metric_type: str, value: float, conversation_id: Optional[str]) -> Dict[str, Any]:
    return {
        "metric_type": metric_type,
        "value": float(value),
        "conversation_id": conversation_id,
    }


class ConversationalMode:
    def __init__(self, rag_system, product_matcher, state_manager, brain=None, intent_router=None):
        self.rag = rag_system
        self.product_matcher = product_matcher
        self.state_manager = state_manager
        self.brain = brain

        # Optional LLM-based intent router (LLM-first greeting vs OM-question).
        # Wired explicitly by the app; None keeps the legacy/brain fallback path.
        self.intent_router = intent_router

        # Optional LLM-based small-talk responder.
        try:
            from src.chatbot.intent_classifier import SmallTalkResponder

            self.small_talk_responder = SmallTalkResponder()
        except Exception:
            self.small_talk_responder = None

        # Lazily import response processor to avoid circular imports at module load time
        try:
            from src.response_processor import ResponseProcessor

            self.response_processor = ResponseProcessor(state_manager=self.state_manager)
        except Exception:
            # Fallback: no response processor available
            self.response_processor = None

    async def process(self, message: str, session_id: str, user_id: str, form_data: Optional[Dict[str, Any]] = None, db=None) -> Dict:
        """Process message in conversational mode"""
        start_time = time.time()

        if db is None:
            db = getattr(self.state_manager, "db", None)

        session_for_id = self.state_manager.get_session(session_id) or {}
        conversation_id: Optional[str] = session_for_id.get("conversation_id") or session_id

        # Backward-compatible: if the frontend still sends a product-guide action via form_data,

        # Backward-compatible: if the frontend still sends a product-guide action via form_data,
        # handle it, but we no longer *emit* buttons/actions as the primary UX.
        if form_data and isinstance(form_data, dict) and form_data.get("action"):
            return await self._process_product_guide_action(form_data, session_id)

        # Handle pending agent handoff confirmation (ask -> wait for yes/no).
        pending_ctx = dict((session_for_id.get("context") or {}))
        if pending_ctx.get("pending_agent_offer"):
            if _is_affirmative(message):
                pending_ctx.pop("pending_agent_offer", None)
                self.state_manager.update_session(session_id, {"context": pending_ctx})
                try:
                    from src.integrations.policy.escalation_service import EscalationService

                    EscalationService(state_manager=self.state_manager).escalate_to_human(
                        session_id=session_id,
                        reason="user_requested_agent",
                        user_id=user_id,
                        metadata={"conversation_id": conversation_id},
                    )
                except Exception:
                    self.state_manager.mark_escalated(
                        session_id,
                        reason="user_requested_agent",
                        metadata={"conversation_id": conversation_id},
                    )
                if conversation_id and hasattr(self.state_manager.db, "add_conversation_event"):
                    try:
                        self.state_manager.db.add_conversation_event(
                            conversation_id=conversation_id,
                            event_type="escalation_confirmed",
                            payload={"source": "user", "reason": "user_requested_agent"},
                        )
                        from src.chatbot.paths import record_conversation_path
                        record_conversation_path(
                            self.state_manager.db, conversation_id, "direct_agent", "keyword"
                        )
                    except Exception:
                        pass
                return {
                    "mode": "escalated",
                    "response": "Message sent to human agent.",
                    "escalated": True,
                    "agent_id": None,
                }
            if _is_negative(message):
                pending_ctx.pop("pending_agent_offer", None)
                self.state_manager.update_session(session_id, {"context": pending_ctx})
                return {
                    "mode": "conversational",
                    "response": "No problem. Any other question you would like me to help you with?",
                    "confidence": 1.0,
                }
            # If user says something else, clear the pending offer and continue normally.
            if (message or "").strip():
                pending_ctx.pop("pending_agent_offer", None)
                self.state_manager.update_session(session_id, {"context": pending_ctx})

        # Explicit request to talk to a human agent: escalate directly. The user
        # asked for it, so no further confirmation is needed.
        if form_data is None and _is_agent_request(message):
            try:
                from src.integrations.policy.escalation_service import EscalationService

                EscalationService(state_manager=self.state_manager).escalate_to_human(
                    session_id=session_id,
                    reason="user_requested_agent",
                    user_id=user_id,
                    metadata={"conversation_id": conversation_id},
                )
            except Exception:
                self.state_manager.mark_escalated(
                    session_id,
                    reason="user_requested_agent",
                    metadata={"conversation_id": conversation_id},
                )
            if conversation_id and hasattr(self.state_manager.db, "add_conversation_event"):
                try:
                    self.state_manager.db.add_conversation_event(
                        conversation_id=conversation_id,
                        event_type="escalation_confirmed",
                        payload={"source": "user", "reason": "user_requested_agent"},
                    )
                    from src.chatbot.paths import record_conversation_path

                    record_conversation_path(
                        self.state_manager.db, conversation_id, "direct_agent", "keyword"
                    )
                except Exception:
                    pass
            return {
                "mode": "escalated",
                "response": "Message sent to human agent.",
                "escalated": True,
                "agent_id": None,
            }

        escalation_state = self.state_manager.get_escalation_state(session_id)
        if escalation_state.get("escalated"):
            logger.info(f"Routing message to human agent for session {session_id}")
            agent_id = escalation_state.get("agent_id")
            status_msg = "Message sent to human agent."
            if agent_id:
                status_msg = f"Message sent to human agent ({agent_id})."
            return {
                "mode": "escalated",
                "response": status_msg,
                "escalated": True,
                "agent_id": agent_id,
            }

        # Path attribution: a normal (non-escalated) user message here is a
        # freeform chat. First path for the conversation wins.
        if (message or "").strip():
            try:
                from src.chatbot.paths import record_conversation_path
                record_conversation_path(db, conversation_id, "freeform", "chat")
            except Exception:
                pass

        # Completion question: if we asked "did I answer everything?", interpret
        # the reply as resolved / unresolved / keep chatting.
        if form_data is None:
            completion_response = self._maybe_handle_completion_question(
                message, session_id, conversation_id, db
            )
            if completion_response is not None:
                return completion_response

        # Identity capture: when a new user greets, ask for name + email (once).
        # Runs only for normal (non-escalated) conversations.
        if form_data is None:
            capture_response = self._maybe_handle_identity_capture(
                message, session_id, user_id, conversation_id, session_for_id, db, start_time
            )
            if capture_response is not None:
                return capture_response

        # If we previously offered to share a section (e.g., benefits) and the user replies "yes",
        # convert that into the corresponding section answer.
        session = self.state_manager.get_session(session_id) or {}
        ctx = dict(session.get("context") or {})
        pending_offer = ctx.get("pending_section_offer")
        if pending_offer:
            if _is_affirmative(message):
                ctx.pop("pending_section_offer", None)
                self.state_manager.update_session(session_id, {"context": ctx})
                return await self._process_product_guide_action({"action": str(pending_offer)}, session_id)
            if _is_negative(message):
                ctx.pop("pending_section_offer", None)
                self.state_manager.update_session(session_id, {"context": ctx})

        pending_choice = ctx.get("pending_product_choice")
        if pending_choice:
            if _is_affirmative(message):
                return {
                    "mode": "conversational",
                    "response": _build_product_choice_clarification(
                        pending_choice.get("topic_label"),
                        pending_choice.get("options") or [],
                    ),
                    "intent": "clarify_product",
                    "confidence": 0.9,
                }
            if _is_negative(message):
                ctx.pop("pending_product_choice", None)
                self.state_manager.update_session(session_id, {"context": ctx})

        # LLM-first intent routing: the LLM decides whether this is casual chat
        # (greeting/small-talk/thanks/goodbye/off-topic) or a real Old Mutual
        # question. Casual chat is answered here, skipping RAG entirely; Old
        # Mutual questions fall through to the brain / keyword RAG below and are
        # expected to be answered ONLY from retrieved chunks.
        require_grounding = False
        if form_data is None:
            session = self.state_manager.get_session(session_id) or {}
            ctx = dict(session.get("context") or {})
            pending_state = bool(
                ctx.get("pending_agent_offer")
                or ctx.get("pending_section_offer")
                or ctx.get("pending_product_choice")
                or ctx.get("pending_quote_offer")
            )
            if not pending_state:
                routed = await self._route_intent(message)
                if routed is not None and routed[0] == "REPLY":
                    label, llm_reply = routed[1], routed[2]
                    return self._build_no_retrieval_response(
                        kind=label,
                        answer_text=llm_reply or self._build_no_retrieval_reply(label),
                        message=message,
                        session_id=session_id,
                        user_id=user_id,
                        conversation_id=conversation_id,
                        db=db,
                        start_time=start_time,
                    )
                if routed is not None and routed[0] == "PASSTHROUGH":
                    require_grounding = bool(routed[1])

        # Conversational brain: free-text messages route through the brain when
        # it is attached and usable. If the brain returns None (disabled or
        # unavailable) we fall through to the keyword/RAG pipeline below.
        if form_data is None and self.brain is not None:
            brain_payload = await self._process_with_brain(
                message, session_id, user_id, conversation_id, db, start_time,
                require_grounding=require_grounding,
            )
            if brain_payload is not None:
                return brain_payload

        # If the user is explicitly asking for a product section (benefits/coverage/etc),
        # resolve the product and answer via the product-guide path (filters by doc_id).
        if form_data is None:
            section_action = _detect_section_intent(message)
            if section_action:
                products = self.product_matcher.match_products(message, top_k=1)

                # Prefer explicit mention in message, else fall back to last product topic.
                session = self.state_manager.get_session(session_id) or {}
                ctx = dict(session.get("context") or {})

                picked = products[0][2] if products else None
                if picked:
                    ctx["product_topic"] = {
                        "digital_flow": _detect_digital_flow(message),
                        "name": picked.get("name"),
                        "doc_id": picked.get("product_id"),
                        "url": picked.get("url"),
                    }
                    self.state_manager.update_session(session_id, {"context": ctx})

                # If we still don't know which product, ask a single clarifying question.
                topic = (ctx.get("product_topic") or {}) if isinstance(ctx, dict) else {}
                if not topic.get("doc_id"):
                    if topic.get("name"):
                        return {
                            "mode": "conversational",
                            "response": _build_product_aware_clarification(topic.get("name")),
                            "intent": "clarify_section",
                            "confidence": 0.9,
                        }
                    return {
                        "mode": "conversational",
                        "response": (
                            "Sure 🙂 Which product do you mean?\n"
                            "Examples: ✈️ Travel Sure Plus, 🩹 Personal Accident, 🏥 Serenicare, 🚗 Motor Private."
                        ),
                        "intent": "clarify_product",
                        "confidence": 0.9,
                    }

                return await self._process_product_guide_action({"action": section_action}, session_id)

        # NO_RETRIEVAL intents (greetings, small talk, thanks, goodbyes).
        if form_data is None:
            no_ret_kind = self._detect_no_retrieval_intent(message)
            if no_ret_kind:
                # Before ending a conversation, ask whether everything was answered (once).
                completion_triggered = False
                if no_ret_kind == "GOODBYE":
                    session = self.state_manager.get_session(session_id) or {}
                    ctx = dict(session.get("context") or {})
                    if not ctx.get("completion_asked") and not ctx.get("pending_completion_question"):
                        ctx["completion_asked"] = True
                        ctx["pending_completion_question"] = True
                        self.state_manager.update_session(session_id, {"context": ctx})
                        answer_text = COMPLETION_ASK_PROMPT
                        completion_triggered = True

                if not completion_triggered:
                    # Small-talk/greeting/thanks/goodbye: skip RAG.
                    if self.small_talk_responder is not None:
                        try:
                            answer_text = await self.small_talk_responder.respond(message, no_ret_kind)
                            if _is_incomplete_smalltalk_reply(answer_text):
                                answer_text = self._build_no_retrieval_reply(no_ret_kind)
                        except Exception:
                            answer_text = self._build_no_retrieval_reply(no_ret_kind)
                    else:
                        answer_text = self._build_no_retrieval_reply(no_ret_kind)

                _emit_metrics(
                    db,
                    [
                        _metric_payload(
                            "response_latency",
                            time.time() - start_time,
                            conversation_id,
                        )
                    ],
                )

                if hasattr(db, "add_conversation_event"):
                    try:
                        db.add_conversation_event(
                            conversation_id=conversation_id or session_id,
                            event_type="intent",
                            payload={
                                "intent": no_ret_kind.lower(),
                                "intent_type": "NO_RETRIEVAL",
                                "confidence": 1.0,
                                "user_message": message,
                                "response_latency": time.time() - start_time,
                            },
                        )
                    except Exception as exc:
                        logger.warning("[metrics] Failed to record conversation event: %s", exc)

                payload = {
                    "mode": "conversational",
                    "response": answer_text,
                    "sources": [],
                    "products_matched": [],
                    "intent": no_ret_kind.lower(),
                    "intent_type": "NO_RETRIEVAL",
                    "suggested_action": None,
                    "confidence": 1.0,
                }

                if no_ret_kind == "GOODBYE" and not completion_triggered:
                    self.state_manager.end_session(session_id, ended_by="bot")

                return payload

        if form_data is None and _is_ambiguous_motor_query(message):
            motor_options = ["Motor Private", "Motor Commercial"]
            session = self.state_manager.get_session(session_id) or {}
            ctx = dict(session.get("context") or {})
            ctx.pop("pending_section_offer", None)
            ctx["pending_product_choice"] = {
                "topic_label": "motor insurance",
                "options": motor_options,
            }
            self.state_manager.update_session(session_id, {"context": ctx})
            return {
                "mode": "conversational",
                "response": _build_product_choice_clarification("motor insurance", motor_options),
                "intent": "clarify_product",
                "confidence": 0.9,
            }

        if form_data is None and _is_vague_selection_reply(message):
            return {
                "mode": "conversational",
                "response": _build_vague_selection_clarification(),
                "intent": "clarify_selection",
                "confidence": 0.9,
            }

        # Detect coarse intent (quote/buy/learn/etc.)
        broad_query = _is_broad_product_query(message)
        intent = self._detect_intent(message)
        explicit_guided_intent = _is_explicit_guided_intent(message)
        detected_product = _detect_digital_flow(message)
        if broad_query and intent in ("learn", "general"):
            intent = "discover"

        # Match relevant products
        products = self.product_matcher.match_products(message, top_k=3)

        session = self.state_manager.get_session(session_id) or {}
        ctx = dict(session.get("context") or {})
        topic = (ctx.get("product_topic") or {}) if isinstance(ctx, dict) else {}

        if ctx.get("pending_section_offer") and _has_confident_product_switch(products, topic):
            ctx.pop("pending_section_offer", None)
            self.state_manager.update_session(session_id, {"context": ctx})
            topic = (ctx.get("product_topic") or {}) if isinstance(ctx, dict) else {}

        should_reuse_topic = _should_reuse_product_topic(message, topic)
        recent_history = self._get_recent_history(session_id)
        query_with_topic = _augment_query_with_topic(
            message,
            topic.get("name"),
            use_topic=should_reuse_topic,
        )
        if detected_product:
            query_with_topic = _augment_query_with_topic(
                query_with_topic,
                _digital_flow_search_hint(detected_product),
                use_topic=True,
            )
        should_use_history = _is_followup_message(message) and bool(recent_history) and not _detect_digital_flow(message)
        retrieval_query = _augment_query_with_history(
            query_with_topic,
            recent_history,
            use_history=should_use_history,
        )

        # Build filters for RAG retrieval.
        filters: Dict[str, Any] = {}
        if products:
            top_score = float(products[0][0] or 0.0)
            second_score = float(products[1][0] or 0.0) if len(products) > 1 else 0.0
            is_confident = (top_score >= 1.2) and (top_score >= second_score + 0.5)

            logger.info(
                "[RAG] Product match: top_score=%s, is_confident=%s, detected=%s, products=%s",
                top_score, is_confident, detected_product, [p[2]["name"] for p in products[:1]]
            )

            if intent == "compare":
                # Comparing products: allow multiple doc_ids.
                filters["products"] = [p[2]["product_id"] for p in products[:3]]
            elif should_reuse_topic and topic.get("doc_id"):
                filters["products"] = [topic["doc_id"]]
                logger.info("[RAG] Reusing session product topic filter: %s", topic["doc_id"])
            elif detected_product:
                # User explicitly asked about a specific product - filter to that product only
                # Find matching product in the list
                for p in products:
                    if p[2].get("product_id") and detected_product in p[2].get("product_id", ""):
                        filters["products"] = [p[2]["product_id"]]
                        logger.info("[RAG] Applying explicit product filter: %s", p[2]["product_id"])
                        break
            elif is_confident and not broad_query:
                # Single-product intent with high confidence: restrict to the best match.
                filters["products"] = [products[0][2]["product_id"]]
                logger.info("[RAG] Applying confident product filter: %s", products[0][2]["product_id"])
        elif detected_product:
            detected_doc_ids = _resolve_doc_ids_for_digital_flow(self.product_matcher, detected_product)
            if detected_doc_ids:
                filters["products"] = detected_doc_ids
                logger.info("[RAG] Applying digital flow fallback filter: flow=%s, doc_ids=%s", detected_product, detected_doc_ids)
        elif should_reuse_topic and topic.get("doc_id"):
            filters["products"] = [topic["doc_id"]]
            logger.info("[RAG] Reusing session product topic filter without fresh product match: %s", topic["doc_id"])

        # Retrieve relevant documents (hybrid BM25 + vector via APIRAGAdapter).
        retrieval_results = await self.rag.retrieve(query=retrieval_query, filters=filters or None, top_k=None)

        # Generate response
        response = await self._generate_with_optional_original_question(
            query=retrieval_query,
            context_docs=retrieval_results,
            conversation_history=recent_history,
            original_question=message,
        )

        # ---- Record RAG metrics ----
        confidence = _estimate_response_confidence(response, retrieval_results, products, filters)
        sources = response.get("sources", [])
        metrics_to_emit = [
            _metric_payload("confidence_score", confidence, conversation_id),
            _metric_payload("retrieval_accuracy", min(len(sources) / 5.0, 1.0), conversation_id),
        ]
        if not sources:
            metrics_to_emit.append(_metric_payload("fallbacks", 1.0, conversation_id))
        # ---- End metrics ----

        # --- Escalation/handover logic ---
        session = self.state_manager.get_session(session_id) or {}

        # A real system error (generator/LLM failure) is not an "agent needed"
        # case: the user just gets the retry message, with no handoff offer.
        system_error = bool(response.get("error"))

        # MIA's job is to answer the question. We do NOT auto-arm a human-agent
        # handoff on low confidence or missing chunks - that made MIA push the
        # agent on customers who were perfectly fine. The agent is only offered
        # when the user explicitly asks for one or declines the completion
        # question (handled elsewhere).
        show_handover_button = False

        products_matched_names = [p[2]["name"] for p in products] if products else []
        if not products_matched_names and topic.get("name") and should_reuse_topic:
            products_matched_names = [topic["name"]]
        if self.response_processor and not system_error:
            processed = self.response_processor.process_response(
                raw_response=response.get("answer"),
                user_input=message,
                confidence=confidence,
                conversation_state=session,
                session_id=session_id,
                user_id=user_id,
                products_matched=products_matched_names,
            )
            answer_text = processed.get("message")
            follow_up_flag = processed.get("follow_up", False)
            processed_reason = (processed.get("metadata") or {}).get("reason")
            processed_fallback = bool(processed.get("fallback"))
            if processed.get("fallback"):
                metrics_to_emit.append(_metric_payload("fallbacks", 1.0, conversation_id))
        else:
            answer_text = response["answer"]
            follow_up_flag = False
            processed_reason = None
            processed_fallback = False

        # Separate "bot is DOWN" (service error) from "bot doesn't have the
        # answers" (no chunks / no sources / low confidence / fallback reply).
        if system_error:
            self._log_service_error(
                db, conversation_id, message, response.get("error_kind") or "system_error"
            )
        elif not retrieval_results or not sources or confidence < 0.2 or processed_fallback:
            reason = (
                "no_chunks"
                if not retrieval_results
                else ("no_sources" if not sources else ("fallback" if processed_fallback else "low_confidence"))
            )
            self._log_unanswered(db, conversation_id, message, reason=reason)

        if processed_reason == "incomplete_input" and not products:
            recommendation = await self._build_recommendation_response(message, session_id)
            if recommendation:
                answer_text = recommendation
                follow_up_flag = True

        related_names = [p[2].get("name") for p in products if p[2].get("name")]
        unique_related_names: List[str] = []
        for name in related_names:
            if name and name not in unique_related_names:
                unique_related_names.append(name)

        broad_multi_product = broad_query and len(unique_related_names) > 1

        # Determine product topic for follow-up guidance.
        digital_flow = _detect_digital_flow(message) or topic.get("digital_flow")
        top_product = None if broad_multi_product else (products[0][2] if products else (topic if topic.get("doc_id") else None))

        if digital_flow or top_product:
            topic_name = None
            topic_url = None
            topic_doc_id = None

            if top_product:
                topic_name = top_product.get("name")
                topic_url = top_product.get("url")
                topic_doc_id = top_product.get("product_id") or top_product.get("doc_id")

            # Persist topic in session context (so buttons can work).
            session = self.state_manager.get_session(session_id) or {}
            ctx = dict(session.get("context") or {})
            ctx["product_topic"] = {
                "digital_flow": digital_flow,
                "name": topic_name,
                "doc_id": topic_doc_id,
                "url": topic_url,
            }
            if top_product:
                ctx.pop("pending_product_choice", None)
            self.state_manager.update_session(session_id, {"context": ctx})

        # Append a natural follow-up prompt when the user is learning about a product.
        follow_up_prompt = None
        related_products_block = None
        if broad_query and products:
            if unique_related_names:
                related_list = "\n".join([f"- {name}" for name in unique_related_names[:4]])
                related_products_block = f"Related products you can consider:\n{related_list}"
        if broad_query and "accident" in (message or "").lower():
            follow_up_prompt = (
                "Is this about Personal Accident cover for an individual, or Group Personal Accident for employees?"
            )
        elif broad_multi_product:
            topic_label = "product"
            lowered_message = (message or "").lower()
            if "motor" in lowered_message:
                topic_label = "motor insurance"
            elif "travel" in lowered_message:
                topic_label = "travel insurance"
            elif "medical" in lowered_message or "health" in lowered_message:
                topic_label = "health insurance"

            follow_up_prompt = _build_product_choice_clarification(topic_label, unique_related_names)

            session = self.state_manager.get_session(session_id) or {}
            ctx = dict(session.get("context") or {})
            ctx.pop("pending_section_offer", None)
            ctx["pending_product_choice"] = {
                "topic_label": topic_label,
                "options": unique_related_names[:4],
            }
            self.state_manager.update_session(session_id, {"context": ctx})
        elif intent in ("learn", "general", "compare", "discover") and (digital_flow or top_product):
            topic_label = topic_name or "this product"
            answer_lower = (answer_text or "").lower()
            mentions_benefits = "benefit" in answer_lower

            # Offer benefits only if we didn't already include them.
            if mentions_benefits:
                follow_up_prompt = f"Would you like anything else about {topic_label}, such as pricing or eligibility?"
            else:
                follow_up_prompt = f"Should I share the benefits of {topic_label}?"

            # Store what a simple "yes" should do next.
            session = self.state_manager.get_session(session_id) or {}
            ctx = dict(session.get("context") or {})
            ctx["pending_section_offer"] = "show_benefits"
            ctx.pop("pending_product_choice", None)
            self.state_manager.update_session(session_id, {"context": ctx})

        # Sources removed from conversation response per user request
        # sources_block = self._format_sources(response.get("sources", []))
        # if sources_block:
        #     answer_text = f"{answer_text}\n\n{sources_block}" if answer_text else sources_block

        # If response processor already queued a follow-up, prefer that text over our generic follow_up_prompt
        if follow_up_flag:
            # If the processor flagged a follow-up, we assume it already queued it.
            # Keep the model-provided message as-is.
            pass
        elif follow_up_prompt:
            answer_parts = [p for p in [answer_text, related_products_block, follow_up_prompt] if p]
            answer_text = "\n\n".join(answer_parts)
        elif related_products_block:
            answer_text = f"{answer_text}\n\n{related_products_block}" if answer_text else related_products_block

        # Determine if we should suggest guided mode
        suggested_action = None
        if explicit_guided_intent:
            digital_flow = _detect_digital_flow(message)

            if digital_flow:
                suggested_action = {
                    "type": "switch_to_guided",
                    "message": "Ready to get started? I can guide you through a few questions to provide a quote.",
                    "flow": "journey",
                    "initial_data": {"product_flow": digital_flow},
                    "buttons": [
                        {"label": "Get quotation", "action": "get_quotation"},
                        {"label": "Not now", "action": "continue_chat"},
                    ],
                }
            elif products:
                top = products[0][2]
                suggested_action = {
                    "type": "switch_to_guided",
                    "message": f"{top.get('name', 'This product')} requires agent assistance. Please share your contact details.",
                    "flow": "agent_handoff",
                    "initial_data": {"product_name": top.get("name"), "product_url": top.get("url")},
                    "buttons": [
                        {"label": "Share details", "action": "start_guided"},
                        {"label": "Not now", "action": "continue_chat"},
                    ],
                }
            else:
                suggested_action = {
                    "type": "switch_to_guided",
                    "message": "Let me help you find the right solution. Please share your details.",
                    "flow": "agent_handoff",
                    "buttons": [
                        {"label": "Share details", "action": "start_guided"},
                        {"label": "Not now", "action": "continue_chat"},
                    ],
                }
        elif intent == "discover" and products:
            suggested_action = {
                "type": "show_product_cards",
                "message": "Here are some products that might interest you:",
                "products": [self._generate_product_card(p[2]) for p in products],
            }

        # No product-guide buttons by default; users can reply in free text.

        response_latency = time.time() - start_time
        metrics_to_emit.append(
            _metric_payload("response_latency", response_latency, conversation_id)
        )
        _emit_metrics(db, metrics_to_emit)

        if hasattr(db, "add_conversation_event"):
            try:
                top_product = products[0][2] if products else {}
                db.add_conversation_event(
                    conversation_id=conversation_id or session_id,
                    event_type="intent",
                    payload={
                        "intent": intent,
                        "intent_type": "INFORMATIONAL",
                        "confidence": response.get("confidence", 0.5),
                        "user_message": message,
                        "response_latency": response_latency,
                        "product_name": top_product.get("name"),
                        "product_id": top_product.get("product_id"),
                        "category": top_product.get("category_name"),
                        "subcategory": top_product.get("sub_category_name"),
                    },
                )
            except Exception as exc:
                logger.warning("[metrics] Failed to record conversation event: %s", exc)

        return {
            "mode": "conversational",
            "response": answer_text,
            "sources": response.get("sources", []),
            "products_matched": [p[2]["name"] for p in products],
            "intent": intent,
            "intent_type": "INFORMATIONAL",
            "suggested_action": suggested_action,
            "confidence": confidence,
            "show_handover_button": show_handover_button,
        }

    async def _route_intent(self, message: str):
        """Route one message through the LLM intent router.

        Returns ``None`` when the router is unavailable or undecided (caller
        falls through to the brain / RAG pipeline), or a tuple:

        * ``("REPLY", label, reply)`` - answer immediately, no retrieval.
        * ``("PASSTHROUGH", require_grounding)`` - continue to the brain; when
          ``require_grounding`` is True the brain's answer must come from chunks.
        """
        router = getattr(self, "intent_router", None)
        if router is None:
            return None
        try:
            label, reply = await router.route(message)
        except Exception as exc:
            logger.warning("IntentRouter failed; falling through to brain/RAG: %s", exc, exc_info=True)
            return None

        if label in ("OM_QUESTION", "QUOTE"):
            return ("PASSTHROUGH", label == "OM_QUESTION")
        if label in ("GREETING", "SMALL_TALK", "THANKS", "GOODBYE", "OFF_TOPIC"):
            return ("REPLY", label, reply)
        # UNKNOWN / unexpected label -> fall through to the normal pipeline.
        return None

    async def _process_with_brain(
        self,
        message: str,
        session_id: str,
        user_id: str,
        conversation_id: Optional[str],
        db,
        start_time: float,
        require_grounding: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        Route one free-text message through the ConversationalBrain.

        Returns a response payload, or ``None`` when the brain is unusable so the
        caller can fall back to the keyword/RAG pipeline.
        """
        if self.brain is None:
            return None

        session = self.state_manager.get_session(session_id) or {}
        ctx = dict(session.get("context") or {})
        topic = (ctx.get("product_topic") or {}) if isinstance(ctx, dict) else {}
        recent_history = self._get_recent_history(session_id)

        # Quote-offer confirmation bridge: if we previously offered a guided
        # quote flow, let the brain decide the user's yes/no/other intent.
        if ctx.get("pending_quote_offer"):
            decision = await self.brain.confirm_quote_offer(message, history=recent_history)
            ctx.pop("pending_quote_offer", None)
            self.state_manager.update_session(session_id, {"context": ctx})

            if decision == "proceed":
                product_flow = _detect_digital_flow(message) or topic.get("digital_flow")
                return {
                    "mode": "conversational",
                    "response": "Great! Click the button below to load the form and get your quotation.",
                    "intent": "quote",
                    "intent_type": "INFORMATIONAL",
                    "confidence": 1.0,
                    "suggested_action": {
                        "type": "switch_to_guided",
                        "flow": "journey",
                        "initial_data": {"product_flow": product_flow},
                        "buttons": [{"label": "Get quotation", "action": "get_quotation"}],
                    },
                }
            if decision == "cancel":
                return {
                    "mode": "conversational",
                    "response": "No problem. Let me know if you'd like help with anything else.",
                    "confidence": 1.0,
                }
            # "other": fall through to the normal brain conversation below.

        result = await self.brain.converse(
            message=message,
            history=recent_history,
            topic=topic,
            pending_quote_offer=bool(ctx.get("pending_quote_offer")),
        )
        if result is None:
            return None

        # Chunk-only guarantee: when the intent router flagged this as an Old
        # Mutual question but the brain answered WITHOUT retrieving from the
        # knowledge base, force a grounded regeneration so facts come strictly
        # from the chunks (never the model's own general knowledge).
        if require_grounding and not result.quote_requested and not getattr(result, "used_knowledge", False):
            grounded = await self._force_grounded_reply(
                message=message,
                session_id=session_id,
                user_id=user_id,
                conversation_id=conversation_id,
                db=db,
                start_time=start_time,
                recent_history=recent_history,
            )
            if grounded is not None:
                return grounded

        products_matched = [p[2]["name"] for p in self.product_matcher.match_products(message, top_k=3)]
        suggested_action = None
        intent = "general"

        if result.quote_requested:
            intent = "quote"
            product_flow = result.product or _detect_digital_flow(message) or topic.get("digital_flow")
            suggested_action = {
                "type": "switch_to_guided",
                "flow": "journey",
                "initial_data": {"product_flow": product_flow},
                "buttons": [{"label": "Get quotation", "action": "get_quotation"}],
            }
            # Remember we offered a quote so the next free-text yes/no is
            # resolved by the brain's confirmation bridge above.
            session = self.state_manager.get_session(session_id) or {}
            ctx = dict(session.get("context") or {})
            ctx["pending_quote_offer"] = True
            self.state_manager.update_session(session_id, {"context": ctx})

        # MIA answers confidently and we do NOT auto-arm a human-agent handoff here.
        # A handoff is only offered when the user asks for one or declines the
        # completion question. Keep the "couldn't answer" signal for metrics so
        # fallback_rate stays honest.
        show_handover_button = False
        if not result.quote_requested and (
            not result.sources or result.confidence < 0.2
        ):
            self._log_unanswered(
                db,
                conversation_id or session_id,
                message,
                reason="no_chunks" if not result.sources else "low_confidence",
            )

        payload = {
            "mode": "conversational",
            "response": result.reply,
            "sources": result.sources,
            "products_matched": products_matched,
            "intent": intent,
            "intent_type": "INFORMATIONAL",
            "suggested_action": suggested_action,
            "confidence": result.confidence,
            "show_handover_button": show_handover_button,
            "brain": True,
        }

        latency = time.time() - start_time
        _emit_metrics(
            db,
            [
                _metric_payload("response_latency", latency, conversation_id),
                _metric_payload("confidence_score", result.confidence, conversation_id),
            ],
        )
        if hasattr(db, "add_conversation_event"):
            try:
                db.add_conversation_event(
                    conversation_id=conversation_id or session_id,
                    event_type="intent",
                    payload={
                        "intent": intent,
                        "intent_type": "BRAIN",
                        "confidence": result.confidence,
                        "user_message": message,
                        "response_latency": latency,
                        "used_knowledge": result.used_knowledge,
                    },
                )
            except Exception as exc:
                logger.warning("[metrics] Failed to record brain conversation event: %s", exc)

        return payload

    async def _force_grounded_reply(
        self,
        *,
        message: str,
        session_id: str,
        user_id: str,
        conversation_id: Optional[str],
        db,
        start_time: float,
        recent_history: List[Dict],
    ) -> Optional[Dict[str, Any]]:
        """Re-run an Old Mutual question strictly from retrieved chunks.

        Used when the brain answered without retrieving the knowledge base, so
        the reply can never come from the model's own general knowledge.
        """
        retrieval_results = await self.rag.retrieve(query=message, filters=None, top_k=None)
        response = await self._generate_with_optional_original_question(
            query=message,
            context_docs=retrieval_results,
            conversation_history=recent_history,
            original_question=message,
        )
        answer = response.get("answer")
        if not answer:
            return None

        confidence = _estimate_response_confidence(response, retrieval_results, [], {})

        _emit_metrics(
            db,
            [
                _metric_payload("response_latency", time.time() - start_time, conversation_id),
                _metric_payload("confidence_score", confidence, conversation_id),
            ],
        )
        if hasattr(db, "add_conversation_event"):
            try:
                db.add_conversation_event(
                    conversation_id=conversation_id or session_id,
                    event_type="intent",
                    payload={
                        "intent": "general",
                        "intent_type": "GROUNDED",
                        "confidence": confidence,
                        "user_message": message,
                        "response_latency": time.time() - start_time,
                        "used_knowledge": True,
                    },
                )
            except Exception as exc:
                logger.warning("[metrics] Failed to record grounded event: %s", exc)

        return {
            "mode": "conversational",
            "response": answer,
            "sources": response.get("sources", []),
            "products_matched": [p[2]["name"] for p in self.product_matcher.match_products(message, top_k=3)],
            "intent": "general",
            "intent_type": "INFORMATIONAL",
            "suggested_action": None,
            "confidence": confidence,
            "show_handover_button": False,
            "brain": True,
            "grounded": True,
        }

    async def _process_product_guide_action(self, form_data: Dict[str, Any], session_id: str) -> Dict:
        action = str(form_data.get("action") or "").strip()

        session = self.state_manager.get_session(session_id) or {}
        ctx = session.get("context") or {}
        topic = (ctx.get("product_topic") or {}) if isinstance(ctx, dict) else {}

        digital_flow = topic.get("digital_flow")
        product_name = topic.get("name") or (digital_flow.replace("_", " ").title() if digital_flow else None)
        doc_id = topic.get("doc_id")
        url = topic.get("url")

        # Quote button: frontend should start guided journey (digital only).
        # The router handles action=get_quotation and will immediately return the first product form/cards.
        if action == "get_quote" and digital_flow:
            return {
                "mode": "conversational",
                "response": "Sure — click 'Get quotation' to begin.",
                "suggested_action": {
                    "type": "switch_to_guided",
                    "flow": "journey",
                    "initial_data": {"product_flow": digital_flow},
                    "buttons": [{"label": "Get quotation", "action": "get_quotation"}],
                },
            }

        if action == "how_to_access":
            msg = "This product is not available as a digital buy/quote journey in this chatbot. "
            msg += "To access it, please visit an Old Mutual branch/agent or contact customer support."
            if url:
                msg += f"\n\nMore details: {url}"
            return {
                "mode": "conversational",
                "response": msg,
            }

        query = _build_section_query(product_name or "", action)
        filters = {"products": [doc_id]} if doc_id else None
        hits = await self.rag.retrieve(query=query, filters=filters)
        gen = await self.rag.generate(query=query, context_docs=hits, conversation_history=self._get_recent_history(session_id))

        # Process generation through ResponseProcessor if available so follow-ups/fallbacks are handled consistently
        session = self.state_manager.get_session(session_id) or {}
        if self.response_processor:
            processed = self.response_processor.process_response(
                raw_response=gen.get("answer"),
                user_input=query,
                confidence=gen.get("confidence", 0.0),
                conversation_state=session,
                session_id=session_id,
            )
            gen_text = processed.get("message")
            follow_up_flag = processed.get("follow_up", False)
        else:
            gen_text = gen.get("answer")
            follow_up_flag = False

        next_action, next_label = _next_section_offer(action, is_digital=bool(digital_flow))

        follow_up = "Do you have any more questions?"
        if next_action and next_label:
            follow_up = (
                f"Do you have any more questions, or should I share the {next_label}? "
                f"Reply 'yes' for {next_label}, or type your next question."
            )

            # Store what a simple "yes" should do next.
            session = self.state_manager.get_session(session_id) or {}
            ctx = dict(session.get("context") or {})
            ctx["pending_section_offer"] = next_action
            self.state_manager.update_session(session_id, {"context": ctx})

        response_text = gen_text
        if not follow_up_flag and follow_up:
            response_text = f"{gen_text}\n\n{follow_up}" if gen_text else follow_up

        return {
            "mode": "conversational",
            "response": response_text,
        }

    async def _build_recommendation_response(self, message: str, session_id: str) -> Optional[str]:
        hint = _infer_recommendation_hint(message)
        if not hint:
            return None

        rec_products = self.product_matcher.match_products(hint, top_k=1)
        if not rec_products:
            return None

        top_score, _, product = rec_products[0]
        if float(top_score or 0.0) < 1.0:
            return None

        hint_tokens = set(re.findall(r"\b[\w']+\b", hint.lower()))
        hint_tokens -= {"insurance", "cover", "policy", "plan", "personal", "business"}
        name_tokens = set(re.findall(r"\b[\w']+\b", (product.get("name") or "").lower()))
        slug_tokens = set(re.findall(r"\b[\w']+\b", (product.get("slug") or "").lower()))
        if hint_tokens and not (hint_tokens & name_tokens or hint_tokens & slug_tokens):
            return None

        product_name = product.get("name") or hint.title()
        product_id = product.get("product_id")

        query = _build_overview_query(product_name)
        filters = {"products": [product_id]} if product_id else None
        hits = await self.rag.retrieve(query=query, filters=filters)
        gen = await self.rag.generate(query=query, context_docs=hits, conversation_history=self._get_recent_history(session_id))

        explanation = (gen.get("answer") or "").strip()
        if "accident" in hint.lower():
            question = (
                "Is this about Personal Accident cover for an individual, or Group Personal Accident for employees?"
            )
        else:
            question = f"Is {product_name} the cover you meant, or should I suggest something else?"

        parts = [p for p in [explanation, question] if p]

        session = self.state_manager.get_session(session_id) or {}
        ctx = dict(session.get("context") or {})
        ctx["product_topic"] = {
            "digital_flow": _detect_digital_flow(hint),
            "name": product_name,
            "doc_id": product_id,
            "url": product.get("url"),
        }
        self.state_manager.update_session(session_id, {"context": ctx})

        return "\n\n".join(parts)

    async def _generate_with_optional_original_question(
        self,
        *,
        query: str,
        context_docs: List[Dict[str, Any]],
        conversation_history: List[Dict[str, Any]],
        original_question: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Call rag.generate while staying compatible with older adapters/tests."""
        try:
            return await self.rag.generate(
                query=query,
                context_docs=context_docs,
                conversation_history=conversation_history,
                original_question=original_question,
            )
        except TypeError as exc:
            if "original_question" not in str(exc):
                raise
            return await self.rag.generate(
                query=query,
                context_docs=context_docs,
                conversation_history=conversation_history,
            )

    def _detect_intent(self, message: str) -> str:
        """Detect coarse user intent from message (quote/buy/learn/compare/discover/claim/general)."""
        message_lower = message.lower()

        # Quote/Purchase intents
        if any(word in message_lower for word in ["quote", "how much", "price", "cost", "premium"]):
            return "quote"

        if any(word in message_lower for word in ["buy", "purchase", "apply", "get insurance"]):
            return "buy"

        # Discovery / learning intents
        if any(word in message_lower for word in ["what is", "tell me about", "explain", "how does"]):
            return "learn"

        if any(word in message_lower for word in ["compare", "difference", "vs", "versus"]):
            return "compare"

        if any(word in message_lower for word in ["need", "looking for", "want", "recommend"]):
            return "discover"

        # Claims/Support
        if any(word in message_lower for word in ["claim", "file", "submit"]):
            return "claim"

        # Default
        return "general"

    def _detect_no_retrieval_intent(self, message: str) -> Optional[str]:
        """
        Detect intents that should never trigger retrieval (NO_RETRIEVAL):
        GREETING, SMALL_TALK, THANKS, GOODBYE.
        """
        m = (message or "").strip().lower()
        if not m:
            return None

        # Greetings
        if _is_greeting(m):
            return "GREETING"

        # Thanks / appreciation
        thanks_phrases = {
            "thanks",
            "thank you",
            "thank you!",
            "thanks!",
            "thx",
            "thank u",
        }
        if m in thanks_phrases:
            return "THANKS"

        # Goodbyes
        goodbye_phrases = {
            "bye",
            "goodbye",
            "bye!",
            "goodbye!",
            "see you",
            "see you later",
        }
        if m in goodbye_phrases:
            return "GOODBYE"

        # Simple small talk
        small_talk_phrases = {
            "how are you",
            "how are you?",
            "how are u",
            "how are u?",
            "how's it going",
            "how's it going?",
            "hi",
            "whatsapp",
            "hello",
        }
        if m in small_talk_phrases:
            return "SMALL_TALK"

        return None

    def _build_no_retrieval_reply(self, kind: str) -> str:
        """
        Build a conversational reply for NO_RETRIEVAL intents without hitting RAG.
        """
        kind = (kind or "").upper()

        if kind == "GREETING":
            return (
                "Hey! I’m MIA, your Old Mutual assistant.\n"
                "You can ask me about our products, benefits, coverage, or how to get a quote."
            )
        if kind == "THANKS":
            return "You’re welcome! If you have any more questions about Old Mutual products or services, I’m here to help."
        if kind == "GOODBYE":
            return "You’re welcome. Feel free to come back any time you need help with Old Mutual products or services."
        if kind == "SMALL_TALK":
            return "I'm doing well, thank you for asking. How can I help you with Old Mutual products or services today?"
        if kind == "OFF_TOPIC":
            return "I only help with Old Mutual products and services. What would you like to know?"

        # Fallback – should rarely be hit.
        return "How can I help you with Old Mutual products or services today?"

    def _build_no_retrieval_response(
        self,
        *,
        kind: str,
        answer_text: str,
        message: str,
        session_id: str,
        user_id: str,
        conversation_id: Optional[str],
        db,
        start_time: float,
    ) -> Dict[str, Any]:
        """Build the response payload for a NO_RETRIEVAL intent (no RAG)."""
        # Ask the completion question once per conversation before ending.
        completion_triggered = False
        if kind == "GOODBYE":
            session = self.state_manager.get_session(session_id) or {}
            ctx = dict(session.get("context") or {})
            if not ctx.get("completion_asked") and not ctx.get("pending_completion_question"):
                ctx["completion_asked"] = True
                ctx["pending_completion_question"] = True
                self.state_manager.update_session(session_id, {"context": ctx})
                answer_text = COMPLETION_ASK_PROMPT
                completion_triggered = True

        _emit_metrics(
            db,
            [_metric_payload("response_latency", time.time() - start_time, conversation_id)],
        )

        if hasattr(db, "add_conversation_event"):
            try:
                db.add_conversation_event(
                    conversation_id=conversation_id or session_id,
                    event_type="intent",
                    payload={
                        "intent": str(kind).lower(),
                        "intent_type": "NO_RETRIEVAL",
                        "confidence": 1.0,
                        "user_message": message,
                        "response_latency": time.time() - start_time,
                    },
                )
            except Exception as exc:
                logger.warning("[metrics] Failed to record conversation event: %s", exc)

        payload = {
            "mode": "conversational",
            "response": answer_text,
            "sources": [],
            "products_matched": [],
            "intent": str(kind).lower(),
            "intent_type": "NO_RETRIEVAL",
            "suggested_action": None,
            "confidence": 1.0,
        }

        if str(kind).upper() == "GOODBYE" and not completion_triggered:
            self.state_manager.end_session(session_id, ended_by="bot")

        return payload

    def _identity_response(self, text: str, intent: str) -> Dict[str, Any]:
        return {
            "mode": "conversational",
            "response": text,
            "sources": [],
            "products_matched": [],
            "intent": intent,
            "intent_type": "NO_RETRIEVAL",
            "confidence": 1.0,
        }

    def _emit_intent_event(self, db, conversation_id: Optional[str], intent: str, intent_type: str, message: str, start_time: float) -> None:
        if db is None or not hasattr(db, "add_conversation_event"):
            return
        try:
            db.add_conversation_event(
                conversation_id=conversation_id,
                event_type="intent",
                payload={
                    "intent": intent,
                    "intent_type": intent_type,
                    "confidence": 1.0,
                    "user_message": message,
                    "response_latency": time.time() - start_time,
                },
            )
        except Exception as exc:
            logger.warning("[metrics] Failed to record conversation event: %s", exc)

    def _log_unanswered(self, db, conversation_id: Optional[str], message: str, reason: str) -> None:
        """Record a question the bot could NOT answer (no chunks / low confidence)."""
        if db is not None and hasattr(db, "add_conversation_event"):
            try:
                db.add_conversation_event(
                    conversation_id=conversation_id,
                    event_type="unanswered_question",
                    payload={
                        "question": (message or "").strip()[:500],
                        "reason": reason,
                    },
                )
            except Exception as exc:
                logger.warning("[metrics] Failed to record unanswered event: %s", exc)
        _emit_metrics(db, [_metric_payload("unanswered_questions", 1.0, conversation_id)])

    def _log_service_error(self, db, conversation_id: Optional[str], message: str, error_kind: str) -> None:
        """Record a bot-DOWN event: the bot could not reply due to a service failure."""
        if db is not None and hasattr(db, "add_conversation_event"):
            try:
                db.add_conversation_event(
                    conversation_id=conversation_id,
                    event_type="service_error",
                    payload={
                        "question": (message or "").strip()[:500],
                        "error_kind": error_kind,
                    },
                )
            except Exception as exc:
                logger.warning("[metrics] Failed to record service error event: %s", exc)
        _emit_metrics(db, [_metric_payload("service_errors", 1.0, conversation_id)])

    def _record_completion(self, db, conversation_id: Optional[str], message: str, outcome: str) -> None:
        """Record the user's completion answer, labelling the conversation outcome."""
        if db is not None and hasattr(db, "add_conversation_event"):
            try:
                db.add_conversation_event(
                    conversation_id=conversation_id,
                    event_type="completion_confirmed",
                    payload={
                        "outcome": outcome,
                        "user_message": (message or "").strip()[:500],
                    },
                )
            except Exception as exc:
                logger.warning("[metrics] Failed to record completion event: %s", exc)
        resolved_value = 1.0 if outcome == "resolved" else 0.0
        _emit_metrics(db, [_metric_payload("completion_outcome", resolved_value, conversation_id)])

    def _maybe_handle_completion_question(
        self,
        message: str,
        session_id: str,
        conversation_id: Optional[str],
        db,
    ) -> Optional[Dict[str, Any]]:
        """Interpret the user's reply to the completion question ("did I answer everything?")."""
        if not message or not (message or "").strip():
            return None

        if db is None:
            db = getattr(self.state_manager, "db", None)

        session = self.state_manager.get_session(session_id) or {}
        ctx = dict(session.get("context") or {})
        if not ctx.get("pending_completion_question"):
            return None

        ctx.pop("pending_completion_question", None)

        if _is_affirmative(message):
            self.state_manager.update_session(session_id, {"context": ctx})
            self._record_completion(db, conversation_id, message, "resolved")
            try:
                self.state_manager.end_session(session_id, ended_by="bot")
            except Exception:
                pass
            return {
                "mode": "conversational",
                "response": COMPLETION_RESOLVED_PROMPT,
                "confidence": 1.0,
                "outcome": "resolved",
            }

        if _is_negative(message):
            sess = self.state_manager.get_session(session_id) or {}
            pending_ctx = dict(sess.get("context") or {})
            pending_ctx["pending_agent_offer"] = True
            self.state_manager.update_session(session_id, {"context": pending_ctx})
            self._record_completion(db, conversation_id, message, "unresolved")
            return {
                "mode": "conversational",
                "response": COMPLETION_UNRESOLVED_PROMPT,
                "confidence": 1.0,
                "outcome": "unresolved",
                "show_handover_button": True,
            }

        # Any other reply: the user kept chatting - clear the question and continue.
        self.state_manager.update_session(session_id, {"context": ctx})
        return None

    def _save_identity(self, db, user_id: str, name: Optional[str], email: Optional[str], conversation_id: Optional[str], via: str, partial: bool = False) -> None:
        if db is not None and hasattr(db, "set_user_identity"):
            try:
                db.set_user_identity(user_id, name=name, email=email)
            except Exception as exc:
                logger.warning("[identity] failed to persist identity: %s", exc)
        if db is not None and hasattr(db, "add_conversation_event"):
            try:
                db.add_conversation_event(
                    conversation_id=conversation_id,
                    event_type="identity_captured",
                    payload={
                        "name_masked": CLIENT_NAME_MASK,
                        "has_name": bool(name),
                        "email": email,
                        "via": via,
                        "partial": bool(partial),
                    },
                )
            except Exception as exc:
                logger.warning("[identity] failed to record identity event: %s", exc)

    def _maybe_handle_identity_capture(self, message: str, session_id: str, user_id: str, conversation_id: Optional[str], session: Dict[str, Any], db, start_time: float) -> Optional[Dict[str, Any]]:
        """Greeting flow: ask for the user's email once per user (privacy-safe).

        Returns a response payload when this turn is consumed by identity
        capture, otherwise None so normal processing continues. The client's
        name is derived from the email address; the email is stored for follow-up.
        """
        try:
            if not message or not (message or "").strip():
                return None

            if db is None:
                db = getattr(self.state_manager, "db", None)

            ctx = dict(session.get("context") or {})
            pending = bool(ctx.get("pending_identity_capture"))
            time_greeting = _time_greeting_eat()

            if not pending:
                identity_kind = _identity_question_kind(message)
                if not _is_greeting(message):
                    if identity_kind is None and not _is_memory_question(message):
                        return None
                user = None
                if db is not None and hasattr(db, "get_user_by_id"):
                    try:
                        user = db.get_user_by_id(user_id)
                    except Exception:
                        user = None
                name = (getattr(user, "name", None) or "").strip() if user is not None else ""
                if identity_kind == "assistant":
                    return self._identity_response(ASSISTANT_IDENTITY_PROMPT, "assistant_identity")
                if identity_kind == "both":
                    if name:
                        return self._identity_response(
                            f"I'm Mia, your Old Mutual Uganda virtual assistant. You're {name}.",
                            "combined_identity",
                        )
                    return self._identity_response(
                        f"{ASSISTANT_IDENTITY_PROMPT} {USER_IDENTITY_UNKNOWN_PROMPT}",
                        "combined_identity",
                    )
                # Handle memory questions first - they need a specific "You're {name}..." response with intent "greeting_returning"
                if user is not None and (getattr(user, "email", None) or "").strip() and _is_memory_question(message):
                    if name:
                        return self._identity_response(
                            f"You're {name}. How can I help you today?",
                            "greeting_returning",
                        )
                    return self._identity_response(USER_IDENTITY_UNKNOWN_PROMPT, "identity_check")

                # Then handle greetings and identity_kind == "user"
                if user is not None and (getattr(user, "email", None) or "").strip() and identity_kind == "user":
                    if name:
                        return self._identity_response(
                            f"You're {name}. How can I help you today?",
                            "greeting_returning",
                        )
                    return self._identity_response(USER_IDENTITY_UNKNOWN_PROMPT, "identity_check")

                # Handle greetings
                if user is not None and (getattr(user, "email", None) or "").strip() and _is_greeting(message):
                    if name:
                        return self._identity_response(
                            _random_greeting(name),
                            "greeting_returning",
                        )
                    return self._identity_response(
                        _random_greeting(name),
                        "greeting_returning",
                    )
                if _is_memory_question(message) or identity_kind == "user":
                    ctx["pending_identity_capture"] = True
                    self.state_manager.update_session(session_id, {"context": ctx})
                    if name:
                        return self._identity_response(f"You're {name}.", "identity_check")
                    return self._identity_response(USER_IDENTITY_UNKNOWN_PROMPT, "identity_check")
                ctx["pending_identity_capture"] = True
                self.state_manager.update_session(session_id, {"context": ctx})
                _emit_metrics(
                    db,
                    [_metric_payload("response_latency", time.time() - start_time, conversation_id)],
                )
                self._emit_intent_event(db, conversation_id, "greeting", "NO_RETRIEVAL", message, start_time)
                ask = IDENTITY_ASK_PROMPT.format(time_greeting=time_greeting)
                return self._identity_response(ask, "greeting")

            # Pending capture: this turn should contain the identity info.
            if _is_greeting(message):
                ask = IDENTITY_ASK_PROMPT.format(time_greeting=time_greeting)
                return self._identity_response(ask, "greeting")

            email = _extract_email(message)

            if email:
                email = email.strip().lower()
                name = _derive_name_from_email(email)
                existing = None
                if db is not None and hasattr(db, "find_user_by_email"):
                    try:
                        existing = db.find_user_by_email(email)
                    except Exception as exc:
                        logger.warning("[identity] email lookup failed: %s", exc)
                if existing is not None and str(getattr(existing, "id", "")) != str(user_id):
                    canonical_id = str(existing.id)
                    canonical_name = (getattr(existing, "name", None) or "").strip() or name
                    self._save_identity(
                        db, canonical_id, canonical_name, email, conversation_id, via="greeting_relink"
                    )
                    if db is not None and hasattr(db, "add_conversation_event"):
                        try:
                            db.add_conversation_event(
                                conversation_id=conversation_id,
                                event_type="identity_relinked",
                                payload={
                                    "email": email,
                                    "name_masked": CLIENT_NAME_MASK,
                                    "has_name": bool(canonical_name),
                                },
                            )
                        except Exception as exc:
                            logger.warning("[identity] failed to record relink event: %s", exc)
                    ctx.pop("pending_identity_capture", None)
                    self.state_manager.update_session(session_id, {"context": ctx, "user_id": canonical_id})
                    welcome = f"Welcome back, {canonical_name}! How can I help you today?"
                    return self._identity_response(welcome, "identity_relinked")
                self._save_identity(db, user_id, name, email, conversation_id, via="greeting")
                ctx.pop("pending_identity_capture", None)
                self.state_manager.update_session(session_id, {"context": ctx})
                confirmed = IDENTITY_CONFIRMED_PROMPT.format(time_greeting=time_greeting)
                return self._identity_response(confirmed, "identity_captured")

            if _looks_like_question(message):
                # Not identity info — stop waiting and process normally.
                ctx.pop("pending_identity_capture", None)
                self.state_manager.update_session(session_id, {"context": ctx})
                return None

            # Unrecognized short reply: don't block the conversation.
            ctx.pop("pending_identity_capture", None)
            self.state_manager.update_session(session_id, {"context": ctx})
            return None
        except Exception as exc:
            logger.warning("[identity] identity capture failed, continuing normally: %s", exc)
            return None

    def _get_recent_history(self, session_id: str, limit: int = 10) -> List[Dict]:
        """Get recent conversation history.

        Fast path: reads the rolling ``recent_messages`` buffer stored in the
        Redis session so follow-up turns never need a PostgreSQL round-trip.
        Falls back to PostgreSQL on cold start (e.g. after a server restart
        before the first reply has been saved this session).
        """
        session = self.state_manager.get_session(session_id)
        if not session:
            return []

        # Redis cache (fast path)
        cached = session.get("recent_messages")
        if cached:
            return cached[-limit:]

        # Cold-start fallback: read from PostgreSQL
        messages = self.state_manager.db.get_conversation_history(session["conversation_id"], limit=limit)
        return [{"role": msg.role, "content": msg.content} for msg in reversed(messages)]

    def _generate_product_card(self, product: Dict) -> Dict:
        """Generate product card data"""
        return {
            "product_id": product.get("product_key") or product["product_id"],
            "doc_id": product.get("doc_id") or product.get("product_id"),
            "name": product["name"],
            "category": product.get("category_name", ""),
            "description": product.get("description", ""),
            "min_premium": product.get("min_premium"),
            "actions": [{"type": "learn_more", "label": "Learn More"}, {"type": "get_quote", "label": "Get a Quote"}],
        }

    def _format_sources(self, sources: List[Dict]) -> str:
        if not sources:
            return ""

        items = []
        seen = set()
        for s in sources:
            payload = s.get("payload") or s
            title = (payload.get("title") or "Source").strip()
            url = (payload.get("url") or "").strip()
            if not url:
                continue
            key = (title, url)
            if key in seen:
                continue
            seen.add(key)
            items.append(f"- {title}: {url}")

        if not items:
            return ""
        return "Sources:\n" + "\n".join(items)
