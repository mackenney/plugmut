_root         := justfile_directory()
_all_packages := 'plugmut plugmut-extras plugmut-llm plugmut-dedup'

_pkg_dir pkg:
    #!/usr/bin/env bash
    set -euo pipefail
    case "{{pkg}}" in
        plugmut)        echo "{{_root}}/mutmut" ;;
        plugmut-extras) echo "{{_root}}/plugmut-extras" ;;
        plugmut-llm)    echo "{{_root}}/plugmut-llm" ;;
        plugmut-dedup)  echo "{{_root}}/plugmut-dedup" ;;
        *) echo "Unknown package: {{pkg}}" >&2; exit 1 ;;
    esac

# Lint with ruff (all packages or specific ones)
lint *packages:
    #!/usr/bin/env bash
    set -euo pipefail
    root="{{_root}}"
    pkg_dir() {
        case "$1" in
            plugmut)        echo "$root/mutmut" ;;
            plugmut-extras) echo "$root/plugmut-extras" ;;
            plugmut-llm)    echo "$root/plugmut-llm" ;;
            plugmut-dedup)  echo "$root/plugmut-dedup" ;;
            *) echo "Unknown package: $1" >&2; exit 1 ;;
        esac
    }
    targets=({{packages}})
    [[ ${#targets[@]} -eq 0 ]] && targets=({{_all_packages}})
    for pkg in "${targets[@]}"; do
        dir=$(pkg_dir "$pkg")
        echo "→ lint $pkg"
        cd "$dir" && uv run ruff check .
        cd "$root"
    done

# Check formatting without modifying (all packages or specific ones)
format-check *packages:
    #!/usr/bin/env bash
    set -euo pipefail
    root="{{_root}}"
    pkg_dir() {
        case "$1" in
            plugmut)        echo "$root/mutmut" ;;
            plugmut-extras) echo "$root/plugmut-extras" ;;
            plugmut-llm)    echo "$root/plugmut-llm" ;;
            plugmut-dedup)  echo "$root/plugmut-dedup" ;;
            *) echo "Unknown package: $1" >&2; exit 1 ;;
        esac
    }
    targets=({{packages}})
    [[ ${#targets[@]} -eq 0 ]] && targets=({{_all_packages}})
    for pkg in "${targets[@]}"; do
        dir=$(pkg_dir "$pkg")
        echo "→ format-check $pkg"
        cd "$dir" && uv run ruff format --check .
        cd "$root"
    done

# ruff check --fix + ruff format in-place (all packages or specific ones)
fix *packages:
    #!/usr/bin/env bash
    set -euo pipefail
    root="{{_root}}"
    pkg_dir() {
        case "$1" in
            plugmut)        echo "$root/mutmut" ;;
            plugmut-extras) echo "$root/plugmut-extras" ;;
            plugmut-llm)    echo "$root/plugmut-llm" ;;
            plugmut-dedup)  echo "$root/plugmut-dedup" ;;
            *) echo "Unknown package: $1" >&2; exit 1 ;;
        esac
    }
    targets=({{packages}})
    [[ ${#targets[@]} -eq 0 ]] && targets=({{_all_packages}})
    for pkg in "${targets[@]}"; do
        dir=$(pkg_dir "$pkg")
        echo "→ fix $pkg"
        cd "$dir" && uv run ruff check --fix . && uv run ruff format .
        cd "$root"
    done

# Type-check with ty (all packages or specific ones)
typecheck *packages:
    #!/usr/bin/env bash
    set -euo pipefail
    root="{{_root}}"
    pkg_dir() {
        case "$1" in
            plugmut)        echo "$root/mutmut" ;;
            plugmut-extras) echo "$root/plugmut-extras" ;;
            plugmut-llm)    echo "$root/plugmut-llm" ;;
            plugmut-dedup)  echo "$root/plugmut-dedup" ;;
            *) echo "Unknown package: $1" >&2; exit 1 ;;
        esac
    }
    targets=({{packages}})
    [[ ${#targets[@]} -eq 0 ]] && targets=(plugmut-extras plugmut-llm plugmut-dedup)
    for pkg in "${targets[@]}"; do
        dir=$(pkg_dir "$pkg")
        echo "→ typecheck $pkg"
        cd "$dir" && uv run ty check .
        cd "$root"
    done

# lint + format-check + typecheck (all packages or specific ones)
check *packages:
    just quality::lint {{packages}}
    just quality::format-check {{packages}}
    just quality::typecheck {{packages}}
