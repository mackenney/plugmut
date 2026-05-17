# Infrastructure Plan: Release Pipeline & Human Decision Capture

## Overview

This plan covers the release infrastructure for the mutmut2 UV workspace containing 4 publishable packages (`plugmut`, `mutmut-extras`, `mutmut-llm`, `mutmut-dedup`). Focus areas:
1. GitHub Actions publish workflow
2. Cleanup of stale `dist/` artifacts
3. `TO_ADDRESS.md` for human-required decisions
4. Fix `asyncio_default_fixture_loop_scope` warning in mutmut-llm

**Out of scope** (covered by other planners): API/branding decisions, package naming, pyproject.toml metadata fields, README content.

## Key Design Decisions

### 1. Single multi-package publish workflow vs. per-package workflows
**Decision: Single workflow with matrix build.**
- One `.github/workflows/publish.yml` builds and publishes all 4 packages
- Matrix strategy allows parallel builds per package
- Single secret (`PYPI_API_TOKEN`) with org-level scope simplifies management
- Alternative (per-package workflows) adds overhead without benefit for a coordinated release

### 2. Trigger strategy: tag-based vs. manual dispatch
**Decision: Tag-based with manual fallback.**
- Primary trigger: Push tags matching `v*` pattern
- Secondary: `workflow_dispatch` for re-runs and testing
- Tags should follow `v4.0.0` format (core version, plugins versioned independently but released together)

### 3. Build backend handling
**Decision: Use `uv build` uniformly.**
- Core uses `uv_build` backend, plugins use `hatchling`
- `uv build` handles both backends correctly when run from package directory
- No need for backend-specific logic in workflow

### 4. Test PyPI staging
**Decision: Optional TestPyPI step, disabled by default.**
- Workflow includes `dry_run` input that publishes to TestPyPI instead
- Allows release validation without polluting production PyPI
- Human must explicitly enable via workflow_dispatch or separate tag pattern

## Implementation Steps

### Step 1: Remove stale dist/ artifacts
**Files:** `dist/plugmut-3.5.0-py3-none-any.whl`, `dist/plugmut-3.5.0.tar.gz`

```bash
rm dist/plugmut-3.5.0-py3-none-any.whl dist/plugmut-3.5.0.tar.gz
```

**Why:** Current version is 4.0.0. Stale 3.5.0 artifacts would cause confusion or accidental upload of wrong version.

**Note:** Keep `dist/.gitignore` if it exists; remove directory entirely if empty after cleanup.

### Step 2: Fix asyncio_default_fixture_loop_scope warning

**File:** `mutmut-llm/pyproject.toml`

Add to `[tool.pytest.ini_options]`:
```toml
asyncio_default_fixture_loop_scope = "function"
```

**Why:** pytest-asyncio emits DeprecationWarning when this is unset. Core `mutmut/pyproject.toml` already has this setting. Consistency + clean test output.

### Step 3: Create publish workflow

**File:** `.github/workflows/publish.yml`

```yaml
name: Publish to PyPI

on:
  push:
    tags:
      - 'v*'
  workflow_dispatch:
    inputs:
      dry_run:
        description: 'Publish to TestPyPI instead of PyPI'
        required: false
        default: false
        type: boolean

jobs:
  build:
    name: Build ${{ matrix.package }}
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        package:
          - mutmut
          - mutmut-extras
          - mutmut-llm
          - mutmut-dedup
    steps:
      - uses: actions/checkout@v5
        with:
          submodules: recursive

      - uses: astral-sh/setup-uv@v6
        with:
          python-version: "3.13"

      - name: Build package
        run: |
          cd ${{ matrix.package }}
          uv build

      - name: Upload artifacts
        uses: actions/upload-artifact@v4
        with:
          name: dist-${{ matrix.package }}
          path: ${{ matrix.package }}/dist/*

  publish:
    name: Publish to PyPI
    needs: build
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write  # Required for trusted publishing
    steps:
      - name: Download all artifacts
        uses: actions/download-artifact@v4
        with:
          pattern: dist-*
          merge-multiple: true
          path: dist/

      - name: Publish to TestPyPI
        if: ${{ inputs.dry_run == true }}
        uses: pypa/gh-action-pypi-publish@release/v1
        with:
          repository-url: https://test.pypi.org/legacy/

      - name: Publish to PyPI
        if: ${{ inputs.dry_run != true }}
        uses: pypa/gh-action-pypi-publish@release/v1
```

**Notes:**
- Uses PyPI trusted publishing (OIDC) instead of API tokens — more secure, no secret management
- Requires one-time setup on PyPI: link each package to this repo/workflow
- Falls back to API token if trusted publishing not configured (add `password: ${{ secrets.PYPI_API_TOKEN }}`)

### Step 4: Create test workflow at repo root

**File:** `.github/workflows/tests.yml`

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    name: Test Python ${{ matrix.python-version }}
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.13", "3.12", "3.11", "3.10"]
    steps:
      - uses: actions/checkout@v5
        with:
          submodules: recursive

      - uses: astral-sh/setup-uv@v6
        with:
          python-version: ${{ matrix.python-version }}
          enable-cache: true

      - name: Install dependencies
        run: uv sync --locked --dev

      - name: Test core
        run: uv run --package mutmut pytest mutmut/tests/ -x

      - name: Test extras
        run: uv run --package mutmut-extras pytest

      - name: Test dedup
        run: uv run --package mutmut-dedup pytest

      - name: Test llm (unit only)
        run: uv run --package mutmut-llm pytest mutmut-llm/tests/ --ignore=mutmut-llm/tests/e2e/
