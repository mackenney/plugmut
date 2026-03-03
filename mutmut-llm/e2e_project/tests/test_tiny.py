"""Tests for tiny module. Intentionally incomplete to allow some mutations to survive."""

from tiny import fibonacci, is_palindrome


def test_fibonacci_base_cases():
    assert fibonacci(0) == 0
    assert fibonacci(1) == 1


def test_fibonacci_sequence():
    assert fibonacci(5) == 5
    assert fibonacci(10) == 55


def test_is_palindrome_true():
    assert is_palindrome("racecar")
    assert is_palindrome("Madam")


def test_is_palindrome_false():
    assert not is_palindrome("hello")
