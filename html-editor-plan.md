# Plan: Trix HTML Editor for Web UI

## Context

When "Send as HTML" is checked in the web UI, users currently type raw HTML into a plain `<textarea>`. There is no formatting assistance — just real-time warnings about potential issues (missing tags, unsupported elements, Gmail clipping). Users who want formatted emails must know HTML and write it by hand.

This plan adds a rich text editor that appears when the HTML toggle is checked, plus an email-compatibility wrapper that ensures the HTML sent via the Graph API renders correctly across major email clients.

## Previous Attempt: Quill 2.x (Abandoned)

A previous implementation used Quill 2.x. It was abandoned for these reasons:

1. **Quill is effectively unmaintained.** Critical bugs like `getSemanticHTML()` converting all spaces to `&nbsp;` (slab/quill#4535) remain unfixed in 2.0.3. The `root.innerHTML` fallback works but is undocumented.
2. **CSS isolation required significant iteration.** Quill's toolbar uses `[role=button]` attributes that Pico CSS styles aggressively. Three approaches failed before finding one that works:
   - **Shadow DOM** broke `document.getSelection()` — cursor tracking failed, each character ended up in its own `<p>` after pressing Enter.
   - **CSS `@layer`** didn't help because Pico sets properties (padding, border, background on `[role=button]`) that Quill never explicitly overrides, so there's no competing rule in the higher layer.
   - **Manual CSS resets** were too fragile — Pico has many selectors (`.pico button`, `.pico [role=button]`, `.pico select`, etc.) and missing even one property caused visual breakage.
   - **Placing the editor outside `.pico`** was the solution. Pico's conditional selectors simply don't match elements that aren't descendants of `.pico`.
3. **Three-way content sync was fragile.** Quill ↔ source textarea ↔ hidden body-input required manual serialization, lazy flush with dirty flags, and workarounds for `&nbsp;` and empty paragraph artifacts.

## Approach: Trix Rich Text Editor

**Library choice — [Trix](https://github.com/basecamp/trix) 2.1.x:**
- Maintained by 37signals (Basecamp/Rails). v2.1.16 released March 2026. Active development with regular security patches.
- **Custom element API** — `<trix-editor input="...">` auto-binds to a hidden input. The hidden input always has the current HTML. No manual sync needed.
- **Clean HTML output** — internal document model produces consistent, terse HTML. No `&nbsp;` bugs, no empty paragraph artifacts, no `getSemanticHTML()` vs `root.innerHTML` decision.
- **Simple programmatic API** — `editor.insertString(text)` for placeholder chips, `editor.loadHTML(html)` for setting content. No Delta format, no clipboard module.
- **Event-driven** — `trix-change` event fires on content changes. Simple to hook validation.
- **Standard DOM** — no Shadow DOM, no `getSelection()` issues.
- **CSS class-scoped** — styles use `.trix-content`, `.trix-button`, etc. Combined with placing the editor outside `.pico`, no isolation hacks needed.
- Bundled as single JS + CSS files. No build step. MIT licensed.

**Format support:** bold, italic, strike, link, heading1, quote, code, bullet list, number list. Does _not_ support underline or multiple heading levels (h2/h3) out of the box. For email composition this is acceptable — underline is discouraged in email (confused with links) and a single heading level is sufficient for most messages.

**What the user sees when "Send as HTML" is checked:**
1. The plain `<textarea>` is hidden and a Trix rich text editor appears in its place.
2. A toolbar provides: Bold, Italic | Link | Heading | Bulleted List, Numbered List | Quote | Decrease/Increase Nesting.
3. A "View Source" toggle switches to a `<textarea>` showing the raw HTML for direct editing.
4. The existing live preview in Step 2 continues to work via the sandboxed iframe.

**What happens on submit:**
HTML is read from the hidden input (always in sync with Trix), wrapped in an email-compatible document structure, and passed to `send_merge()`.

---

## Do Not Revert the Quill Commits

The Quill implementation introduced infrastructure that is editor-independent and should be kept:

| Component | Location | Status |
|---|---|---|
| `_wrap_html_for_email()` + constants | `api.py` | Keep — editor-independent |
| `_STYLE_BLOCK_RE` / `_FULL_HTML_DOC_RE` warnings | `app.py` | Keep — editor-independent |
| JS validation (`validateHtmlBody()`, regexes) | `app.js` | Keep — reads `body-input` |
| HTML toggle show/hide logic | `app.js` | Keep — swap Quill calls for Trix |
| Source toggle concept | `app.js` | Keep — rework for Trix API |
| `#html-editor-wrap` outside `.pico` | `index.html` | Keep — same isolation approach |
| `localStorage` `mm_html` key | `app.js` | Keep |
| Tests for `_wrap_html_for_email` | `test_api.py` | Keep |
| Tests for HTML warnings | `test_web.py` | Keep |
| `quill.min.js`, `quill.snow.css` | `static/` | Remove — replaced by Trix |
| `initQuill()`, `flushQuill()`, `syncTextareaToQuill()`, `activateHtmlEditor()` | `app.js` | Remove — replaced by Trix |
| `quillEditor`, `quillDirty` state | `app.js` | Remove — replaced by Trix |
| Quill chip insertion logic | `app.js` | Remove — replaced by `editor.insertString()` |
| `quill.snow.css` `<link>` | `index.html` | Replace with `trix.css` |
| `quill.min.js` `<script>` | `index.html` | Replace with `trix.js` |

---

## 1. Bundle Trix

**New files:**
- `src/mail_merge/web/static/trix.js` — Trix 2.1.x UMD bundle
- `src/mail_merge/web/static/trix.css` — Trix stylesheet

Download from npm/CDN and commit as static assets. Remove `quill.min.js` and `quill.snow.css`.

**File:** `src/mail_merge/web/templates/index.html`

Update `<head>`:
```html
<link rel="stylesheet" href="{{ url_for('static', filename='trix.css') }}">
```

Update `<script>` (before `app.js`):
```html
<script src="{{ url_for('static', filename='trix.js') }}"></script>
```

## 2. HTML Structure

**File:** `src/mail_merge/web/templates/index.html`

Replace the Quill editor markup inside `#html-editor-wrap` (which already sits outside `.pico`):

```html
<!-- HTML editor (outside .pico — CSS isolation) -->
<div id="html-editor-wrap" class="hidden">
    <div class="html-editor-header">
        <label>
            <input type="checkbox" id="source-toggle"> View source
        </label>
    </div>
    <input type="hidden" id="trix-input">
    <trix-editor input="trix-input" placeholder="Compose your HTML email..."></trix-editor>
    <textarea id="html-source" rows="12" class="hidden" spellcheck="false"></textarea>
    <small>Tip: if you include your own &lt;html&gt; tags, the app's email compatibility wrappers are skipped.</small>
</div>
```

Trix auto-inserts a `<trix-toolbar>` element before the `<trix-editor>`. No manual toolbar HTML needed.

The hidden `<input id="trix-input">` is Trix's output — it always contains the current HTML. This eliminates the three-way sync problem entirely.

## 3. JavaScript Integration

**File:** `src/mail_merge/web/static/app.js`

Remove all Quill-specific code (`quillEditor`, `quillDirty`, `initQuill()`, `flushQuill()`, `syncTextareaToQuill()`, `activateHtmlEditor()`). Replace with:

**State:**
```javascript
let trixEditor = null;
```

**Initialization** — Trix initializes automatically when the custom element is in the DOM:
```javascript
document.addEventListener('trix-initialize', (e) => {
    trixEditor = e.target.editor;
});
```

**Content sync** — Trix writes to `#trix-input` automatically. Copy to `body-input` on change:
```javascript
document.addEventListener('trix-change', () => {
    $('body-input').value = $('trix-input').value;
    onTemplateChange();
});
```

No `flushQuill()`, no dirty flag, no `getSemanticHTML()` vs `root.innerHTML`. The hidden input is always current.

**Prevent file drops** — Trix supports drag-and-drop attachments by default; disable since the app handles attachments separately:
```javascript
document.addEventListener('trix-file-accept', (e) => {
    e.preventDefault();
});
```

**HTML toggle handler** — replace `activateHtmlEditor()`:
```javascript
function activateHtmlEditor() {
    const existingBody = $('body-input').value;
    if (existingBody && trixEditor) {
        trixEditor.loadHTML(existingBody);
    }
    hide('body-input');
    show('html-editor-wrap');
}
```

**Source toggle:**
```javascript
$('source-toggle').addEventListener('change', () => {
    if ($('source-toggle').checked) {
        $('html-source').value = $('trix-input').value;
        hide(trixEditorElement);
        show('html-source');
    } else {
        trixEditor.loadHTML($('html-source').value);
        show(trixEditorElement);
        hide('html-source');
    }
});
```

**Placeholder chip insertion:**
```javascript
if ($('html-toggle').checked && trixEditor && !$('source-toggle').checked) {
    trixEditor.insertString(insertion);
} else {
    // existing textarea insertion logic (unchanged)
}
```

**Reset (`newMerge`):**
```javascript
if (trixEditor) {
    trixEditor.loadHTML('');
}
$('trix-input').value = '';
$('html-source').value = '';
```

**Remove `flushQuill()` calls** from `goToStep()`, `onTemplateChange()` debounce callback, and localStorage save interval. These are no longer needed since `trix-input` is always current.

## 4. Hide Unwanted Toolbar Buttons

**File:** `src/mail_merge/web/static/style.css`

```css
.trix-button--icon-strike,
.trix-button--icon-code,
.trix-button-group--file-tools {
    display: none;
}
```

## 5. Editor Styling

**File:** `src/mail_merge/web/static/style.css`

Replace `#quill-editor` rules with:

```css
/* Trix editor — sits outside .pico in the DOM */
trix-editor {
    min-height: 150px;
    font-family: -apple-system, 'Segoe UI', Roboto, Arial, Helvetica, sans-serif;
    font-size: 14px;
    line-height: 1.5;
    color: #1a1a1a;
}
```

## 6. Email Compatibility Wrapper

Already implemented in `api.py` as `_wrap_html_for_email()`. No changes needed — the wrapper is editor-independent. It wraps HTML fragments in an email-compatible document structure with:
- CSS resets for `<p>`, `<h1>`, `<ul>/<ol>`, `<blockquote>` (prevents oversized gaps in Outlook/Gmail)
- Outlook DPI fix (`PixelsPerInch` conditional comment)
- Mobile viewport meta tag
- Cross-platform font stack

The wrapper uses string concatenation (not `.format()`) because the body may contain `{{placeholders}}` that conflict with Python format strings.

Full-document bypass: if the body contains `<!DOCTYPE` or `<html>`, the wrapper is skipped and the user's HTML is sent as-is. Both client-side and server-side warnings alert the user to this.

## 7. Tests

- `TestWrapHtmlForEmail` tests — keep unchanged.
- `test_preview_html_warns_style_block` / `test_preview_html_warns_full_document` — keep unchanged.
- E2E tests (`test_web_e2e.py`): Update any selectors that reference `.ql-*` classes to use `trix-editor` / `trix-toolbar` selectors.
- Add E2E test: toggle HTML mode, type in Trix editor, verify `body-input` has the content.

## 8. Implementation Order

1. **Bundle Trix** — download JS + CSS, remove Quill files
2. **Update HTML** — replace Quill markup with Trix custom element
3. **Update JS** — replace Quill code with Trix event listeners and API calls
4. **Update CSS** — replace Quill rules with Trix styling + hidden toolbar buttons
5. **Update E2E tests** — fix selectors for Trix elements
6. **Run full test suite** — `uv run pytest` + `uv run mypy`

## 9. Template Placeholder Caveat

If a user applies formatting to part of a `{{name}}` placeholder (e.g. makes `na` bold), Trix may produce `{{<strong>na</strong>me}}` which breaks template matching. The existing placeholder validation (`validatePlaceholders()`) runs on the HTML source and will flag `{{name}}` as unresolved, alerting the user. No special handling needed — the warning is sufficient.

## Lessons Learned (from Quill)

1. **CSS isolation: use Pico conditional scoping, not Shadow DOM or @layer.** Place the editor outside any `.pico` ancestor in the DOM. Pico's selectors don't match elements outside `.pico`. Zero overrides, zero fragility.

2. **Don't fight the editor's content model.** Quill's Delta model required `clipboard.convert()` for HTML→Delta and `getSemanticHTML()`/`root.innerHTML` for Delta→HTML, each with bugs. Trix's hidden input binding eliminates manual sync entirely.

3. **Check for known bugs in the editor's HTML export.** Quill 2.0.3's `getSemanticHTML()` converts all spaces to `&nbsp;`. Always verify the actual output of the extraction API before relying on it.

4. **Don't use Shadow DOM for rich text editors.** `document.getSelection()` doesn't work across shadow boundaries. Cursor tracking breaks catastrophically.

5. **Lazy sync is good, but no sync is better.** The `flushQuill()` dirty-flag pattern reduced per-keystroke work but added complexity (every consumer had to remember to flush). Trix's hidden input is always current — no sync code at all.
