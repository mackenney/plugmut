_root := justfile_directory()

# Run core mutmut tests (unit + integration, no e2e)
core *args:
    cd "{{_root}}" && uv run --package plugmut pytest mutmut/tests/ --ignore=mutmut/tests/e2e/ {{args}}

# Run plugmut-extras tests (unit only, no e2e)
extras *args:
    cd "{{_root}}" && uv run --package plugmut-extras pytest plugmut-extras/tests/ --ignore=plugmut-extras/tests/e2e/ {{args}}

# Run plugmut-llm tests (unit only, no e2e)
llm *args:
    cd "{{_root}}" && uv run --package plugmut-llm pytest plugmut-llm/tests/ --ignore=plugmut-llm/tests/e2e/ {{args}}

# Run plugmut-dedup tests
dedup *args:
    cd "{{_root}}" && uv run --package plugmut-dedup pytest plugmut-dedup/tests/ {{args}}

# Run core e2e tests
e2e *args:
    cd "{{_root}}" && uv run --package plugmut pytest mutmut/tests/e2e/ {{args}}

# Run extras e2e tests
e2e-extras *args:
    cd "{{_root}}" && uv run --package plugmut-extras pytest plugmut-extras/tests/e2e/ {{args}}

# Run llm e2e tests (no live API; live tests need PLUGMUT_LLM_E2E_LIVE=1)
e2e-llm *args:
    cd "{{_root}}" && uv run --package plugmut-llm pytest plugmut-llm/tests/e2e/ {{args}}

# Run all e2e tests
e2e-all *args:
    just tests::e2e {{args}}
    just tests::e2e-extras {{args}}
    just tests::e2e-llm {{args}}

# Run all tests across all packages (unit + e2e)
all *args:
    just tests::core {{args}}
    just tests::extras {{args}}
    just tests::llm {{args}}
    just tests::dedup {{args}}
    just tests::e2e-all {{args}}
