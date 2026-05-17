# API/Branding Namespace Rename Plan: mutmut → plugmut

## Overview

This plan covers the runtime namespace rename from `"mutmut"` to `"plugmut"` across the codebase. Per SPEC.md:

> The package is published as `plugmut`. The internal Python module remains `mutmut`. The CLI command is `plugmut`. The pluggy hook namespace is `"plugmut"`. The entry-point group is `plugmut`.

**Scope:** Every place the string `"mutmut"` is used as:
1. Pluggy namespace (`PluginManager("...")`, `HookspecMarker("...")`, `HookimplMarker("...")`)
2. Entry-point group (`[project.entry-points.mutmut]`, `load_setuptools_entrypoints("...")`)
3. CLI command name (`[project.scripts]` key)
4. pyproject.toml package name (`name = "..."`)
5. Configuration section names (`[tool.mutmut]`, `[mutmut]` in setup.cfg)
6. Error messages referencing the namespace
7. Environment variable names (`MUTMUT_*`)

**Out of scope (other planners):**
- pyproject.toml metadata (authors, license, classifiers, README) — Packaging Metadata planner
- GitHub Actions, dist cleanup, TO_ADDRESS.md structure — Infrastructure planner

---

## Key Design Decisions

### D1. Configuration section backward compatibility

**Decision required:** Should `[tool.mutmut]` in pyproject.toml and `[mutmut]` in setup.cfg continue working with a deprecation warning, or fail immediately?

**Recommendation:** Fail with clear error pointing to the new section name. Rationale:
- This is a breaking release (4.0.0)
- `mutmut-llm` already has this pattern: raises `ValueError` when `[tool.mutmut.llm]` exists without `[tool.plugmut.llm]`
- Clean break avoids long-term maintenance of backward compatibility code

### D2. Environment variable naming

**Decision required:** Should `PLUGMUT_DISABLE_PLUGIN_AUTOLOAD` and `PLUGMUT_LLM_E2E_LIVE` be renamed to `PLUGMUT_*`?

**Recommendation:** Yes, rename to `PLUGMUT_DISABLE_PLUGIN_AUTOLOAD`. Rationale:
- Consistency with the published package name
- The environment variable is documented in SPEC.md under the `plugmut` heading
- All test fixtures already set this env var — can be changed atomically

### D3. Plugin package naming (TO_ADDRESS item)

**Decision required for user:** Should `mutmut-extras` → `plugmut-extras`, `mutmut-llm` → `plugmut-llm`, `mutmut-dedup` → `plugmut-dedup`?

**Recommendation:** Escalate to TO_ADDRESS.md. SPEC.md is silent on plugin package names. Both options are defensible:
- `plugmut-*`: Consistent branding, discoverable on PyPI
- `mutmut-*`: Preserves continuity, works with both upstream mutmut and plugmut (if made generic)

This plan assumes plugin package names **do not change** and only the entry-point group changes. If the user decides to rename packages, that's additional pyproject.toml changes.

### D4. Error message and comment updates

**Policy:** All error messages and code comments that reference "mutmut" as the product name or namespace should change to "plugmut" when referring to:
- Plugin loading errors
- CLI command invocations
- Hook namespace references

The Python module name `mutmut` in import paths (`from mutmut.hookspecs import hookimpl`) remains unchanged.

---

## Implementation Steps

### Phase 1: Core pluggy namespace (3 files, 5 changes)

**Step 1.1:** `mutmut/src/mutmut/hookspecs.py`

| Line | Current | New |
|------|---------|-----|
| 12 | `hookspec = pluggy.HookspecMarker("mutmut")` | `hookspec = pluggy.HookspecMarker("plugmut")` |
| 13 | `hookimpl = pluggy.HookimplMarker("mutmut")` | `hookimpl = pluggy.HookimplMarker("plugmut")` |

**Step 1.2:** `mutmut/src/mutmut/plugin_manager.py`

| Line | Current | New |
|------|---------|-----|
| 14 | `_pm = pluggy.PluginManager("mutmut")` | `_pm = pluggy.PluginManager("plugmut")` |
| 18 | `_pm.load_setuptools_entrypoints("mutmut")` | `_pm.load_setuptools_entrypoints("plugmut")` |
| 20 | `raise RuntimeError(f"Failed to load mutmut plugins: {e}")` | `raise RuntimeError(f"Failed to load plugmut plugins: {e}")` |

**Step 1.3:** `mutmut/src/mutmut/__init__.py`

| Line | Current | New |
|------|---------|-----|
| 10 | `__version__ = importlib.metadata.version("mutmut")` | `__version__ = importlib.metadata.version("plugmut")` |

### Phase 2: Core pyproject.toml (2 changes)

**Step 2.1:** `mutmut/pyproject.toml`

