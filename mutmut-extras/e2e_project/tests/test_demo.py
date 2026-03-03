"""Tests for the demo module — designed to kill most mutants."""

import pytest

from demo import (
    Animal,
    Dog,
    build_report,
    classify,
    clamp,
    first_come_first_served,
    generate_evens,
    greet,
    head,
    middle_elements,
    paginate,
    positive_values,
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
    with pytest.raises(AssertionError):
        validated_age(-1)


def test_validated_age_too_old():
    with pytest.raises(AssertionError):
        validated_age(300)


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


# --- void_call_removal ---

def test_build_report():
    """Catches void_call_removal: if append becomes pass, report is empty."""
    assert build_report(["a", "b", "c"]) == ["A", "B", "C"]


def test_build_report_empty():
    assert build_report([]) == []


# --- yield_mutation ---

def test_generate_evens():
    """Catches yield_mutation: if yield i becomes yield None, values are wrong."""
    assert list(generate_evens(6)) == [0, 2, 4]


def test_generate_evens_zero():
    assert list(generate_evens(0)) == []


# --- comprehension_filter_removal ---

def test_positive_values():
    """Catches comprehension_filter_removal: if filter removed, negatives leak through."""
    assert positive_values([-2, -1, 0, 1, 2]) == [1, 2]


def test_positive_values_all_negative():
    assert positive_values([-3, -2, -1]) == []


# --- super_call_deletion ---

def test_dog_inherits_name():
    """Catches super_call_deletion: if super().__init__() becomes pass, name missing."""
    dog = Dog("Rex", "Labrador")
    assert dog.name == "Rex"
    assert dog.breed == "Labrador"


def test_animal_init():
    animal = Animal("Cat")
    assert animal.name == "Cat"


# --- fstring_mutation ---

def test_greet():
    """Catches fstring_mutation: if {name} becomes {'XX'}, output is wrong."""
    assert greet("World") == "Hello, World!"


def test_greet_empty():
    assert greet("") == "Hello, !"


# --- default_param_mutation ---

def test_paginate_default():
    """Catches default_param_mutation: if page_size=10 becomes 11, result changes."""
    items = list(range(20))
    assert paginate(items) == list(range(10))


def test_paginate_explicit():
    assert paginate([1, 2, 3, 4, 5], page_size=3) == [1, 2, 3]


# --- reverse_iteration ---

def test_first_come_first_served_order():
    """Catches reverse_iteration: if for-loop is reversed, order changes."""
    assert first_come_first_served([3, 1, 2]) == [3, 1, 2]


def test_first_come_first_served_empty():
    assert first_come_first_served([]) == []
