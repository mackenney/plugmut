# Adversarial Critique: Context Quality Spec Delta

> Reviewer role. Every challenge below is backed by code evidence from
> `.claude/worktrees/agent-a28bdd9d/mutmut-llm/src/mutmut_llm/scope.py`
> and cross-referenced with `plans/wave2-review-findings.md`.

---

## Import Filtering Correctness Guarantee

**Challenge 1 — Internal contradiction in the MUST clauses.**

The spec simultaneously says:

> "An import MUST be included if any of its locally-bound names appears as a
> word-boundary token in the function source text."

and later:

> "The presence check is text-level … This causes **false positives**."

These two claims contradict each other. If the contract is defined at the
text-level-matching layer (tokens anywhere in raw source), then matching "os"
inside `x = "os"` is **correct behavior per the contract**, not a false
positive. A false positive only exists relative to an intention the spec
never formally states: "include only imports whose names are referenced as
actual identifiers."

The spec must choose one of two framings and be consistent:

- **Framing A (weaker, implementable now):** "Context MUST include all
  imports whose bound names appear as word-boundary tokens anywhere in the
  function source text (including string literals and comments)." Then
  matching inside strings is not a bug, just a conservative side-effect.
  The H1 fix becomes an optimization, not a correctness obligation.

- **Framing B (stronger, not yet implementable):** "Context MUST include
  exactly those imports whose bound names are referenced as actual identifiers
  in the function AST." This makes H1 a MUST-violation that blocks spec
  ratification. The current wording gestures at this intent but defines the
  contract at text-level.

The draft conflates both framings. Pick one. The current code only satisfies
Framing A.

---

**Challenge 2 — `break` bug: compound statements silently skip 2nd+ items.**

`_build_module_context` (line 107–119) iterates `stmt.body` and calls
`break` unconditionally after the first `Import/ImportFrom/Assign/AnnAssign`
it encounters:

```python
for item in stmt.body:
    if isinstance(item, (cst.Import, cst.ImportFrom)):
        ...
        break          # exits after first import regardless of match
    elif isinstance(item, (cst.Assign, cst.AnnAssign)):
        ...
        break          # exits after first assign regardless of match
```

For a semicolon-compound statement like `import os; import sys`, only
`import os` is evaluated; `import sys` is silently skipped. The spec's MUST
clause — "an import MUST NOT be excluded if any bound name matches" — is
violated for imports appearing after the first item of a compound statement
line.

This is a NEW BUG not in the wave2 review findings. The spec must either:

a) Document it as a known limitation ("this implementation does not handle
   compound-statement lines; each `SimpleStatementLine` is evaluated via
   its first statement only"), or
b) Elevate it to a MUST that the fix must address.

While semicolon-compound imports are rare in Python, the spec cannot
silently omit a correctness violation it knows about.

---

**Challenge 3 — The MUST NOT on exclusion is not guaranteed by the code.**

"An import statement MUST NOT be included if none of its locally-bound names
appears in the function source text."

This is correct in intent, but under Framing A (text-level contract), a
name appearing in a comment still satisfies "appears in function source
text." So `# uses os module` inside the function body → `import os` included.
The MUST NOT only holds when NO occurrence of the name appears anywhere in
raw text (including comments). The spec doesn't call this out, creating
ambiguity: does MUST NOT apply to AST-level references or raw-text
occurrences?

---

## Wildcard Import Handling

**Challenge 4 — MUST NOT is defensible but the rationale is incomplete.**

The spec states `from x import *` MUST NOT be included, accepting the false
negative. The wave2 review (M4) recommends conservative inclusion instead.
The spec justifies exclusion with "to avoid always including potentially large
wildcard scopes."

This justification is weak: the LLM prompt already contains the function
source, class header, and module-level constants. Adding one star-import line
(`from utils import *`) adds a single line of text, not the entire `utils`
module. The "potentially large" risk is of the wildcard's **symbols**, not
the import statement itself — and symbols aren't included regardless.

If the contract says MUST NOT, the spec must explain why conservative
inclusion (the simpler, safer choice for the LLM) was rejected. As written,
the rationale is unpersuasive and will be reopened by every reviewer.

