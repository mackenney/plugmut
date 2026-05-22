# plugmut-llm

LLM-powered mutation operator for [plugmut](https://github.com/mackenney/plugmut).

Generates semantically sophisticated code mutations using an LLM. The default backend is Claude (Anthropic); additional backends can be added by implementing the `Generator` protocol. API costs are incurred only during the explicit generation phase, not during test execution.

## Installation

```bash
pip install plugmut-llm
```

Requires an Anthropic API key:

```bash
export ANTHROPIC_API_KEY=your-key-here
```

## Overview

mutmut-llm generates semantically sophisticated code mutations using an LLM backend (Claude by default). It operates in two phases:

1. **Generation phase** — calls the LLM API and caches results locally
2. **Operator phase** — reads pre-generated mutations during plugmut's mutation pass

LLM API costs are incurred only during generation, not during test execution.

## Usage

### Generate mutations

```bash
plugmut generate [paths...]
```

Without paths, scans `./src/` by default. Use `--budget N` to cap the number of API calls (default: 20). Use `--dry-run` to preview scope without making API calls.

### Run mutation testing

```bash
plugmut run
```

The LLM operator yields cached mutations automatically.

### Check status

```bash
plugmut llm-status
```

Shows library stats (functions cached, total mutations, cumulative cost), latest run summary, and active config.

## Configuration

Configure in `pyproject.toml`:

```toml
[tool.plugmut.llm]
model = "claude-sonnet-4-6"            # Model to use
min_mutations_per_function = 2         # Minimum mutations requested per function
max_mutations_per_function = 5         # Maximum mutations requested per function
temperature = 0.6                      # Generation temperature (0.0–1.0)
enabled = true                         # Enable/disable the plugin
cache_ttl = "5m"                       # Prompt-cache TTL: "5m" or "1h"
```

API key must be set via the `ANTHROPIC_API_KEY` environment variable. Setting `api_key` in `pyproject.toml` has no effect.

## Caching

- Cache entries stored in `.plugmut-llm/entries/` relative to the project root
- Entries keyed by source hash — refactored functions automatically get new mutations
- Two functions with identical source bodies share cache entries
- Cache never expires automatically; entries accumulate until manually cleared
- Clear with: `rm -rf .plugmut-llm/`

Run history is stored under `.mutmut-cache/llm/runs/` and is not removed by cache clears.

## Prompt caching

The system prompt and per-file context are structured to enable Anthropic prompt caching. This reduces API costs significantly for projects with many functions in the same file. The `cache_ttl` option controls the TTL: `"5m"` (ephemeral, default) or `"1h"` (one-hour).

## Documentation

See [SPEC.md](https://github.com/mackenney/plugmut/blob/main/mutmut-llm/SPEC.md) for detailed contracts, validation pipeline, cost tracking, and known limitations.

## License

MIT License. See [LICENSE](LICENSE).

Built on [plugmut](https://github.com/mackenney/mutmut) (a fork of [mutmut](https://github.com/boxed/mutmut) by Anders Hovmöller). The core mutation engine is the original author's work; this plugin is by Ignacio Mackenney.
