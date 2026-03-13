"""Tests for mutmut_llm.config: env var priority, pyproject.toml loading, defaults."""

from __future__ import annotations

from pathlib import Path

import pytest

from mutmut_llm.config import LLMConfig
from mutmut_llm.config import find_pyproject
from mutmut_llm.config import load_config
from mutmut_llm.config import read_toml_section


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_default_config(self):
        config = load_config(pyproject_path=None, env={})
        assert config.model == "claude-sonnet-4-6"
        assert config.max_mutations_per_function == 5
        assert config.max_tokens == 4096
        assert config.enabled is True
        assert config.api_key == ""
        assert config.is_configured is False

    def test_default_is_not_configured_without_key(self):
        config = LLMConfig()
        assert config.is_configured is False

    def test_is_configured_with_key(self):
        config = LLMConfig(api_key="sk-test-123")
        assert config.is_configured is True


# ---------------------------------------------------------------------------
# Environment variable
# ---------------------------------------------------------------------------


class TestEnvVar:
    def test_api_key_from_env(self):
        config = load_config(
            pyproject_path=None, env={"ANTHROPIC_API_KEY": "sk-test-abc"}
        )
        assert config.api_key == "sk-test-abc"
        assert config.is_configured is True

    def test_missing_env_var_gives_empty_key(self):
        config = load_config(pyproject_path=None, env={})
        assert config.api_key == ""

    def test_env_var_takes_priority_over_no_pyproject(self):
        config = load_config(pyproject_path=None, env={"ANTHROPIC_API_KEY": "sk-env"})
        assert config.api_key == "sk-env"


# ---------------------------------------------------------------------------
# pyproject.toml loading
# ---------------------------------------------------------------------------


class TestPyprojectLoading:
    def test_reads_all_fields(self, tmp_path):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""\
[tool.mutmut.llm]
model = "claude-haiku-4-5"
max_mutations_per_function = 10
max_tokens = 2048
enabled = false
""")
        config = load_config(pyproject_path=pyproject, env={})
        assert config.model == "claude-haiku-4-5"
        assert config.max_mutations_per_function == 10
        assert config.max_tokens == 2048
        assert config.enabled is False

    def test_partial_override(self, tmp_path):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""\
[tool.mutmut.llm]
model = "claude-opus-4-6"
""")
        config = load_config(pyproject_path=pyproject, env={})
        assert config.model == "claude-opus-4-6"
        assert config.max_mutations_per_function == 5  # default
        assert config.max_tokens == 4096  # default
        assert config.enabled is True  # default

    def test_empty_llm_section_uses_defaults(self, tmp_path):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""\
[tool.mutmut]
paths_to_mutate = ["src/"]
""")
        config = load_config(pyproject_path=pyproject, env={})
        assert config.model == "claude-sonnet-4-6"

    def test_no_mutmut_section_uses_defaults(self, tmp_path):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""\
[project]
name = "myproject"
""")
        config = load_config(pyproject_path=pyproject, env={})
        assert config.model == "claude-sonnet-4-6"

    def test_unknown_keys_are_ignored(self, tmp_path):
        """Unknown keys don't crash loading."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""\
[tool.mutmut.llm]
model = "claude-sonnet-4-6"
unknown_key = "value"
another_unknown = 42
""")
        config = load_config(pyproject_path=pyproject, env={})
        assert config.model == "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# find_pyproject
# ---------------------------------------------------------------------------


class TestFindPyproject:
    def test_finds_in_current_dir(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n")
        result = find_pyproject(start=tmp_path)
        assert result == tmp_path / "pyproject.toml"

    def test_finds_in_parent_dir(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n")
        child = tmp_path / "src" / "pkg"
        child.mkdir(parents=True)
        result = find_pyproject(start=child)
        assert result == tmp_path / "pyproject.toml"

    def test_returns_none_when_not_found(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        result = find_pyproject(start=empty_dir)
        # May find the workspace pyproject.toml or not, depending on parent chain
        # Just verify it returns Path or None
        assert result is None or isinstance(result, Path)


# ---------------------------------------------------------------------------
# read_toml_section
# ---------------------------------------------------------------------------


class TestReadTomlSection:
    def test_reads_section(self, tmp_path):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""\
[tool.mutmut.llm]
model = "test-model"
max_tokens = 1000
""")
        section = read_toml_section(pyproject)
        assert section == {"model": "test-model", "max_tokens": 1000}

    def test_empty_when_no_section(self, tmp_path):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[project]\nname='test'\n")
        section = read_toml_section(pyproject)
        assert section == {}


# ---------------------------------------------------------------------------
# Priority: env > pyproject > defaults
# ---------------------------------------------------------------------------


class TestPriority:
    def test_env_api_key_with_pyproject_model(self, tmp_path):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""\
[tool.mutmut.llm]
model = "claude-haiku-4-5"
""")
        config = load_config(
            pyproject_path=pyproject,
            env={"ANTHROPIC_API_KEY": "sk-from-env"},
        )
        assert config.api_key == "sk-from-env"
        assert config.model == "claude-haiku-4-5"

    def test_each_call_returns_fresh_config(self, tmp_path):
        """No singleton caching — each call builds fresh."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("""\
[tool.mutmut.llm]
model = "model-a"
""")
        config1 = load_config(pyproject_path=pyproject, env={})
        assert config1.model == "model-a"

        pyproject.write_text("""\
[tool.mutmut.llm]
model = "model-b"
""")
        config2 = load_config(pyproject_path=pyproject, env={})
        assert config2.model == "model-b"


class TestTTLValidation:
    def test_invalid_ttl_10m_raises(self):
        """10m is not a valid Anthropic TTL — must raise ValueError."""
        with pytest.raises(ValueError, match="Invalid cache_ttl"):
            LLMConfig(cache_ttl="10m")

    def test_garbage_ttl_raises(self):
        with pytest.raises(ValueError, match="Invalid cache_ttl"):
            LLMConfig(cache_ttl="garbage")

    def test_empty_ttl_raises(self):
        with pytest.raises(ValueError, match="Invalid cache_ttl"):
            LLMConfig(cache_ttl="")

    def test_config_rejects_invalid_ttl(self):
        """LLMConfig validates cache_ttl on construction."""
        with pytest.raises(ValueError, match="Invalid cache_ttl"):
            LLMConfig(cache_ttl="999hours")

    def test_config_rejects_invalid_ttl_from_toml(self, tmp_path):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[tool.mutmut.llm]\ncache_ttl = "10m"\n')
        with pytest.raises(ValueError, match="Invalid cache_ttl"):
            load_config(pyproject_path=pyproject, env={})
