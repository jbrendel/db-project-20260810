import pytest
from research import categories as c


def test_core_always_selected():
    keys = c.selected_category_keys({})
    assert set(c.CORE_CATEGORIES) <= set(keys)
    assert "reddit" not in keys


def test_borderline_added_when_ticked():
    keys = c.selected_category_keys({"reddit": True})
    assert "reddit" in keys
    assert keys.index("news") < keys.index("reddit")  # core before borderline


def test_borderline_not_added_when_unticked():
    keys = c.selected_category_keys({"reddit": False})
    assert "reddit" not in keys


def test_unknown_borderline_key_raises():
    with pytest.raises(KeyError):
        c.selected_category_keys({"nonsense": True})
