# Conflict Resolution: CLI alias and URL update in mutmut/pyproject.toml

## What changed

Two modifications were made to `mutmut/pyproject.toml`:

1. **CLI alias**: Added `mutmut = "mutmut.__main__:cli"` to `[project.scripts]` alongside the existing `plugmut` entry. This preserves backward compatibility for users who still call `mutmut` on the command line.

2. **URL update**: Changed all project URLs from `https://github.com/boxed/mutmut` to `https://github.com/mackenney/mutmut` to reflect the fork's location. The `Documentation` URL pointing to readthedocs was removed since it targets the upstream project, not this fork.

## Why it could not be done via plugin

Project metadata (`[project.scripts]`, `[project.urls]`) is not pluggable — there is no hook mechanism for adding CLI entry points or changing package URLs at install time. The change must live in `pyproject.toml`.

## Upstream risk

- `[project.scripts]`: Upstream may add or rename entry points. If upstream removes `plugmut` and renames it, the alias will still work but our `plugmut` entry would be a duplicate. Resolve by keeping only `mutmut` if upstream drops the `plugmut` alias.
- `[project.urls]`: Upstream will change these URLs frequently (e.g. changelog location, docs URL). On sync, prefer upstream's URL values and update the fork URL separately (`mackenney/mutmut`).

## How to resolve conflicts

If upstream modifies `[project.scripts]`:
1. Keep the `mutmut` alias we added — add it back after applying upstream's change.
2. Do not duplicate any entry point upstream already provides.

If upstream modifies `[project.urls]`:
1. Apply upstream's changes as-is.
2. Then replace `boxed/mutmut` with `mackenney/mutmut` throughout the section.
3. Remove any URL that points to upstream infrastructure we do not operate (e.g. readthedocs).
