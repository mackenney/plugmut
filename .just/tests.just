_root := justfile_directory()

# Run core mutmut tests
core *args:
    cd "{{_root}}" && uv run --package plugmut pytest mutmut/tests/ {{args}}

# Run plugmut-extras tests
extras *args:
    cd "{{_root}}" && uv run --package plugmut-extras pytest plugmut-extras/tests/ {{args}}

# Run plugmut-llm tests
llm *args:
    cd "{{_root}}" && uv run --package plugmut-llm pytest plugmut-llm/tests/ {{args}}

# Run plugmut-dedup tests
dedup *args:
    cd "{{_root}}" && uv run --package plugmut-dedup pytest plugmut-dedup/tests/ {{args}}

# Run core e2e tests
e2e *args:
    cd "{{_root}}" && uv run --package plugmut pytest mutmut/tests/e2e/ {{args}}

# Run all tests across all packages
all *args:
    just tests::core {{args}}
    just tests::extras {{args}}
    just tests::llm {{args}}
    just tests::dedup {{args}}
