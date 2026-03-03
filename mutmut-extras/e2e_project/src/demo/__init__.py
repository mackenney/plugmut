"""Demo module exercising all mutmut-extras operator targets."""


def safe_divide(a, b):
    """Return a/b, or None on error. Exercises: return_none, exception_handler."""
    try:
        result = a / b
    except ZeroDivisionError:
        return -1
    return result


def clamp(value, lo, hi):
    """Clamp value to [lo, hi]. Exercises: ternary."""
    return lo if value < lo else (hi if value > hi else value)


def validated_age(age):
    """Validate age is positive. Exercises: assert_true."""
    assert age >= 0, "age must be non-negative"
    assert age < 200, "age must be realistic"
    return age


def middle_elements(items):
    """Return the middle portion of a list. Exercises: slice_removal."""
    return items[1:-1]


def head(items, n):
    """Return first n items. Exercises: slice_removal."""
    return items[:n]


def classify(score):
    """Classify a score. Exercises: ternary, return_none."""
    label = "pass" if score >= 50 else "fail"
    return label
