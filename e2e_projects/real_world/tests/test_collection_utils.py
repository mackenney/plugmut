"""Tests for collection_utils — designed to kill mutants effectively."""
from real_world.collection_utils import deduplicate
from real_world.collection_utils import flatten
from real_world.collection_utils import group_by
from real_world.collection_utils import merge_dicts
from real_world.collection_utils import paginate
from real_world.collection_utils import take_while


class TestDeduplicate:
    def test_removes_duplicates(self):
        assert deduplicate([1, 2, 2, 3, 1]) == [1, 2, 3]

    def test_preserves_order(self):
        assert deduplicate([3, 1, 2, 1, 3]) == [3, 1, 2]

    def test_empty(self):
        assert deduplicate([]) == []

    def test_no_duplicates(self):
        assert deduplicate([1, 2, 3]) == [1, 2, 3]

    def test_all_same(self):
        assert deduplicate([5, 5, 5]) == [5]


class TestMergeDicts:
    def test_basic_merge(self):
        assert merge_dicts({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}

    def test_override(self):
        assert merge_dicts({"a": 1}, {"a": 2}) == {"a": 2}

    def test_empty_override(self):
        assert merge_dicts({"a": 1}, {}) == {"a": 1}

    def test_empty_base(self):
        assert merge_dicts({}, {"a": 1}) == {"a": 1}

    def test_both_empty(self):
        assert merge_dicts({}, {}) == {}


class TestPaginate:
    def test_first_page(self):
        assert paginate([1, 2, 3, 4, 5], page=1, page_size=2) == [1, 2]

    def test_second_page(self):
        assert paginate([1, 2, 3, 4, 5], page=2, page_size=2) == [3, 4]

    def test_last_partial_page(self):
        assert paginate([1, 2, 3, 4, 5], page=3, page_size=2) == [5]

    def test_beyond_last_page(self):
        assert paginate([1, 2, 3], page=5, page_size=2) == []

    def test_page_zero_returns_empty(self):
        assert paginate([1, 2, 3], page=0, page_size=2) == []

    def test_negative_page_returns_empty(self):
        assert paginate([1, 2, 3], page=-1) == []

    def test_page_size_zero_returns_empty(self):
        assert paginate([1, 2, 3], page=1, page_size=0) == []

    def test_default_page_size(self):
        items = list(range(25))
        assert paginate(items, page=1) == list(range(10))

    def test_empty_list(self):
        assert paginate([], page=1) == []


class TestGroupBy:
    def test_basic(self):
        result = group_by([1, 2, 3, 4], lambda x: x % 2)
        assert result == {1: [1, 3], 0: [2, 4]}

    def test_empty(self):
        assert group_by([], lambda x: x) == {}

    def test_all_same_key(self):
        result = group_by(["a", "b", "c"], lambda _: "same")
        assert result == {"same": ["a", "b", "c"]}

    def test_string_grouping(self):
        result = group_by(["apple", "ant", "banana"], lambda s: s[0])
        assert result == {"a": ["apple", "ant"], "b": ["banana"]}


class TestFlatten:
    def test_nested_lists(self):
        assert flatten([[1, 2], [3, [4, 5]]]) == [1, 2, 3, 4, 5]

    def test_already_flat(self):
        assert flatten([1, 2, 3]) == [1, 2, 3]

    def test_empty(self):
        assert flatten([]) == []

    def test_strings_not_expanded(self):
        assert flatten(["hello", ["world"]]) == ["hello", "world"]

    def test_deep_nesting(self):
        assert flatten([[[1]], [[2]], [[[3]]]]) == [1, 2, 3]


class TestTakeWhile:
    def test_basic(self):
        assert take_while(lambda x: x < 3, [1, 2, 3, 4]) == [1, 2]

    def test_all_pass(self):
        assert take_while(lambda x: x > 0, [1, 2, 3]) == [1, 2, 3]

    def test_none_pass(self):
        assert take_while(lambda x: x > 10, [1, 2, 3]) == []

    def test_empty(self):
        assert take_while(lambda x: True, []) == []

    def test_stops_at_first_false(self):
        assert take_while(lambda x: x != 3, [1, 2, 3, 2, 1]) == [1, 2]
