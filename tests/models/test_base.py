# tests/models/test_base.py

"""Tests for the Pydantic ``Base`` model utilities and field validators."""

import pytest

from src.models.base import Base


class _Person(Base):
    """Concrete model used to exercise ``is_valid`` / ``get_validation_errors``."""

    age: int


def test_is_valid_true_for_well_formed_instance() -> None:
    # Arrange / Act
    person = _Person(age=30)
    # Assert
    assert person.is_valid() is True
    assert person.get_validation_errors() is None


def test_is_valid_false_and_reports_errors_for_malformed_instance() -> None:
    # Arrange: model_construct bypasses validation, producing an invalid instance.
    person = _Person.model_construct(age="not-an-int")
    # Act / Assert
    assert person.is_valid() is False
    errors = person.get_validation_errors()
    assert errors is not None
    assert "age" in errors


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("07911123456", "07911123456"),
        ("7911123456", "07911123456"),  # 10 digits, no leading 0 -> 0 prepended
        (None, None),
    ],
)
def test_validate_phone_number_accepts_valid(raw, expected) -> None:
    assert Base.validate_phone_number(raw, "phone") == expected


@pytest.mark.parametrize("raw", ["123", "abc", "07123456789", "03123456789"])
def test_validate_phone_number_rejects_invalid(raw) -> None:
    with pytest.raises(ValueError):
        Base.validate_phone_number(raw, "phone")


@pytest.mark.parametrize("email", ["alice@example.com", "bob@company.co.uk"])
def test_validate_email_accepts_valid(email) -> None:
    assert Base.validate_email_address(email, "email") == email


@pytest.mark.parametrize("email", ["x@mailinator.com", "y@tempmail.com", "z@10minutemail.com"])
def test_validate_email_rejects_disposable(email) -> None:
    with pytest.raises(ValueError):
        Base.validate_email_address(email, "email")


@pytest.mark.parametrize(
    "zipcode,expected",
    [
        ("SW1A 1AA", "SW1A 1AA"),
        ("ec1a 1bb", "ec1a 1bb"),  # case-insensitive
        (None, None),
    ],
)
def test_validate_zipcode_accepts_valid(zipcode, expected) -> None:
    assert Base.validate_zipcode(zipcode) == expected


@pytest.mark.parametrize("zipcode", ["ZZZ", "12345", "SW1A"])
def test_validate_zipcode_rejects_invalid(zipcode) -> None:
    with pytest.raises(ValueError):
        Base.validate_zipcode(zipcode)
