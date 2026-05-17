# Plan Unification Analysis

## Plans Analyzed
1. **plan-branding.md** — API/namespace rename from `mutmut` → `plugmut`
2. **plan-metadata.md** — PyPI metadata, READMEs, CHANGELOGs
3. **plan-infra-raw.md** — GitHub Actions, TO_ADDRESS.md, cleanup

## Where Plans AGREE

| Area | Consensus |
|------|-----------|
| Pluggy namespace | `mutmut` → `plugmut` for HookspecMarker, HookimplMarker, PluginManager |
| Entry-point group | `[project.entry-points.mutmut]` → `[project.entry-points.plugmut]` |
| CLI command | `mutmut` → `plugmut` |
| Package name | Core becomes `name = "plugmut"` |
| Config section | `[tool.mutmut]` → `[tool.plugmut]` |
| Env var | `PLUGMUT_DISABLE_PLUGIN_AUTOLOAD` → `PLUGMUT_DISABLE_PLUGIN_AUTOLOAD` |
| asyncio fix | Add `asyncio_default_fixture_loop_scope = "function"` to mutmut-llm |
| Plugin versions | Keep `0.1.0` for initial release |
| Dist cleanup | Remove stale 3.5.0 artifacts |

## Where Plans CONFLICT

### 1. Plugin package names (escalated to TO_ADDRESS)
- **Branding plan:** Assumes NO rename, escalates to TO_ADDRESS
- **Infra plan:** Puts in TO_ADDRESS as decision
- **Metadata plan:** Silent on this
- **Resolution:** Keep as TO_ADDRESS item. Use current names (`mutmut-*`) until decided.

### 2. CLI alias retention
- **Branding plan:** Focuses on rename to `plugmut`, doesn't mention alias
- **Infra plan:** Asks about keeping `mutmut` as alias in TO_ADDRESS
- **Resolution:** Keep as TO_ADDRESS item. Default to `plugmut` only.

### 3. Old config section handling
- **Branding plan:** Recommends "fail with clear error" (no deprecation)
- **Resolution:** Follow branding plan. 4.0.0 is a breaking release.

### 4. Metadata placeholders
- **Metadata plan:** Uses `{{AUTHOR_NAME}}`, `{{AUTHOR_EMAIL}}`, `{{REPO_URL}}`
- **Infra plan:** Documents these in TO_ADDRESS.md
- **Resolution:** Both approaches combined. Placeholders in code, documented in TO_ADDRESS.md.

## Where Plans COMPLEMENT

| Area | Branding | Metadata | Infra |
|------|----------|----------|-------|
| Exact line changes | ✓ | — | — |
| pyproject.toml metadata | — | ✓ | — |
| README content | — | ✓ | — |
| CHANGELOG format | — | ✓ | — |
| GitHub Actions | — | — | ✓ |
| TO_ADDRESS structure | — | — | ✓ |
| Risk analysis | ✓ | ✓ | ✓ |

## Key Decisions Made

### D1: Implementation order
Branding plan's Phase 1-2 (core namespace + pyproject.toml) is the atomic foundation. Everything else depends on it.

### D2: Env var rename scope
Branding plan identifies 26 files. This is a mechanical change that can be done with sed.

### D3: Hook names vs namespace
- **Namespace:** Changes to `plugmut` (PluginManager, HookspecMarker, HookimplMarker)
- **Hook function names:** Stay `mutmut_*` (e.g., `mutmut_register_operators`)
- **Import paths:** Stay `from mutmut` (Python module name unchanged)

### D4: Breaking change policy
This is v4.0.0 — a breaking release. No backward compatibility code for old config sections or env vars.

## Deliverables Written

### plans/release/PROGRESS.md
- Wave map with 8 waves
- 15 steps with dependencies
- Open decisions list
- Orchestrator protocol
- Subagent contract

### Step files (15 total)
| Step | Name | Wave | Purpose |
|------|------|------|---------|
| 01 | core-namespace-rename | 0 | Atomic foundation |
| 02 | plugin-entrypoints | 1 | Entry-point groups + deps |
| 03 | config-section-rename | 2 | __main__.py config reader |
| 04 | workspace-pyproject | 2 | Root pyproject.toml |
| 05 | env-var-rename | 3 | 26 files mechanical change |
| 06 | plugin-metadata | 4 | pyproject.toml fields |
| 07-10 | readme-* | 5 | README creation (parallel) |
| 11 | changelog-creation | 6 | CHANGELOG files |
| 12 | cleanup-and-fixes | 6 | dist/, asyncio |
| 13 | to-address-creation | 6 | Human decisions doc |
| 14 | github-actions | 7 | CI/CD workflows |
| 15 | conflict-resolution-docs | 8 | Doc updates |

## Risks Carried Forward

| Risk | From | Mitigation |
|------|------|------------|
| Pluggy namespace mismatch | Branding | Wave 0 is atomic |
| User config breaks | Branding | Clear error messages |
| Plugin name collision on PyPI | Infra | Check availability before release |
| Trusted publishing setup fails | Infra | Fallback to API token |
| Env var change breaks CI | Branding | Document in release notes |

## Verification Commands

Full test suite after all changes:
```bash
uv sync
uv run --package plugmut pytest mutmut/tests/ --ignore=mutmut/tests/e2e -x
uv run --package plugmut pytest mutmut/tests/e2e/ -x
uv run --package mutmut-extras pytest -x
uv run --package mutmut-llm pytest --ignore=mutmut-llm/tests/e2e -x
uv run --package mutmut-dedup pytest -x
uv run plugmut --version
```

Placeholder verification:
```bash
grep -r "{{" . --include="*.toml" --include="*.md" | grep -v TO_ADDRESS.md | grep -v unifier-output.md
# Expected: no output (all placeholders in TO_ADDRESS.md only)
```
