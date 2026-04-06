# Plan: Filter Field Name Chip Buttons

## Context

The filter textarea in Step 1 requires users to type column names from memory (e.g. `company=Acme`). The codebase already has clickable chip buttons for inserting `{{column}}` placeholders into subject/body fields. This plan adds equivalent chip buttons near the filter textarea so users can click a column name to insert it, reducing errors and making filter creation faster.

## Approach

Reuse the existing `.chip` / `.chip-container` CSS and follow the same pattern as `showPlaceholderChips()`. Chips show bare column names (not `{{wrapped}}`), append `=` on click, and handle newlines automatically.

## Changes

### 1. `src/mail_merge/web/templates/index.html` — add chip container

Insert after the filter `<textarea>` (line 161), inside the same grid cell:

```html
<div id="filter-chips" class="hidden">
    <small>Insert column name (click to add):</small>
    <div class="chip-container" id="filter-chips-container"></div>
</div>
```

### 2. `src/mail_merge/web/static/app.js` — add `showFilterChips()` function

Insert after `showPlaceholderChips()` (after line 591). Same structure but:
- Chip text = bare column name (no `{{}}`)
- Insertion text = `columnname=`
- Always targets `$("filter-input")`
- Uses `mousedown` + `e.preventDefault()` (same as placeholder chips) to prevent focus leaving the textarea, then explicitly calls `target.focus()` and `target.setSelectionRange()` after insertion so the cursor is placed right after the `=` and the user can immediately type the value
- **Newline logic:** prepends `\n` when inserting at the end if `value.trimEnd()` is non-empty and `value` doesn't already end with `\n` — using `trimEnd()` handles trailing whitespace so `"status=active "` correctly gets a newline before the next filter
- Uses event delegation: attach a single `mousedown` listener on `#filter-chips-container` and check `e.target.closest(".chip")` instead of per-chip listeners — avoids any leak concerns when `innerHTML` is cleared on re-upload

### 3. `src/mail_merge/web/static/app.js` — wire up calls

| Location | Change |
|---|---|
| After spreadsheet upload (line 519) | Add `showFilterChips(data.columns);` |
| Session restoration (~line 252, inside `if (data.spreadsheet)`) | Add `showPlaceholderChips(s.columns);` and `showFilterChips(s.columns);` — fixes existing gap where placeholder chips don't restore either |
| `newMerge()` (after line 1165) | Add `hide("filter-chips");` |

### 4. `tests/test_web_e2e.py` — add E2E tests

Add to `TestSetupStep` class, after `test_placeholder_chip_inserts_text` (line 206):

- **`test_filter_chips_appear`** — upload spreadsheet, expand "Additional options", verify chip count >= 3
- **`test_filter_chip_inserts_column_name`** — click a filter chip, verify textarea contains `=` but not `{{`
- **`test_filter_chip_newline_handling`** — pre-fill textarea with `company=Acme`, click chip, verify `\n` separates the two filters

### No CSS changes needed

Existing `.chip` and `.chip-container` styles already include `flex-wrap: wrap` so many columns (50+) will wrap rather than overflow horizontally.

## Files touched

- `src/mail_merge/web/templates/index.html` (4 lines added)
- `src/mail_merge/web/static/app.js` (~30 lines added)
- `tests/test_web_e2e.py` (~35 lines added)

## Verification

1. `uv run pytest` — all existing + new tests pass
2. Manual: `uv run mergemail365-web`, upload a spreadsheet, expand "Additional options", verify chips appear below filter textarea, click one, confirm `columnname=` is inserted and cursor is after `=` ready for typing
