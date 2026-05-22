"""Demo module exercising all mutmut-extras operator targets.

Every function and method also exercises function_deletion (body replaced with pass).
"""


def safe_divide(a, b):
    """Return a/b, or None on error. Exercises: return_none, exception_handler, function_deletion."""
    try:
        result = a / b
    except ZeroDivisionError:
        return -1
    return result


def clamp(value, lo, hi):
    """Clamp value to [lo, hi]. Exercises: ternary, function_deletion."""
    return lo if value < lo else (hi if value > hi else value)


def validated_age(age):
    """Validate age is positive. Exercises: assert_true, function_deletion."""
    assert age >= 0, "age must be non-negative"
    assert age < 200, "age must be realistic"
    return age


def middle_elements(items):
    """Return the middle portion of a list. Exercises: slice_removal, function_deletion."""
    return items[1:-1]


def head(items, n):
    """Return first n items. Exercises: slice_removal, function_deletion."""
    return items[:n]


def classify(score):
    """Classify a score. Exercises: ternary, return_none, function_deletion."""
    label = "pass" if score >= 50 else "fail"
    return label


def build_report(items):
    """Accumulate uppercased items. Exercises: void_call_removal, reverse_iteration, function_deletion."""
    report = []
    for item in items:
        report.append(item.upper())
    return report


def generate_evens(n):
    """Yield even numbers up to n. Exercises: yield_mutation, function_deletion."""
    for i in range(n):
        if i % 2 == 0:
            yield i


def positive_values(items):
    """Filter to positive values. Exercises: comprehension_filter_removal, function_deletion."""
    return [x for x in items if x > 0]


class Animal:
    def __init__(self, name):
        self.name = name


class Dog(Animal):
    """Exercises: super_call_deletion, function_deletion."""

    def __init__(self, name, breed):
        super().__init__(name)
        self.breed = breed


def greet(name):
    """Exercises: fstring_mutation, function_deletion."""
    return f"Hello, {name}!"


def paginate(items, page_size=10):
    """Exercises: default_param_mutation, slice_removal, function_deletion."""
    return items[:page_size]


def first_come_first_served(tasks):
    """Exercises: reverse_iteration, void_call_removal, function_deletion."""
    result = []
    for task in tasks:
        result.append(task)
    return result


def has_prefix(text, prefix):
    """Exercises: startswith_endswith_swap, function_deletion."""
    return text.startswith(prefix)


def clean_input(text):
    """Exercises: strip_to_partial, function_deletion."""
    return text.strip()


def compute_difference(a, b):
    """Exercises: operand_swap, function_deletion."""
    return a - b


def last_index(items):
    """Exercises: remove_boundary_offset, function_deletion."""
    return len(items) - 1


def check_numeric(value):
    """Exercises: isinstance_type_reduction, function_deletion."""
    return isinstance(value, (int, float))


def safe_parse(text):
    """Exercises: exception_type_broadening, exception_control_flow, function_deletion."""
    try:
        return int(text)
    except ValueError:
        return None


def resilient_process(items):
    """Exercises: exception_control_flow (pass in loop), function_deletion."""
    results = []
    for item in items:
        try:
            results.append(int(item))
        except ValueError:
            pass
    return results
