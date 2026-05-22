set shell := ["bash", "-euo", "pipefail", "-c"]

mod quality '.just/quality.just'
mod tests   '.just/tests.just'

[private]
default:
    @just --list --list-submodules

# Install all workspace dependencies
[group('workspace')]
sync:
    uv sync --all-groups

# quality::check — lint + format-check
[group('aliases')]
check *packages:
    just quality::check {{packages}}

# quality::fix — ruff check --fix + format in-place
[group('aliases')]
fix *packages:
    just quality::fix {{packages}}

# quality::typecheck — ty check (plugin packages)
[group('aliases')]
typecheck *packages:
    just quality::typecheck {{packages}}

# Run all tests across all packages
[group('aliases')]
test *args:
    just tests::all {{args}}
