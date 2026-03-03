"""Tests for the demo module — designed to kill most mutants."""

from demo import (
    classify,
    clamp,
    head,
    middle_elements,
    safe_divide,
    validated_age,
)


def test_safe_divide_normal():
    assert safe_divide(10, 2) == 5.0


def test_safe_divide_zero():
    """If exception handler becomes pass, this would return None instead of -1."""
    assert safe_divide(1, 0) == -1


def test_safe_divide_returns_value():
    """Catches return <expr> -> return None."""
    result = safe_divide(6, 3)
    assert result is not None
    assert result == 2.0


def test_clamp_within_range():
    assert clamp(5, 0, 10) == 5


def test_clamp_below():
    """Catches always-false and swapped branches."""
    assert clamp(-5, 0, 10) == 0


def test_clamp_above():
    assert clamp(15, 0, 10) == 10


def test_validated_age_valid():
    assert validated_age(25) == 25


def test_validated_age_negative():
    """If assert becomes True, this won't raise."""
    try:
        validated_age(-1)
        assert False, "Should have raised AssertionError"
    except AssertionError:
        pass


def test_validated_age_too_old():
    try:
        validated_age(300)
        assert False, "Should have raised AssertionError"
    except AssertionError:
        pass


def test_middle_elements():
    assert middle_elements([1, 2, 3, 4, 5]) == [2, 3, 4]


def test_middle_elements_short():
    assert middle_elements([1, 2]) == []


def test_head():
    assert head([1, 2, 3, 4, 5], 3) == [1, 2, 3]


def test_head_zero():
    assert head([1, 2, 3], 0) == []


def test_classify_pass():
    assert classify(75) == "pass"


def test_classify_fail():
    assert classify(30) == "fail"


def test_classify_boundary():
    assert classify(50) == "pass"