| Line | Current | New |
|------|---------|-----|
| 2 | `name = "mutmut"` | `name = "plugmut"` |
| 46 | `mutmut = "mutmut.__main__:cli"` | `plugmut = "mutmut.__main__:cli"` |

### Phase 3: Configuration section names (2 files)

**Step 3.1:** `mutmut/src/mutmut/__main__.py` — pyproject.toml config section

Lines 948-951:
```python
# Before
config = data["tool"]["mutmut"]

# After (with deprecation error)
if "mutmut" in data.get("tool", {}) and "plugmut" not in data.get("tool", {}):
    raise ValueError(
        "Config section [tool.mutmut] is deprecated. "
        "Rename to [tool.plugmut] in your pyproject.toml."
    )
config = data["tool"]["plugmut"]
```

**Step 3.2:** `mutmut/src/mutmut/__main__.py` — setup.cfg config section

Lines 967-969:
```python
# Before
result: Any = config_parser.get("mutmut", key)

# After
result: Any = config_parser.get("plugmut", key)
```

Also need to add a check if `[mutmut]` section exists in setup.cfg — raise deprecation error.

### Phase 4: Plugin entry-point groups (3 files, 3 changes)

**Step 4.1:** `mutmut-extras/pyproject.toml`

| Line | Current | New |
|------|---------|-----|
| 12 | `[project.entry-points.mutmut]` | `[project.entry-points.plugmut]` |
| 8 | `"mutmut>=3.5.0",` | `"plugmut>=4.0.0",` |

**Step 4.2:** `mutmut-llm/pyproject.toml`

| Line | Current | New |
|------|---------|-----|
| 15 | `[project.entry-points.mutmut]` | `[project.entry-points.plugmut]` |
| 8 | `"mutmut>=3.5.0",` | `"plugmut>=4.0.0",` |

**Step 4.3:** `mutmut-dedup/pyproject.toml`

| Line | Current | New |
|------|---------|-----|
| 13 | `[project.entry-points.mutmut]` | `[project.entry-points.plugmut]` |
| 8 | `"mutmut>=3.5.0",` | `"plugmut>=4.0.0",` |

### Phase 5: Workspace root pyproject.toml

**Step 5.1:** `pyproject.toml` (workspace root)

| Line | Current | New |
|------|---------|-----|
| 14 | `mutmut = { workspace = true }` | `plugmut = { workspace = true }` |

Also update any workspace member references if needed.

### Phase 6: Environment variable rename

**Step 6.1:** `mutmut/src/mutmut/plugin_manager.py`

| Line | Current | New |
|------|---------|-----|
| 16 | `if not os.environ.get("PLUGMUT_DISABLE_PLUGIN_AUTOLOAD"):` | `if not os.environ.get("PLUGMUT_DISABLE_PLUGIN_AUTOLOAD"):` |

**Step 6.2:** Test fixtures — update all occurrences (26 files):

Files to update (all use `monkeypatch.setenv("PLUGMUT_DISABLE_PLUGIN_AUTOLOAD", "1")`):
- `mutmut/tests/conftest.py` (lines 12, 16)
- `mutmut-extras/tests/*.py` (17 test files)
- `mutmut-dedup/tests/*.py` (3 test files)
- `mutmut-extras/tests/e2e/test_e2e_extras.py` (lines 140, 146)

Pattern: `PLUGMUT_DISABLE_PLUGIN_AUTOLOAD` → `PLUGMUT_DISABLE_PLUGIN_AUTOLOAD`

**Step 6.3:** `mutmut-llm` environment variables

| File | Current | New |
|------|---------|-----|
| `mutmut-llm/tests/e2e/test_e2e_live.py` | `PLUGMUT_LLM_E2E_LIVE` | `PLUGMUT_LLM_E2E_LIVE` |

### Phase 7: Conflict-resolution documentation updates

Update these files to reflect the new namespace:

| File | Sections to update |
|------|-------------------|
| `conflict-resolution/plugin-autoload-isolation.md` | Lines 31-32 (entry point group reference), env var references |
| `conflict-resolution/plugin-autoload-fail-loudly.md` | Lines 18, 20 (error message examples) |
| `conflict-resolution/command-registration-fault-tolerance.md` | Line 21 (hook call example) |
| `conflict-resolution/register-operators-caching.md` | Lines 11, 12 (hook name references) |
| `conflict-resolution/additional-hookspecs.md` | Line 36 (`mutmut_` prefix reference) |
| `conflict-resolution/hook-filter-composition.md` | Lines 11-23 (hook call examples) |

All references to `PluginManager("mutmut")`, `load_setuptools_entrypoints("mutmut")`, and similar should be updated.

### Phase 8: Test validation

**Step 8.1:** Verify all tests pass with new namespace

