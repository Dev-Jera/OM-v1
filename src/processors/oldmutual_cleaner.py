"""
Website data cleaning logic.

"""

from __future__ import annotations

import html as html_lib
import re
import unicodedata
from typing import Any, Dict, List


_DEFAULT_ENCODING_FIXES: list[tuple[str, str]] = [
    # Common mojibake
    ("Ã¢Â€Â™", "’"),
    ("Ã¢Â€Âœ", "“"),
    ("Ã¢Â€Â", "”"),
    ("Ã¢Â€Â“", "–"),
    ("Ã¢Â€Â¦", "…"),
    ("Ã¢Â€Â˜", "‘"),
    ("Ã‚Â", ""),
    # Alternative broken sequences
    ("â€™", "’"),
    ("â", "’"),
    ("â", "‘"),
    ("â€œ", "“"),
    ("â", "“"),
    ("â€", "”"),
    ("â", "”"),
    ("â€“", "–"),
    ("â", "–"),
    ("â€¦", "…"),
    ("â¦", "…"),
    # Zero-width space
    ("â", ""),
    ("Â", ""),
]


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


class OldMutualCleaner:
    """
    Clean scraped Old Mutual page objects:
    - fix encoding/mojibake
    - normalize unicode
    - collapse whitespace
    - dedupe repeated sections / FAQs
    - merge weird numeric headings (e.g. merchant code 238233) into the previous section
    - optionally improve "Step X" headings
    """

    def __init__(
        self,
        *,
        normalize_unicode: bool = True,
        fix_ocr_errors: bool = True,
        normalize_terminology: bool = True,
        improve_step_headings: bool = True,
    ) -> None:
        self.normalize_unicode = normalize_unicode
        self.fix_ocr_errors = fix_ocr_errors
        self.normalize_terminology = normalize_terminology
        self.improve_step_headings = improve_step_headings

    def clean_text(self, text: str) -> str:
        s = _safe_text(text)
        if not s:
            return ""

        s = html_lib.unescape(s)

        if self.fix_ocr_errors:
            for bad, good in _DEFAULT_ENCODING_FIXES:
                s = s.replace(bad, good)

        if self.normalize_unicode:
            s = unicodedata.normalize("NFKC", s)

        # Collapse whitespace
        s = re.sub(r"[ \t]+", " ", s)
        s = re.sub(r"\n{3,}", "\n\n", s)
        s = s.strip()

        if self.normalize_terminology:
            # Keep minimal: no aggressive replacements.
            pass

        return s

    def clean_sections(self, sections: Any) -> List[Dict[str, str]]:
        if not isinstance(sections, list):
            return []

        cleaned: List[Dict[str, str]] = []
        seen_hashes: set[str] = set()

        for section in sections:
            if not isinstance(section, dict):
                continue

            heading = self.clean_text(section.get("heading", ""))
            content = self.clean_text(section.get("content", ""))

            if not heading and not content:
                continue

            # Merge numeric headings (common: merchant codes) into previous section
            if re.fullmatch(r"\d{3,}", heading):
                if cleaned:
                    cleaned[-1]["content"] = (cleaned[-1]["content"] + "\n" + content).strip()
                continue

            # Improve step headings (optional)
            if self.improve_step_headings and heading.lower().startswith("step"):
                heading = self._improve_step_heading(heading, content)

            # Deduplicate by normalized content (heading+content)
            dedupe_key = re.sub(r"\s+", " ", f"{heading}\n{content}".strip().lower())
            h = str(hash(dedupe_key))
            if h in seen_hashes:
                continue
            seen_hashes.add(h)

            cleaned.append({"heading": heading, "content": content})

        return cleaned

    def clean_faqs(self, faqs: Any) -> List[Dict[str, str]]:
        if not isinstance(faqs, list):
            return []

        cleaned: List[Dict[str, str]] = []
        seen_questions: set[str] = set()

        for faq in faqs:
            if not isinstance(faq, dict):
                continue
            q = self.clean_text(faq.get("question", ""))
            a = self.clean_text(faq.get("answer", ""))
            if not q and not a:
                continue

            key = re.sub(r"\s+", " ", q.lower()).strip()
            if key and key in seen_questions:
                continue
            if key:
                seen_questions.add(key)

            cleaned.append({"question": q, "answer": a})

        return cleaned

    def _improve_step_heading(self, heading: str, content: str) -> str:
        c = content.lower()
        if "dial *185#" in c or "mtn" in c:
            return f"{heading} (MTN Mobile Money)"
        if "dial *291#" in c or "airtel" in c:
            return f"{heading} (Airtel Money)"
        if "flexipay" in c:
            return f"{heading} (FlexiPay)"
        if "bank" in c:
            return f"{heading} (Banking)"
        return heading
