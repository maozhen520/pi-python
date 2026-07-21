# Research: edit-tool designs across open-source coding agents

**Ticket:** [Research: edit-tool designs across open-source coding agents](https://github.com/maozhen520/pi-python/issues/15)  
**Map:** [Map: Python pi harness (core + TUI + coding CLI)](https://github.com/maozhen520/pi-python/issues/1)  
**Follow-up grill:** [Grill: edit tool contract for v1](https://github.com/maozhen520/pi-python/issues/16)  
**Fetched:** 2026-07-21  
**Upstream pi pin:** `earendil-works/pi@9e7582aa03e5` (main tip at fetch)

## Question

What should pi-python’s v1 **`edit`** tool contract be, informed by open-source coding agents — not only upstream pi?

## Verdict (for the grill)

**Recommend a structured exact-replace tool** in the Claude Code / Anthropic `str_replace` family, with **upstream pi’s multi-hunk-in-one-call** shape:

| Choice | v1 recommendation |
|--------|-------------------|
| Apply model | Exact unique string replace; optional `replace_all`; **multi** `edits[]` matched against the **original** file (non-overlapping) |
| Soft normalize | Line endings + BOM + limited unicode/trailing-ws normalize (pi-style) **before** uniqueness checks — not Aider-style edit-distance auto-apply |
| Errors | Fail closed with actionable text (not found / not unique / overlap); prefer including a short “nearby candidates” hint when cheap (Aider-quality); no traceback to the model |
| Concurrency | Per-file mutation queue shared with `write` (pi `withFileMutationQueue`) |
| Do **not** copy | Freeform SEARCH/REPLACE in assistant prose (Aider chat format); unified-diff as the *primary* tool schema; silent fuzzy apply of wrong hunks; requiring a hard “must have Read this turn” gate unless we later add read-tracking |

Rationale: tool-calling agents already speak structured `old`/`new` replaces; uniqueness-fail is a feature; multi-edit against original avoids incremental offset bugs; aggressive fuzzy matching trades safety for fewer retries and is a poor default for a coding CLI that can destroy files.

---

## 1. Comparison matrix

| System | Interface | Match rule | Multi-change | Failure UX | Notes |
|--------|-----------|------------|--------------|------------|-------|
| **Upstream pi `edit`** | Tool: `path` + `edits[{oldText,newText}]` | Exact, then limited fuzzy normalize; each `oldText` must be **unique**; all matched on **original**; no overlaps | Yes, one call | Clear not-found / duplicate / empty / no-op errors | File mutation queue; diff/patch in `details` |
| **Claude Code `Edit`** | Tool: `old_string` / `new_string` (+ `replace_all`) | Exact only (docs); must be unique unless `replace_all` | One replace per call (or all occurrences) | Uniqueness / missing match | Docs: prefer prior `Read`; edit against current disk content |
| **Anthropic text editor `str_replace`** | API tool command | Exact `old_str` → `new_str` | Single replace per command | Exact-match failures | Platform-defined schema |
| **Aider “diff” / editblock** | Model emits SEARCH/REPLACE **in assistant text**, harness parses | Exact → whitespace-tolerant → `...` segments → **difflib fuzzy** | Many blocks per response | Excellent: show failed block + similar lines + “don’t resend succeeded blocks” | Format varies by model (`whole`, `udiff`, …) |

Sources pinned below.

---

## 2. Upstream pi (earendil-works/pi)

Primary sources:

- [`packages/coding-agent/src/core/tools/edit.ts`](https://github.com/earendil-works/pi/blob/9e7582aa03e5/packages/coding-agent/src/core/tools/edit.ts)
- [`packages/coding-agent/src/core/tools/edit-diff.ts`](https://github.com/earendil-works/pi/blob/9e7582aa03e5/packages/coding-agent/src/core/tools/edit-diff.ts)
- [`packages/coding-agent/src/core/tools/file-mutation-queue.ts`](https://github.com/earendil-works/pi/blob/9e7582aa03e5/packages/coding-agent/src/core/tools/file-mutation-queue.ts)

### Contract

- Schema: `path`, `edits: [{ oldText, newText }, ...]` (legacy single `oldText`/`newText` coerced into `edits`).
- Prompt guidelines: keep `oldText` small but unique; merge nearby changes; **do not** match incrementally; no overlapping/nested edits.
- Apply pipeline (`applyEditsToNormalizedContent`): normalize EOL to LF; for each edit `fuzzyFindText` (exact `indexOf`, else normalize unicode quotes/dashes/spaces + strip trailing ws); count occurrences on normalized space — duplicates throw; apply in reverse offset order; optionally overlay fuzzy line changes onto original bytes to preserve untouched lines; restore original EOL; produce display diff + unified patch for UI `details`.

### Concurrency

- `withFileMutationQueue(path, fn)` serializes mutations to the same realpath; different files stay parallel — important when agent `toolExecution` is parallel and `write`/`edit` share a path.

### What is strong for pi-python

- Multi-hunk tool call fits our already-chosen tool-calling loop (assemble-then-execute).
- Uniqueness + non-overlap are clear safety rails.
- Mutation queue matches parallel tool batches already decided for `pi_agent`.

### What to treat carefully

- Fuzzy normalize can still surprise (quote/dash folding). Acceptable as **fallback after exact**, with errors still speaking “must match”; avoid advertising “fuzzy edit” to the model.
- Error strings are clear but rarely show “did you mean these lines?” — Aider is stronger here.

---

## 3. Claude Code / Anthropic str_replace

Primary sources:

- [Claude Code Tools reference — Edit tool behavior](https://code.claude.com/docs/en/tools-reference) (fetched 2026-07-21)
- [Anthropic platform — Text editor tool (`str_replace`)](https://platform.claude.com/docs/en/agents-and-tools/tool-use/text-editor-tool)

### Contract (docs)

- Exact string replacement; **not** regex / fuzzy (Claude Code docs).
- `old_string` must appear exactly once, unless `replace_all: true`.
- Practical guidance: include surrounding context so the match is unique.
- Claude Code documents read/freshness rules (prefer having read the file; behavior around disk changes evolved by version — treat as product policy, not something we must clone byte-for-byte).

### What is strong for pi-python

- Simplest mental model for tool-calling models.
- `replace_all` covers rename-in-file without inventing a second tool.
- Fail-closed uniqueness matches “don’t silently edit the wrong occurrence.”

### Gaps vs pi

- Single hunk per call → more round-trips for multi-site edits; pi’s `edits[]` is better for one turn / one file.

---

## 4. Aider

Primary sources:

- [Aider edit formats](https://aider.chat/docs/more/edit-formats.html)
- [`aider/coders/editblock_prompts.py`](https://github.com/Aider-AI/aider/blob/main/aider/coders/editblock_prompts.py) (SEARCH/REPLACE rules)
- [`aider/coders/editblock_coder.py`](https://github.com/Aider-AI/aider/blob/main/aider/coders/editblock_coder.py) (`perfect_or_whitespace`, `try_dotdotdots`, `replace_closest_edit_distance`, rich `SearchReplaceNoExactMatch` errors)

### Contract

- Not primarily a JSON tool schema: the model writes fenced `<<<<<<< SEARCH` / `=======` / `>>>>>>> REPLACE` blocks (or whole-file / udiff variants).
- Apply stack escalates: exact → leading-whitespace tolerance → `...` elision segments → difflib-ish closest match.
- On failure: reprint the failing block, show similar file lines, tell the model which blocks already applied.

### What to take

- **Error quality** and retry instructions are best-in-class for edit loops.
- Whitespace-tolerance as a *narrow* fallback is proven.

### What not to copy for v1

- Assistant-prose edit formats (we already committed to structured tools + LiteLLM tool calls).
- Aggressive edit-distance apply as default (can commit the wrong hunk).
- Multiple competing edit dialects (`whole` / `udiff` / `diff-fenced`) — high prompt/surface cost.

---

## 5. Other signals (lighter)

- Anthropic’s older/computer-use style editors and many OSS agents converge on **str_replace-shaped** tools once they use native tool calling (same failure modes: uniqueness, whitespace drift).
- “Apply unified patch” tools exist in some stacks; models often emit invalid patches or wrong line context. Higher parser burden; better as a **later** optional tool than v1 default.
- Secondary write-ups (e.g. community comparisons of SEARCH/REPLACE vs str_replace) agree on the trade-off: structured exact replace + good errors beats silent fuzzy for safety — use them only as orientation, not as primary cites.

---

## 6. Recommendations for [Grill: edit tool contract for v1](https://github.com/maozhen520/pi-python/issues/16)

### 6.1 Apply model

1. **Primary:** structured tool `edit` with:
   - `path: str`
   - `edits: list[{old_text: str, new_text: str}]` (non-empty)
   - optional `replace_all: bool` **per edit** or top-level — grill should pick one; default `false`
2. Match each `old_text` against the **original** file contents (LF-normalized view).
3. Require uniqueness unless `replace_all`.
4. Reject overlapping match ranges.
5. Apply all-or-nothing for the call (if any hunk fails, write nothing).
6. Soft normalize (EOL, BOM, trailing ws / smart quotes) only as match assist; prefer reporting errors in “exact match” language.

### 6.2 Failure modes (model-facing)

Minimum set (align pi + Claude):

- empty `old_text`
- not found
- not unique (include occurrence count; ask for more context or `replace_all`)
- overlap between edits
- no-op (identical content)
- I/O / permission

Stretch (Aider-inspired, worth v1 if cheap): when not found, include ≤N similar line snippets from the file.

### 6.3 Concurrency

- Share a per-realpath mutation queue with `write` (and any future file mutators).
- Keep `execution_mode` compatible with agent parallel batches (sequential-for-same-file via queue, not necessarily forcing global sequential tools).

### 6.4 Deliberate non-copies from upstream pi

- Do not require TypeBox / TS renderers — Python schema (Pydantic/JSON Schema) + Textual rendering elsewhere.
- Do not promise macOS path unicode gymnastics inside `edit` (can live in shared path utils later).
- Treat fuzzy normalize as implementation detail, not a marketed capability.
- Optional: skip legacy single `oldText` top-level fields; only `edits[]` in v1 API.

### 6.5 Relationship to already-locked tools

From [Grill: built-in tool semantics](https://github.com/maozhen520/pi-python/issues/13):

- `write` = full file create/overwrite
- `edit` = surgical replace only (this note)
- Host permissions; no gitignore sandbox
- Actionable errors, no tracebacks to the model

---

## 7. Citations (primary)

1. earendil-works/pi `edit.ts` / `edit-diff.ts` / `file-mutation-queue.ts` @ `9e7582aa03e5`
2. [Claude Code tools reference](https://code.claude.com/docs/en/tools-reference) — Edit tool behavior
3. [Anthropic text editor tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/text-editor-tool) — `str_replace`
4. [Aider edit formats](https://aider.chat/docs/more/edit-formats.html)
5. Aider-AI/aider `editblock_prompts.py`, `editblock_coder.py` (main branch tips fetched 2026-07-21)

## 8. Decision for map #1

Research complete: recommend **pi-shaped multi exact-replace tool + Claude-style uniqueness/`replace_all` + Aider-quality errors**, without Aider prose formats or aggressive fuzzy apply. Final parameter naming and `replace_all` placement belong in the grill ticket.
