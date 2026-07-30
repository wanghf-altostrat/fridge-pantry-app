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

import pytest

from app.flask_app import parse_shopping_list_line
from app.privacy import (
    contains_personal_data,
    filter_receipt_food_items,
    is_receipt_metadata_line,
    sanitize_dict,
    sanitize_text,
)


def test_sanitize_text():
    raw = (
        "Customer John Doe, Email: john.doe@example.com, Phone: (555) 123-4567, "
        "Card: 4111-2222-3333-4444, Address: 742 Evergreen Terrace, Springfield OR 97477"
    )
    sanitized = sanitize_text(raw)

    assert "[REDACTED CARD]" in sanitized
    assert "[REDACTED EMAIL]" in sanitized
    assert "[REDACTED PHONE]" in sanitized
    assert "[REDACTED ADDRESS]" in sanitized
    assert "4111-2222-3333-4444" not in sanitized
    assert "john.doe@example.com" not in sanitized
    assert "(555) 123-4567" not in sanitized


def test_filter_receipt_food_items():
    receipt_text = """
    TARGET STORE #1042
    100 Market Street, San Jose CA
    Cashier: Sarah
    Member ID: 9812739
    Visa Card #: 4532 1234 5678 9010
    Auth #: 112233

    Items Purchased:
    2 lbs Chicken Breast
    1 carton Milk
    4 Tomatoes
    1 bag Spinach

    Subtotal: $18.50
    Tax: $1.20
    Total Paid: $19.70
    """

    foods = filter_receipt_food_items(receipt_text)

    assert "2 lbs Chicken Breast" in foods
    assert "1 carton Milk" in foods
    assert "4 Tomatoes" in foods
    assert "1 bag Spinach" in foods

    # Verify no receipt metadata or payment data is included
    for food in foods:
        assert not contains_personal_data(food)
        assert not is_receipt_metadata_line(food)


def test_parse_shopping_list_line_privacy():
    # Valid food item line
    valid_parsed = parse_shopping_list_line("2 lbs Chicken Breast")
    assert valid_parsed is not None
    assert valid_parsed["name"] == "Chicken Breast"

    # Personal data / receipt line should be rejected
    assert parse_shopping_list_line("Visa Card #: 4111 2222 3333 4444") is None
    assert parse_shopping_list_line("Total Paid: $25.00") is None
    assert parse_shopping_list_line("Cashier: Sarah") is None
    assert parse_shopping_list_line("Member ID: 998877") is None


def test_sanitize_dict():
    data = {
        "item": "Milk",
        "email": "user@test.com",
        "nested": {"card": "4111222233334444"},
        "tags": ["(555) 000-1111", "fresh"],
    }
    sanitized = sanitize_dict(data)

    assert sanitized["item"] == "Milk"
    assert "[REDACTED EMAIL]" in sanitized["email"]
    assert "[REDACTED CARD]" in sanitized["nested"]["card"]
    assert "[REDACTED PHONE]" in sanitized["tags"][0]
    assert sanitized["tags"][1] == "fresh"
