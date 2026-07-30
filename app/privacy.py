# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Privacy and personal data protection guardrails for Fridge & Pantry Agent."""

import logging
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Regex patterns for sensitive personal data
CARD_REGEX = re.compile(r"\b(?:\d[ -]*?){13,16}\b")
EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_REGEX = re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
ADDRESS_REGEX = re.compile(
    r"\b\d{1,5}\s+[A-Za-z0-9\s,.]+?\b(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Way|Terrace|Ter|Court|Ct|Circle|Cir|Place|Pl)\b",
    re.IGNORECASE,
)
PAYMENT_META_REGEX = re.compile(
    r"(?i)\b(visa|mastercard|amex|discover|card\s*#|auth\s*#|trans\s*#|cashier|member\s*#|loyalty\s*#|account\s*#|subtotal|total\s*(?:paid)?|tax|receipt\s*#|change\s*due|amount\s*due)\b"
)
RECEIPT_HEADER_KEYWORDS = [
    "store #",
    "cashier",
    "auth #",
    "member id",
    "loyalty #",
    "transaction #",
    "items purchased:",
    "subtotal:",
    "total paid:",
    "order #",
]


def contains_personal_data(text: str) -> bool:
    """Checks if text contains personal, contact, address, or payment data."""
    if not text:
        return False
    if CARD_REGEX.search(text) or EMAIL_REGEX.search(text) or PHONE_REGEX.search(text):
        return True
    if ADDRESS_REGEX.search(text) or PAYMENT_META_REGEX.search(text):
        return True
    return False


def sanitize_text(text: str) -> str:
    """Redacts sensitive personal, payment, and address data from text."""
    if not text:
        return text
    sanitized = CARD_REGEX.sub("[REDACTED CARD]", text)
    sanitized = EMAIL_REGEX.sub("[REDACTED EMAIL]", sanitized)
    sanitized = PHONE_REGEX.sub("[REDACTED PHONE]", sanitized)
    sanitized = ADDRESS_REGEX.sub("[REDACTED ADDRESS]", sanitized)
    if sanitized != text:
        logger.info("PRIVACY GUARDRAIL [REDACTION]: Redacted sensitive personal/payment details from text.")
    return sanitized.strip()


def is_receipt_metadata_line(line: str) -> bool:
    """Determines whether a line in a receipt or shopping list contains non-food metadata or personal info."""
    line_clean = line.strip().lower()
    if not line_clean:
        return True
    if contains_personal_data(line):
        return True
    if any(kw in line_clean for kw in RECEIPT_HEADER_KEYWORDS):
        return True
    return False


def filter_receipt_food_items(text: str) -> List[str]:
    """Filters raw receipt text to extract candidate food item lines while removing all personal/payment metadata."""
    if not text:
        return []
    lines = text.replace(",", "\n").splitlines()
    food_lines = []
    filtered_count = 0
    for line in lines:
        line_clean = line.strip()
        if not line_clean:
            continue
        if is_receipt_metadata_line(line_clean):
            filtered_count += 1
            continue
        food_lines.append(line_clean)
    logger.info(f"PRIVACY GUARDRAIL [RECEIPT FILTER]: Extracted {len(food_lines)} food line(s) and filtered out {filtered_count} non-food metadata line(s).")
    return food_lines


def sanitize_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively sanitizes dictionary string values to strip personal data."""
    sanitized = {}
    for key, value in data.items():
        if isinstance(value, str):
            sanitized[key] = sanitize_text(value)
        elif isinstance(value, dict):
            sanitized[key] = sanitize_dict(value)
        elif isinstance(value, list):
            sanitized[key] = [
                sanitize_text(v) if isinstance(v, str) else v for v in value
            ]
        else:
            sanitized[key] = value
    return sanitized