```

### Step 5: Create TO_ADDRESS.md

**File:** `TO_ADDRESS.md`

See full content in section below.

### Step 6: Update conflict-resolution docs after rename

**File:** `conflict-resolution/plugin-autoload-fail-loudly.md`

The file mentions "plugmut" in error message but codebase uses "mutmut". After branding decisions are finalized, update this doc to match. Add to TO_ADDRESS.md as post-decision task.

## TO_ADDRESS.md Content

```markdown
# Decisions Required Before Release

This document tracks decisions that require human input before the v4.0.0 release can proceed.

## Critical (Blocking Release)

### 1. PyPI Package Names
**Question:** What PyPI package names should the plugins use?
- Option A: `mutmut-extras`, `mutmut-llm`, `mutmut-dedup` (matches current directory names)
- Option B: `plugmut-extras`, `plugmut-llm`, `plugmut-dedup` (matches rebrand if core becomes `plugmut`)

**Impact:** PyPI names are permanent. Wrong choice requires deprecating and re-releasing.

**Decision:** _____________
**Decided by:** _____________
**Date:** _____________

---

### 2. PyPI Trusted Publishing Setup
**Question:** Configure PyPI trusted publishing for this repository?

**Required actions:**
1. Create PyPI accounts/organization for each package
2. Link each package to `<your-org>/mutmut2` repository
3. Configure environment `pypi` in GitHub repo settings
4. Grant the `publish.yml` workflow access to the environment

**Alternative:** Use API token instead (add `PYPI_API_TOKEN` secret)

**Decision:** Trusted publishing / API token / _____________
**Decided by:** _____________
**Date:** _____________

---

### 3. Plugin Package Authors
**Question:** Who should be listed as author(s) for the plugin packages?
- Core mutmut: Anders Hovmöller
- Plugin packages: _____________

**Impact:** Appears in package metadata, PyPI listing, `pip show` output.

**Decision:** _____________
**Decided by:** _____________
**Date:** _____________

---

### 4. Plugin Package License
**Question:** What license for the plugin packages?
- Core mutmut: BSD-3-Clause
- Options: BSD-3-Clause (match core), MIT, Apache-2.0

**Impact:** Legal terms for users and contributors.

**Decision:** _____________
**Decided by:** _____________
**Date:** _____________

---

### 5. Repository URL / Homepage
**Question:** What URLs should plugin packages use for project.urls?
- Options: 
  - `https://github.com/<org>/mutmut2` (this workspace)
  - `https://github.com/<org>/mutmut2/tree/main/mutmut-extras` (subdir)
  - Separate repos per plugin

**Impact:** Where users find docs, issues, source code.

**Decision:** _____________
**Decided by:** _____________
**Date:** _____________

---

## Important (Pre-Release Recommended)

### 6. CLI Alias Retention
**Question:** Keep `mutmut` as a CLI alias alongside `plugmut`?
- Current: `mutmut` command
- Options:
  - A: Keep both `mutmut` and `plugmut` commands
  - B: Only `plugmut` (breaking change)
  - C: Only `mutmut` (no rebrand in CLI)

**Impact:** User migration path, backwards compatibility.

**Decision:** _____________
**Decided by:** _____________
**Date:** _____________

---

### 7. Version Strategy
**Question:** How to version the plugin packages relative to core?
- Option A: Independent versions (plugins stay 0.x until stable)
- Option B: Synchronized versions (all packages share version number)
- Option C: Compatible ranges (plugins require compatible core version)

**Current state:** Core is 4.0.0, all plugins are 0.1.0

**Impact:** Dependency resolution, upgrade paths, changelog organization.

**Decision:** _____________
**Decided by:** _____________
**Date:** _____________

---

## Post-Decision Tasks

After decisions above are finalized:

- [ ] Update plugin pyproject.toml files with chosen names, authors, license, URLs
- [ ] Update conflict-resolution/plugin-autoload-fail-loudly.md to match branding
- [ ] Configure PyPI trusted publishing or add API token secret
- [ ] Tag and release
```

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Trusted publishing setup fails | Medium | High | Workflow includes TestPyPI dry-run path; fallback to API token |
| Package name conflicts on PyPI | Low | Critical | Check availability before finalizing TO_ADDRESS.md decisions |
| Build backend incompatibility | Low | Medium | `uv build` handles both `uv_build` and `hatchling`; tested locally |
| Submodule checkout missing | Medium | High | Workflow uses `submodules: recursive` |
| Version mismatch between packages | Medium | Low | Document version strategy in TO_ADDRESS.md |

## Tradeoffs vs. Other Approaches

### Trusted Publishing vs. API Tokens
**Chosen: Trusted publishing (OIDC)**
- Pro: No secret management, more secure, no token rotation
- Con: Requires one-time PyPI setup per package
- Alternative (API token): Simpler setup but less secure, requires secret rotation

### Single Publish Workflow vs. Per-Package Workflows
**Chosen: Single workflow with matrix**
- Pro: Coordinated releases, single point of maintenance
- Con: All-or-nothing publish (can't publish single package)
- Alternative (per-package): More flexibility but more maintenance

### Tag-Based Trigger vs. Release-Based
**Chosen: Tag-based (`v*`)**
- Pro: Works with existing Git workflow, simple
- Con: No draft release workflow
- Alternative (release event): Better GitHub integration but more complex

### Monorepo Publish vs. Separate Repos
**Chosen: Monorepo (workspace) publish**
- Pro: Matches project structure, coordinated development
- Con: All packages in one release cycle
- Alternative (separate repos): Independent release cycles but fragmented development
