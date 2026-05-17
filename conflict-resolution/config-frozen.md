# Config dataclass frozen

## What changed

`mutmut/src/mutmut/__main__.py` line 911: Added `frozen=True` to the `@dataclass` decorator for `Config`.

## Why this couldn't be done via plugin

`Config` is the core configuration object created in `ensure_config_loaded()` and passed to `mutmut_configure` hooks. Plugins receive it but cannot change how it's defined.

## Files modified

### `mutmut/src/mutmut/__main__.py`

```python
# Before
@dataclass
class Config:

# After
@dataclass(frozen=True)
class Config:
```

## How to resolve conflicts

If upstream modifies the Config class:
1. Ensure `frozen=True` is present in the `@dataclass` decorator
2. If upstream adds mutable fields, check whether they can be made immutable
3. Methods like `should_ignore_for_mutation()` are unaffected by frozen

If upstream code tries to mutate Config fields post-creation:
1. That code must be changed to create a new Config instead
2. Or the mutation must happen during Config construction

## Verification

```bash
grep -q 'frozen=True' mutmut/src/mutmut/__main__.py
uv run --package mutmut pytest mutmut/tests/ -x -q
```
