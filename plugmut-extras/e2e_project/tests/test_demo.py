"""Tests for the demo module — designed to kill most mutants."""

import pytest
from demo import Animal
from demo import Dog
from demo import build_report
from demo import check_numeric
from demo import clamp
from demo import classify
from demo import clean_input
from demo import compute_difference
from demo import first_come_first_served
from demo import generate_evens
from demo import greet
from demo import has_prefix
from demo import head
from demo import last_index
from demo import middle_elements
from demo import paginate
from demo import positive_values
from demo import resilient_process
from demo import safe_divide
from demo import safe_parse
from demo import validated_age


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


def test_build_report():
    """Catches void_call_removal: if append becomes pass, report is empty."""
    assert build_report(["a", "b", "c"]) == ["A", "B", "C"]


def test_build_report_empty():
    assert build_report([]) == []


def test_generate_evens():
    """Catches yield_mutation: if yield i becomes yield None, values are wrong."""
    assert list(generate_evens(6)) == [0, 2, 4]


def test_generate_evens_zero():
    assert list(generate_evens(0)) == []


def test_positive_values():
    """Catches comprehension_filter_removal: if filter removed, negatives leak through."""
    assert positive_values([-2, -1, 0, 1, 2]) == [1, 2]


def test_positive_values_all_negative():
    assert positive_values([-3, -2, -1]) == []


def test_dog_inherits_name():
    """Catches super_call_deletion: if super().__init__() becomes pass, name missing."""
    dog = Dog("Rex", "Labrador")
    assert dog.name == "Rex"
    assert dog.breed == "Labrador"


def test_animal_init():
    animal = Animal("Cat")
    assert animal.name == "Cat"


def test_greet():
    """Catches fstring_mutation: if {name} becomes {'XX'}, output is wrong."""
    assert greet("World") == "Hello, World!"


def test_greet_empty():
    assert greet("") == "Hello, !"


def test_paginate_default():
    """Catches default_param_mutation: if page_size=10 becomes 11, result changes."""
    items = list(range(20))
    assert paginate(items) == list(range(10))


def test_paginate_explicit():
    assert paginate([1, 2, 3, 4, 5], page_size=3) == [1, 2, 3]


def test_first_come_first_served_order():
    """Catches reverse_iteration: if for-loop is reversed, order changes."""
    assert first_come_first_served([3, 1, 2]) == [3, 1, 2]


def test_first_come_first_served_empty():
    assert first_come_first_served([]) == []


def test_has_prefix_true():
    """Catches startswith->endswith: 'hello'.endswith('hel') is False."""
    assert has_prefix("hello", "hel") is True


def test_has_prefix_false():
    assert has_prefix("hello", "xyz") is False


def test_has_prefix_suffix_distinction():
    """Specifically crafted so startswith != endswith."""
    assert has_prefix("abc", "ab") is True
    assert has_prefix("abc", "bc") is False


def test_clean_input_strips_both_sides():
    """Catches strip->lstrip or strip->rstrip: only partial stripping."""
    assert clean_input("  hello  ") == "hello"


def test_clean_input_left_only():
    assert clean_input("  hello") == "hello"


def test_clean_input_right_only():
    assert clean_input("hello  ") == "hello"


def test_compute_difference():
    """Catches a-b -> b-a: 10-3=7, but 3-10=-7."""
    assert compute_difference(10, 3) == 7


def test_compute_difference_negative():
    assert compute_difference(3, 10) == -7


def test_last_index():
    """Catches len(items)-1 -> len(items): off by one."""
    assert last_index([1, 2, 3]) == 2


def test_last_index_single():
    assert last_index([42]) == 0


def test_check_numeric_int():
    assert check_numeric(42) is True


def test_check_numeric_float():
    """Catches isinstance(x,(int,float))->isinstance(x,int): float rejected."""
    assert check_numeric(3.14) is True


def test_check_numeric_string():
    assert check_numeric("hello") is False


def test_safe_parse_valid():
    assert safe_parse("42") == 42


def test_safe_parse_invalid():
    """Catches ValueError->Exception: would swallow all errors."""
    assert safe_parse("abc") is None


def test_safe_parse_type_error():
    """If broadened to Exception, TypeError would be caught too."""
    with pytest.raises(TypeError):
        safe_parse(None)


def test_resilient_process():
    """Catches pass->break: would stop after first error."""
    assert resilient_process(["1", "bad", "3"]) == [1, 3]


def test_resilient_process_all_valid():
    assert resilient_process(["1", "2", "3"]) == [1, 2, 3]


def test_resilient_process_all_invalid():
    assert resilient_process(["a", "b"]) == []


def test_resilient_process_error_then_valid():
    """Catches pass->continue or pass->return."""
    assert resilient_process(["bad", "1", "bad", "2"]) == [1, 2]
