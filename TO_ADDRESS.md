# Pre-Release Checklist

All major decisions have been made and implemented. The following items remain
before publishing to PyPI.

---

## Remaining: CHANGELOG Review

Each plugin CHANGELOG is at `[0.0.1] - 2026-05-17`. Review entries for
accuracy and completeness before tagging.

- `plugmut-extras/CHANGELOG.md`
- `plugmut-llm/CHANGELOG.md`
- `plugmut-dedup/CHANGELOG.md`

---

## Remaining: PyPI Setup and Release

When ready to publish:

1. Register GitHub repos: `mackenney/plugmut` (monorepo) and `mackenney/mutmut` (fork)
2. Create PyPI account under `mackenney`
3. Configure trusted publishing (OIDC) on PyPI for each package:
   - `plugmut` → `mackenney/mutmut`, workflow `publish.yml`
   - `plugmut-extras` → `mackenney/plugmut`, workflow `publish.yml`
   - `plugmut-llm` → `mackenney/plugmut`, workflow `publish.yml`
   - `plugmut-dedup` → `mackenney/plugmut`, workflow `publish.yml`
4. Create `pypi` GitHub environment in each repo
5. Run placeholder verification: `grep -r "{{" mutmut-extras/ mutmut-llm/ mutmut-dedup/ README.md --include="*.toml" --include="*.md"` (expected: no output)
6. Tag and publish

---

## Decision Log

| # | Decision | Outcome |
|---|----------|---------|
| 1 | PyPI package names | `plugmut-extras`, `plugmut-llm`, `plugmut-dedup` |
| 2 | Author for plugin packages | Ignacio Mackenney (`mackenney92@gmail.com`); fork attribution in READMEs |
| 3 | License for plugin packages | MIT; fork keeps BSD-3-Clause |
| 4 | Repository URL | `https://github.com/mackenney/plugmut` (monorepo), `https://github.com/mackenney/mutmut` (fork) |
| 5 | PyPI publishing method | Trusted publishing (OIDC) — repo setup only, no PyPI actions yet |
| 6 | PyPI account | Individual — `mackenney` (register later) |
| 7 | CLI alias | Both `mutmut` and `plugmut` entry points kept |
| 8 | Version strategy | Independent semver; plugins start at `0.0.1` |
| 9 | Release date | No release scheduled yet |
