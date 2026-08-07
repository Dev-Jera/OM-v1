"""
Content validation utilities for scraped data
"""

import re
import hashlib
from typing import Dict, Optional, Set
import logging
from langdetect import detect, LangDetectException

logger = logging.getLogger(__name__)


class ContentValidator:
    """Validates scraped content quality"""

    def __init__(
        self,
        min_content_length: int = 100,
        max_content_length: int = 1000000,
        min_chunk_length: int = 50,
        max_chunk_length: int = 2000,
        expected_language: str = "en",
        check_language: bool = True,
    ):
        """
        Initialize content validator

        Args:
            min_content_length: Minimum acceptable content length
            max_content_length: Maximum acceptable content length
            min_chunk_length: Minimum chunk length for validation
            max_chunk_length: Maximum chunk length for validation
            expected_language: Expected language code (default: 'en')
            check_language: Whether to check content language
        """
        self.min_content_length = min_content_length
        self.max_content_length = max_content_length
        self.min_chunk_length = min_chunk_length
        self.max_chunk_length = max_chunk_length
        self.expected_language = expected_language
        self.check_language = check_language

        # Common error page indicators
        self.error_indicators = [
            r"404",
            r"not found",
            r"page not found",
            r"error 500",
            r"internal server error",
            r"access denied",
            r"forbidden",
            r"403",
            r"500",
        ]

    def validate_content(self, content: str, url: Optional[str] = None) -> Dict[str, any]:
        """
        Validate scraped content

        Args:
            content: Content to validate
            url: Source URL (for logging)

        Returns:
            Dict with validation results:
            - valid: bool
            - errors: list of error messages
            - warnings: list of warning messages
            - quality_score: float (0-1)
        """
        errors = []
        warnings = []
        quality_score = 1.0

        if not content:
            errors.append("Content is empty")
            return {"valid": False, "errors": errors, "warnings": warnings, "quality_score": 0.0}

        content = content.strip()
        content_length = len(content)

        # Check minimum length
        if content_length < self.min_content_length:
            errors.append(f"Content too short: {content_length} chars " f"(minimum: {self.min_content_length})")
            quality_score *= 0.3

        # Check maximum length
        if content_length > self.max_content_length:
            warnings.append(f"Content very long: {content_length} chars " f"(maximum: {self.max_content_length})")
            quality_score *= 0.9

        # Check for error pages
        content_lower = content.lower()
        for indicator in self.error_indicators:
            if re.search(indicator, content_lower):
                errors.append(f"Error page detected: {indicator}")
                quality_score = 0.0
                break

        # Check for meaningful content (not just navigation/boilerplate)
        if self._is_mostly_boilerplate(content):
            warnings.append("Content appears to be mostly boilerplate/navigation")
            quality_score *= 0.5

        # Language detection
        if self.check_language:
            lang_result = self._check_language(content)
            if not lang_result["matches"]:
                warnings.append(f"Language mismatch: detected '{lang_result['detected']}', " f"expected '{self.expected_language}'")
                quality_score *= 0.7

        # Check for minimum word count
        word_count = len(content.split())
        if word_count < 20:
            errors.append(f"Too few words: {word_count} (minimum: 20)")
            quality_score *= 0.4

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "quality_score": max(0.0, min(1.0, quality_score)),
            "content_length": content_length,
            "word_count": word_count,
        }

    def _is_mostly_boilerplate(self, content: str) -> bool:
        """Check if content is mostly navigation/boilerplate"""
        # Common boilerplate patterns
        boilerplate_patterns = [
            r"cookie",
            r"privacy policy",
            r"terms and conditions",
            r"copyright",
            r"all rights reserved",
            r"home.*about.*contact",
        ]

        content_lower = content.lower()
        boilerplate_matches = sum(1 for pattern in boilerplate_patterns if re.search(pattern, content_lower))

        # If multiple boilerplate patterns found, likely boilerplate
        return boilerplate_matches >= 3

    def _check_language(self, content: str) -> Dict[str, any]:
        """Check content language"""
        try:
            # Sample first 1000 chars for language detection (faster)
            sample = content[:1000] if len(content) > 1000 else content
            detected = detect(sample)
            return {"detected": detected, "matches": detected == self.expected_language}
        except LangDetectException as e:
            logger.warning(f"Language detection failed: {e}")
            return {"detected": "unknown", "matches": True}  # Don't fail validation if detection fails

    def validate_chunk(self, chunk: str) -> Dict[str, any]:
        """Validate a text chunk"""
        chunk_length = len(chunk.strip())

        errors = []
        if chunk_length < self.min_chunk_length:
            errors.append(f"Chunk too short: {chunk_length} chars " f"(minimum: {self.min_chunk_length})")
        if chunk_length > self.max_chunk_length:
            errors.append(f"Chunk too long: {chunk_length} chars " f"(maximum: {self.max_chunk_length})")

        return {"valid": len(errors) == 0, "errors": errors, "length": chunk_length}

    def is_duplicate_content(self, content: str, seen_hashes: Set[str]) -> tuple[bool, str]:
        """
        Check if content is duplicate based on hash

        Args:
            content: Content to check
            seen_hashes: Set of content hashes already seen

        Returns:
            Tuple of (is_duplicate: bool, content_hash: str)
        """
        # Normalize content for hashing (remove extra whitespace)
        normalized = re.sub(r"\s+", " ", content.strip().lower())
        content_hash = hashlib.md5(normalized.encode("utf-8")).hexdigest()

        is_duplicate = content_hash in seen_hashes
        if not is_duplicate:
            seen_hashes.add(content_hash)

        return is_duplicate, content_hash