Additionally: the draft cites Open Question 2 ("should implementation warn?
or include unconditionally?") while the body simultaneously states MUST NOT.
If it's already decided (MUST NOT), it's not an open question. If it's
genuinely open, the MUST NOT in the body is premature. The spec has both.

---

## Target Function Deduplication

**Challenge 5 — MUST NOT is right but enforcement is absent.**

The spec correctly uses MUST NOT:

> "The class context MUST NOT include the target function's signature as a
> sibling method stub."

This is a good, falsifiable MUST NOT. The spec also correctly flags it as
a BUG (H4) with required fix. No issue with severity.

However: the note says "pass target function name to `_build_class_context`
and skip it." But `_build_class_context` currently receives `(module,
class_def, module_context)` — no target name. The fix requires a signature
change. The spec delta should note this required API change explicitly,
because if a spec says MUST NOT and the fix requires changing a private
function signature, future implementors need to know.

Minor: the spec says "target function's **signature** as a sibling method
stub" but the actual duplication is even worse — the target function's
**name** appears in the stub list, and its **full body** appears in
`ScopeTarget.source`. The spec should say "The class context MUST NOT
include any reference to the target function."

---

## Constants 'Used By' Definition

**Challenge 6 — Same H1 contamination, not acknowledged.**

The import filtering section explicitly notes H1 (text-level matching). The
constants section does not. The same `re.findall` on raw source at line 104
governs constant inclusion too: `if assign_names & func_names`. If the
function contains `msg = "MAX_SIZE"`, then `MAX_SIZE = 1000` is included as
a "used" constant. The draft does not mention this for constants, even though
the root cause is identical to H1.

**Challenge 7 — Augmented assignments silently dropped.**

`_extract_assign_targets` (line 162) handles `cst.Assign | cst.AnnAssign`
only. `cst.AugAssign` (`COUNTER += 1` at module level) falls through
silently. The spec says "module-level simple assignment" must be included;
augmented assignments are also simple assignments semantically but are
silently excluded. This is undocumented.

**Challenge 8 — `if TYPE_CHECKING:` constants excluded without mention.**

Module-level constants inside `if TYPE_CHECKING:` blocks are `IfStmt` nodes,
not `SimpleStatementLine`. They're silently excluded. For type-annotation-
heavy code, relevant `TYPE_CHECKING` constants (e.g., `from __future__ import
annotations` effects, `TYPE_ALIAS = ...`) are never included. The spec
mentions Open Question 4 for `if __name__ == '__main__'` but not for
`if TYPE_CHECKING:`, which is far more common in production code.

**Challenge 9 — Chained assignment spec clause vs code behavior mismatch.**

The spec says (Open Question 5): "does the contract require both `a` and `b`
to be extractable from `a = b = CONSTANT`?" But `_extract_assign_targets`
at line 168–171 iterates `node.targets` for `cst.Assign`. For `a = b =
CONSTANT`, libcst's `Assign.targets` is `[AssignTarget(a), AssignTarget(b)]`.
Both `a` and `b` ARE extracted. This is already implemented and consistent
— but the spec leaves it as an open question, creating false uncertainty. The
spec should state what the code actually does.

---

## Context Size Bounding

**Challenge 10 — No bound is a behavioral gap, not just a missing detail.**

For a class with 200 methods, the context string includes 200 signature stubs.
For 50 methods each with 3-line decorator chains, that's 150+ lines of
context. At some point the LLM's context window is exceeded and the API call
fails or silently truncates.

The spec says nothing about this. The options for a correct spec are:

a) MUST NOT: "Context MUST NOT exceed N characters/tokens" — requires a
   truncation mechanism (undefined).
b) MAY: "Context MAY grow unbounded; callers are responsible for token
   budget management" — passes the problem upstream.
c) SHOULD: "Context SHOULD be bounded to the N nearest method signatures
   by line proximity" — names the open question as a SHOULD obligation.

None of these are in the spec. Open Question 3 names the gap but provides no
normative statement. A spec with an unbounded MUST (all method signatures
MUST be included) and no size bound is a ticking API failure. This must be
resolved before merge.

---

## Performance Contract

**Challenge 11 — M3 is misclassified as purely non-normative.**

The spec documents M3 as "performance, not correctness" with no normative
statement. This is technically true but misleading. The O(N×M) behavior is
observable: for a 10-class, 100-method file with 200 imports, extraction
does 1000 module traversals. This can take seconds on real codebases.

The spec should add at minimum: "Module-level context extraction SHOULD be
computed once per module file, not once per function extracted from that
file." This is a SHOULD (not MUST) because correctness isn't violated, but
it establishes a performance expectation that reviewers can hold
implementations to. Without it, any O(N^3) implementation satisfies the
spec.

---

## Determinism

**Challenge 12 — Determinism is unspecified, which is dangerous.**

The spec never states that the same input produces the same context. This is
a critical omission for a component whose output feeds into a cache key
system (the LLM cache keys on source content). If `_build_module_context`
ever produced non-deterministic output — e.g., due to a set iteration order
leaking into the output, or whitespace normalization differences — cache hits
would diverge silently.

The spec must add: "Context assembly MUST be deterministic: given the same
source file and function name, `ScopeTarget.context` MUST be identical
across all calls."

The current implementation IS deterministic (AST traversal order is
document order, set operations only affect inclusion/exclusion, not
ordering). But the spec should guarantee it.

---

## Verdict

The spec delta has the right structure and covers the main behavioral areas.
The biggest problems are:

| # | Issue | Severity | Blocks merge? |
|---|-------|----------|---------------|
| 1 | Internal contradiction: MUST defined at text-level but labeled as causing "false positives" — two incompatible framings | HIGH | No, but must be resolved in spec before ratification |
| 2 | `break` bug in compound-statement lines — MUST clause violated, not documented | HIGH | YES — undocumented correctness gap |
| 3 | Wildcard import MUST NOT contradicts own Open Question 2 | MEDIUM | No, but one must be removed |
| 4 | Constants section omits H1 contamination caveat | MEDIUM | No |
| 5 | Augmented assignments silently excluded, undocumented | MEDIUM | No |
| 6 | `if TYPE_CHECKING:` exclusion undocumented | LOW–MEDIUM | No |
| 7 | Context size unbounded with no normative statement | HIGH | YES — unbounded MUST (all signatures) without size cap is unsafe |
| 8 | Determinism unspecified | MEDIUM | No, but needed before spec is final |
| 9 | Open Question 5 (chained assignment) is already answered by code | LOW | No |
| 10 | No performance contract despite O(N×M) known issue | LOW | No |

**Two clauses cannot be ratified as written**: the import MUST (until the
text-level vs AST-level framing is resolved) and the class context MUST (all
signatures, no size bound). Everything else is a documentation gap.
