"""Verify that plugin autoload via entry_points discovers plugmut-extras."""

import os

from mutmut.file_mutation import create_mutations
from mutmut.file_mutation import reset_plugin_operators
from mutmut.plugin_manager import get_plugin_manager
from mutmut.plugin_manager import reset_plugin_manager


def _with_autoload_disabled(fn):
    """Run fn with autoload disabled, then restore the original env state."""
    original = os.environ.get("PLUGMUT_DISABLE_PLUGIN_AUTOLOAD")
    os.environ["PLUGMUT_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    reset_plugin_manager()
    reset_plugin_operators()
    try:
        return fn()
    finally:
        if original is None:
            os.environ.pop("PLUGMUT_DISABLE_PLUGIN_AUTOLOAD", None)
        else:
            os.environ["PLUGMUT_DISABLE_PLUGIN_AUTOLOAD"] = original
        reset_plugin_manager()
        reset_plugin_operators()


def _with_autoload_enabled(fn):
    """Run fn with autoload enabled, then restore the original env state."""
    original = os.environ.get("PLUGMUT_DISABLE_PLUGIN_AUTOLOAD")
    os.environ.pop("PLUGMUT_DISABLE_PLUGIN_AUTOLOAD", None)
    reset_plugin_manager()
    reset_plugin_operators()
    try:
        return fn()
    finally:
        if original is None:
            os.environ.pop("PLUGMUT_DISABLE_PLUGIN_AUTOLOAD", None)
        else:
            os.environ["PLUGMUT_DISABLE_PLUGIN_AUTOLOAD"] = original
        reset_plugin_manager()
        reset_plugin_operators()


def test_extras_plugin_autoloads():
    """With no PLUGMUT_DISABLE_PLUGIN_AUTOLOAD, extras registers via entry_points."""

    def check():
        pm = get_plugin_manager()
        plugin_names = {name for name, _ in pm.list_name_plugin() if name}
        assert "extras" in plugin_names, f"Expected 'extras' in registered plugins, got: {plugin_names}"

    _with_autoload_enabled(check)


def test_autoloaded_extras_produces_more_mutations():
    """Autoloaded extras plugin produces strictly more mutations than builtins alone."""
    source = """\
def safe_divide(a, b):
    try:
        return a / b
    except ZeroDivisionError:
        return None
"""

    def get_baseline_count():
        _, baseline = create_mutations(source)
        return len(baseline)

    def get_extras_count():
        _, with_extras = create_mutations(source)
        return len(with_extras)

    baseline_count = _with_autoload_disabled(get_baseline_count)
    extras_count = _with_autoload_enabled(get_extras_count)

    assert extras_count > baseline_count, (
        f"Autoloaded extras should produce more mutations ({extras_count}) than builtins alone ({baseline_count})"
    )
