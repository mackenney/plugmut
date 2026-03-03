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


def build_report(items):
    """Accumulate uppercased items. Exercises: void_call_removal, reverse_iteration."""
    report = []
    for item in items:
        report.append(item.upper())
    return report


def generate_evens(n):
    """Yield even numbers up to n. Exercises: yield_mutation."""
    for i in range(n):
        if i % 2 == 0:
            yield i


def positive_values(items):
    """Filter to positive values. Exercises: comprehension_filter_removal."""
    return [x for x in items if x > 0]


class Animal:
    def __init__(self, name):
        self.name = name


class Dog(Animal):
    """Exercises: super_call_deletion."""
    def __init__(self, name, breed):
        super().__init__(name)
        self.breed = breed


def greet(name):
    """Exercises: fstring_mutation."""
    return f"Hello, {name}!"


def paginate(items, page_size=10):
    """Exercises: default_param_mutation, slice_removal."""
    return items[:page_size]


def first_come_first_served(tasks):
    """Exercises: reverse_iteration, void_call_removal."""
    result = []
    for task in tasks:
        result.append(task)
    return result
