"""Tests for text_utils — designed to kill mutants effectively."""
from real_world.text_utils import count_words
from real_world.text_utils import extract_emails
from real_world.text_utils import is_valid_identifier
from real_world.text_utils import normalize_whitespace
from real_world.text_utils import render_template
from real_world.text_utils import slugify
from real_world.text_utils import truncate


class TestNormalizeWhitespace:
    def test_collapses_spaces(self):
        assert normalize_whitespace("a  b   c") == "a b c"

    def test_strips_leading_trailing(self):
        assert normalize_whitespace("  hello  ") == "hello"

    def test_handles_tabs_and_newlines(self):
        assert normalize_whitespace("a\t\nb") == "a b"

    def test_empty_string(self):
        assert normalize_whitespace("") == ""

    def test_single_word(self):
        assert normalize_whitespace("word") == "word"


class TestExtractEmails:
    def test_finds_single_email(self):
        assert extract_emails("contact: foo@bar.com") == ["foo@bar.com"]

    def test_finds_multiple(self):
        result = extract_emails("a@b.co and c@d.org")
        assert result == ["a@b.co", "c@d.org"]

    def test_no_emails(self):
        assert extract_emails("no emails here") == []

    def test_ignores_invalid(self):
        assert extract_emails("not@an@email") == []


class TestSlugify:
    def test_basic(self):
        assert slugify("Hello World") == "hello-world"

    def test_strips_leading_trailing_hyphens(self):
        assert slugify("--hello--") == "hello"

    def test_special_chars(self):
        assert slugify("foo & bar!") == "foo-bar"

    def test_already_slug(self):
        assert slugify("already-slug") == "already-slug"

    def test_empty(self):
        assert slugify("") == ""


class TestTruncate:
    def test_short_text_unchanged(self):
        assert truncate("hi", 10) == "hi"

    def test_exact_length(self):
        assert truncate("hello", 5) == "hello"

    def test_truncates_with_suffix(self):
        assert truncate("hello world", 8) == "hello..."

    def test_custom_suffix(self):
        assert truncate("hello world", 7, suffix="~") == "hello ~"

    def test_max_len_equals_suffix_len(self):
        assert truncate("hello world", 3) == "..."

    def test_max_len_less_than_suffix_len(self):
        assert truncate("hello world", 2) == ".."

    def test_zero_max_len(self):
        assert truncate("hello", 0) == ""


class TestIsValidIdentifier:
    def test_valid(self):
        assert is_valid_identifier("foo") is True

    def test_keyword_rejected(self):
        assert is_valid_identifier("class") is False

    def test_starts_with_digit(self):
        assert is_valid_identifier("3abc") is False

    def test_non_string(self):
        assert is_valid_identifier(42) is False

    def test_empty_string(self):
        assert is_valid_identifier("") is False

    def test_underscore(self):
        assert is_valid_identifier("_var") is True


class TestRenderTemplate:
    def test_replaces_placeholder(self):
        assert render_template("hi {{name}}", {"name": "Al"}) == "hi Al"

    def test_multiple_placeholders(self):
        result = render_template("{{a}} and {{b}}", {"a": "1", "b": "2"})
        assert result == "1 and 2"

    def test_missing_key_left_as_is(self):
        assert render_template("{{missing}}", {}) == "{{missing}}"

    def test_no_placeholders(self):
        assert render_template("plain text", {"key": "val"}) == "plain text"


class TestCountWords:
    def test_basic(self):
        assert count_words("one two three") == 3

    def test_empty(self):
        assert count_words("") == 0

    def test_whitespace_only(self):
        assert count_words("   ") == 0

    def test_single_word(self):
        assert count_words("hello") == 1
