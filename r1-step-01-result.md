# Step 01 Result: Core Namespace Rename

**Status:** Step 01 complete ✅ (commit daacd05)

## Summary

Renamed pluggy namespace and PyPI package name from `mutmut` to `plugmut`. All acceptance criteria pass.

## Changes Made

The step plan listed 4 files, but 4 additional files required mechanical updates because `uv_build` needs `module-name` to map package→module, and the workspace/plugin packages reference the package by name.

### Core package (`mutmut/` submodule) — commit 2603846
| File | Change |
|------|--------|
| `src/mutmut/hookspecs.py` | `HookspecMarker("mutmut")` → `HookspecMarker("plugmut")`, `HookimplMarker("mutmut")` → `HookimplMarker("plugmut")` |
| `src/mutmut/plugin_manager.py` | `PluginManager("mutmut")` → `PluginManager("plugmut")`, `load_setuptools_entrypoints("mutmut")` → `("plugmut")`, error message string |
| `src/mutmut/__init__.py` | `importlib.metadata.version("mutmut")` → `importlib.metadata.version("plugmut")` |
| `src/mutmut/__main__.py` | `@click.version_option()` → `@click.version_option(package_name="plugmut")` (click auto-detects `mutmut` without this) |
| `pyproject.toml` | `name = "mutmut"` → `name = "plugmut"`, `mutmut = "mutmut.__main__:cli"` → `plugmut = "mutmut.__main__:cli"`, added `module-name = "mutmut"` to `[tool.uv.build-backend]` (required: uv_build defaults module name to package name; without this it looks for `src/plugmut/`) |

### Workspace and plugin packages — commit daacd05 (parent repo)
| File | Change |
|------|--------|
| `pyproject.toml` (root) | `"mutmut"` → `"plugmut"` in deps; `mutmut = { workspace = true }` → `plugmut = { workspace = true }` in sources |
| `mutmut-dedup/pyproject.toml` | dep `mutmut>=3.5.0` → `plugmut>=4.0.0`; entry-point group `[project.entry-points.mutmut]` → `[project.entry-points.plugmut]`; workspace source ref |
| `mutmut-extras/pyproject.toml` | same pattern |
| `mutmut-llm/pyproject.toml` | dep + entry-point group (no workspace source section) |

## Acceptance Criteria Results

| Criterion | Result |
|-----------|--------|
| `hookimpl.project_name` → `plugmut` | ✅ |
| `pm.project_name` → `plugmut` | ✅ |
| `uv run plugmut --version` exits 0, outputs version | ✅ (`plugmut, version 4.0.0`) |
| `pytest mutmut/tests/ -x -q` passes | ✅ (226 passed, 2 skipped) |
| No `"mutmut"` strings in hookspecs.py | ✅ |
| No `"mutmut"` strings in plugin_manager.py | ✅ |

## Gap vs Step Plan

The step plan described 4 files. Two additional issues not covered by the plan were required:
1. `__main__.py` — click's `version_option()` auto-detects `mutmut` from module context; must pass `package_name="plugmut"` explicitly.
2. `pyproject.toml` — `uv_build` defaults module name to the normalized package name (`plugmut`), which breaks the build since the source dir is `src/mutmut/`. Added `module-name = "mutmut"` to `[tool.uv.build-backend]`.
3. Workspace/plugin `pyproject.toml` files — all referenced the old package name `mutmut` in dependencies, `[tool.uv.sources]`, and entry-point groups. These are mandatory for `uv sync` to succeed.

All changes are mechanical consequences of the package rename, not new product decisions.
