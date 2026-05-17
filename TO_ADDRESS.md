# Decisions Required Before Release

This document tracks every decision that requires human input before the
plugmut v4.0.0 release can go out to PyPI. Complete **Critical** items before
publishing anything. **Important** items should be resolved before the first
release announcement.

After each decision, fill in the blanks and work through the post-decision
checklist at the bottom of this file.

---

## Critical (Blocking Release)

### 1. PyPI Package Names for Plugin Packages

**Question:** What should the three plugin packages be named on PyPI?

- Option A — keep current directory names: `mutmut-extras`, `mutmut-llm`, `mutmut-dedup`
- Option B — match the `plugmut` rebrand: `plugmut-extras`, `plugmut-llm`, `plugmut-dedup`

**Why this matters:** PyPI package names are permanent. Choosing wrong requires
deprecating the old names, re-publishing under new names, and updating every
user's `pip install` instructions. The core package is already named `plugmut`,
so Option B is the more consistent choice, but Option A preserves the
association with the well-known `mutmut` ecosystem.

**Action required:** Update the `name` field in `mutmut-extras/pyproject.toml`,
`mutmut-llm/pyproject.toml`, and `mutmut-dedup/pyproject.toml` once decided.

Decision: _____________
Decided by: _____________
Date: _____________

---

### 2. Author Name(s) and Email for Plugin Packages

**Question:** Who should be listed as the author of the plugin packages
(`mutmut-extras`, `mutmut-llm`, `mutmut-dedup`)?

The core `plugmut` package lists Anders Hovmöller (boxed@killingar.net) as
author. The plugin packages were developed separately and may have a different
author or additional co-authors.

The `authors` field in each plugin `pyproject.toml` currently uses placeholder
text for AUTHOR_NAME and AUTHOR_EMAIL. Replace those placeholders with real
values before publishing.

**Files to update:** `mutmut-extras/pyproject.toml`, `mutmut-llm/pyproject.toml`,
`mutmut-dedup/pyproject.toml`

Decision — author name: _____________
Decision — author email: _____________
Decided by: _____________
Date: _____________

---

### 3. License for Plugin Packages

**Question:** Which open-source license should govern the plugin packages?

- Recommended: BSD-3-Clause — matches the core `plugmut` license, familiar to
  Python ecosystem users, permissive, compatible with MIT and Apache-2.0.
- Alternative: MIT — slightly more permissive, very widely recognized.
- Alternative: Apache-2.0 — includes patent grant, heavier legal text.

**Action required:** After deciding, create a `LICENSE` file in each plugin
directory (`mutmut-extras/`, `mutmut-llm/`, `mutmut-dedup/`) with the full
license text. Update the `license` field in each plugin `pyproject.toml`
(currently set to a placeholder for LICENSE).

Decision: _____________
Decided by: _____________
Date: _____________

---

### 4. Repository URL / Homepage

**Question:** What URL should the plugin packages use for `project.urls`?

- Option A: `https://github.com/ORG/mutmut2` — monorepo URL, simplest
- Option B: `https://github.com/ORG/mutmut2/tree/main/mutmut-extras` (etc.) —
  links directly to the subdirectory for each plugin
- Option C: Separate repos per plugin (requires creating new repos)

Replace ORG with your GitHub username or organization name.

**Files to update:** `project.urls` sections in all three plugin `pyproject.toml`
files (Homepage, Repository, Issues fields — currently set to REPO_URL placeholder).
Also update the same URL in any README files created for plugins.

Decision: _____________
Decided by: _____________
Date: _____________

---

### 5. PyPI Publishing Setup

**Question:** How will the packages be published to PyPI?

- Option A — Trusted publishing (OIDC): No long-lived secrets. GitHub Actions
  authenticates directly with PyPI via OIDC. Requires:
  1. Create PyPI account / organization
  2. Register each package name on PyPI (first publish can be done manually
     with a token, or via the "Add a new pending publisher" workflow on PyPI)
  3. Create a GitHub environment named `pypi` in repo settings
  4. Configure trusted publisher on PyPI linking each package to this repo and
     the `publish.yml` workflow
  5. Grant the `pypi` environment access to the workflow

- Option B — API token: Add a `PYPI_API_TOKEN` repository secret in GitHub.
  Simpler setup, but the token is long-lived and must be rotated manually.

Decision: Trusted publishing / API token / other: _____________
Decided by: _____________
Date: _____________

---

### 6. PyPI Account / Organization

**Question:** Will the packages be published under an individual PyPI account or
a shared organization account?

Using a PyPI organization allows multiple maintainers with role-based access.
Individual accounts are simpler to set up for solo projects.

**Action required:** Create the account or organization before publishing. For
trusted publishing, the PyPI account/org must exist before configuring OIDC.

Decision: Individual account / organization (name: _____________): _____________
Decided by: _____________
Date: _____________

---

## Important (Pre-Release Recommended)

### 7. CLI Alias Retention

**Question:** Should the `mutmut` command be kept as an alias alongside `plugmut`?