```bash
# Core tests
uv run --package plugmut pytest mutmut/tests/ --ignore=mutmut/tests/e2e -x

# E2E tests (core)
uv run --package plugmut pytest mutmut/tests/e2e/ -x

# Plugin tests
uv run --package mutmut-extras pytest -x
uv run --package mutmut-llm pytest -x
uv run --package mutmut-dedup pytest -x
```

**Step 8.2:** Verify CLI command works

```bash
uv run plugmut --version
uv run plugmut --help
```

**Step 8.3:** Verify plugin loading works

```bash
# Ensure plugins are discovered via new entry-point group
uv run python -c "from mutmut.plugin_manager import get_plugin_manager; pm = get_plugin_manager(); print([p for p in pm.get_plugins()])"
```

---

## Risks and Mitigations

### R1. Pluggy namespace mismatch breaks plugin loading

**Risk:** If `HookimplMarker("plugmut")` is used by plugins but `PluginManager("mutmut")` is used by core (or vice versa), plugins silently won't be called.

**Mitigation:** All three must change atomically:
- `PluginManager("plugmut")` in `plugin_manager.py`
- `HookspecMarker("plugmut")` in `hookspecs.py`
- `HookimplMarker("plugmut")` in `hookspecs.py`
- Entry-point group `[project.entry-points.plugmut]` in all plugin pyproject.toml files

**Verification:** Write a test that registers a plugin and verifies its hook is called.

### R2. Existing user configurations break

**Risk:** Users with `[tool.mutmut]` in their pyproject.toml will get errors.

**Mitigation:** Clear error message pointing to the correct section name. This is acceptable for a major version bump.

### R3. Stale env var in CI/CD pipelines

**Risk:** Users setting `PLUGMUT_DISABLE_PLUGIN_AUTOLOAD=1` in CI will find plugins loading unexpectedly.

**Mitigation:** Document the env var rename in release notes. The behavior change (plugins loading) is generally desirable, and users can update their CI config.

### R4. Workspace member references in pyproject.toml

**Risk:** The workspace root `pyproject.toml` uses `mutmut = { workspace = true }`. If the package is renamed to `plugmut`, this must be `plugmut = { workspace = true }`.

**Mitigation:** Ensure all workspace source references are updated.

---

## Tradeoffs vs. Other Approaches

### Alternative A: Keep "mutmut" namespace, only change published name

**Pros:** No plugin breakage, simpler change
**Cons:** Confusing — users install `plugmut` but configure `[tool.mutmut]` and use `HookimplMarker("mutmut")`
**Verdict:** Rejected per SPEC.md which mandates namespace parity

### Alternative B: Gradual deprecation with both namespaces supported

**Pros:** Smoother migration for existing users
**Cons:** Complex code checking both namespaces, longer maintenance burden, SPEC.md says hook namespace is `"plugmut"` (not "both")
**Verdict:** Rejected — clean break preferred for 4.0.0

### Alternative C: Rename Python module from `mutmut` to `plugmut`

**Pros:** Full consistency
**Cons:** Massive diff, every import changes, breaks external tools expecting `import mutmut`, SPEC.md explicitly says "internal Python module remains `mutmut`"
**Verdict:** Rejected per SPEC.md

---

## Files Changed Summary

| Package | Files | Change Type |
|---------|-------|-------------|
| mutmut (core) | `src/mutmut/hookspecs.py` | Namespace strings |
| mutmut (core) | `src/mutmut/plugin_manager.py` | Namespace strings, env var, error message |
| mutmut (core) | `src/mutmut/__init__.py` | Package name for version lookup |
| mutmut (core) | `src/mutmut/__main__.py` | Config section names |
| mutmut (core) | `pyproject.toml` | Package name, CLI script name |
| mutmut (core) | `tests/conftest.py` | Env var name |
| mutmut-extras | `pyproject.toml` | Entry-point group, dependency |
| mutmut-extras | `tests/*.py` (17 files) | Env var name |
| mutmut-llm | `pyproject.toml` | Entry-point group, dependency |
| mutmut-llm | `tests/e2e/test_e2e_live.py` | Env var name |
| mutmut-dedup | `pyproject.toml` | Entry-point group, dependency |
| mutmut-dedup | `tests/*.py` (3 files) | Env var name |
| workspace | `pyproject.toml` | Workspace source name |
| conflict-resolution | 6+ documentation files | Namespace references |

**Total:** ~35 files, ~70 individual changes

---

## Implementation Order

1. **Phase 1-2** (core namespace + pyproject.toml) — must be atomic
2. **Phase 4** (plugin entry-points) — must match Phase 1
3. **Phase 3** (config sections) — can follow
4. **Phase 5** (workspace root) — must follow Phase 2
5. **Phase 6** (env vars) — can be done in parallel
6. **Phase 7** (docs) — after all code changes
7. **Phase 8** (validation) — final

Phases 1, 2, 4, and 5 are tightly coupled and should be in the same commit to avoid broken intermediate states.
