"""Tiny module for LLM mutation e2e tests. Kept minimal to reduce API cost."""


def fibonacci(n):
    """Return the nth Fibonacci number."""
    if n <= 0:
        return 0
    if n == 1:
        return 1
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b


def is_palindrome(s):
    """Check if a string is a palindrome (case-insensitive)."""
    cleaned = s.lower().strip()
    return cleaned == cleaned[::-1]