- Option A: Keep both `mutmut` and `plugmut` CLI entry points — zero migration
  friction for existing users, at the cost of maintaining the alias indefinitely.
- Option B: Only `plugmut` — clean break, matches the namespace rename, but
  breaks existing scripts and documentation that reference `mutmut`.
- Option C: Only `mutmut` — no CLI rebrand; the PyPI package name changes but
  the command stays the same.

**Action required if Option A:** Add a `mutmut` entry to `[project.scripts]` in
`mutmut/pyproject.toml` pointing to the same entry point as `plugmut`.

Decision: _____________
Decided by: _____________
Date: _____________

---

### 8. Version Strategy for Coordinated Releases

**Question:** How should plugin package versions be managed relative to the
core `plugmut` package?

- Option A: Independent versioning — each plugin has its own version, updated
  only when that plugin changes. Cleaner semver semantics.
- Option B: Synchronized versioning — all plugins track the same version as
  core (currently 4.0.0). Simpler to communicate compatibility to users.

All plugin `pyproject.toml` files currently declare `version = "0.1.0"`.
If synchronized versioning is chosen, bump them to `4.0.0` before release.

Decision: _____________
Decided by: _____________
Date: _____________

---

### 9. Release Date

**Question:** When will v4.0.0 be published?

The CHANGELOG files for each plugin contain a placeholder for RELEASE_DATE.
Replace that placeholder with the actual ISO date (YYYY-MM-DD) before tagging.

Decision: _____________
Decided by: _____________
Date: _____________

---

### 10. README Placeholder Review

**Question:** Are the README files for each plugin complete and accurate?

The README files (once created by the release preparation steps) contain
placeholder text for REPO_URL, LICENSE, and AUTHOR information. Review each
file after filling in the decisions above and confirm the content accurately
describes the package.

Files to review:
- `mutmut-extras/README.md`
- `mutmut-llm/README.md`
- `mutmut-dedup/README.md`
- `README.md` (workspace root)

Decision: Reviewed and approved / needs changes: _____________
Decided by: _____________
Date: _____________

---

## Post-Decision Checklist

Work through this after all decisions above are finalized:

- [ ] Replace AUTHOR_NAME and AUTHOR_EMAIL placeholder text in all plugin
      `pyproject.toml` files with the real author name and email
- [ ] Replace the LICENSE placeholder in all plugin `pyproject.toml` files
      with the chosen SPDX license identifier (e.g., `BSD-3-Clause`)
- [ ] Create a `LICENSE` file in each plugin directory with the full license text
- [ ] Replace REPO_URL placeholder in all plugin `pyproject.toml` and README
      files with the actual repository URL
- [ ] Replace RELEASE_DATE placeholder in all plugin `CHANGELOG.md` files
      with the actual release date in YYYY-MM-DD format
- [ ] If Option B for package names: update the `name` field in each plugin
      `pyproject.toml` from `mutmut-*` to `plugmut-*`
- [ ] If Option A for CLI alias: add `mutmut` entry to `[project.scripts]`
      in `mutmut/pyproject.toml`
- [ ] If synchronized versioning: bump plugin versions from `0.1.0` to `4.0.0`
      in all plugin `pyproject.toml` files
- [ ] Create PyPI account / organization and configure publishing method
- [ ] If trusted publishing: configure OIDC on PyPI for each package and
      create the `pypi` GitHub environment
- [ ] If API token: add `PYPI_API_TOKEN` to repository secrets
- [ ] Verify no placeholder text remains: run the command below
- [ ] Tag release: `git tag v4.0.0 && git push origin v4.0.0`
- [ ] Trigger publish workflow or run `uv build && twine upload` manually

### Placeholder verification command

Run this before tagging to confirm all placeholder text has been replaced:

```bash
grep -r "AUTHOR_NAME\|AUTHOR_EMAIL\|REPO_URL\|RELEASE_DATE\|LICENSE_PLACEHOLDER" \
  mutmut-extras/ mutmut-llm/ mutmut-dedup/ README.md \
  --include="*.toml" --include="*.md"
# Expected: no output
```

---

## Quick Reference: Files with Placeholder Text

| File | Placeholders |
|------|-------------|
| `mutmut-extras/pyproject.toml` | AUTHOR_NAME, AUTHOR_EMAIL, LICENSE, REPO_URL |
| `mutmut-llm/pyproject.toml` | AUTHOR_NAME, AUTHOR_EMAIL, LICENSE, REPO_URL |
| `mutmut-dedup/pyproject.toml` | AUTHOR_NAME, AUTHOR_EMAIL, LICENSE, REPO_URL |
| `mutmut-extras/CHANGELOG.md` | RELEASE_DATE |
| `mutmut-llm/CHANGELOG.md` | RELEASE_DATE |
| `mutmut-dedup/CHANGELOG.md` | RELEASE_DATE |
| `mutmut-extras/README.md` | REPO_URL, LICENSE (once README is created) |
| `mutmut-llm/README.md` | REPO_URL, LICENSE (once README is created) |
| `mutmut-dedup/README.md` | REPO_URL, LICENSE (once README is created) |
