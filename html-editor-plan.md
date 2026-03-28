# Plan: HTML Editor for Web UI

## Context

When "Send as HTML" is checked in the web UI, users currently type raw HTML into a plain `<textarea>`. There is no formatting assistance — just real-time warnings about potential issues (missing tags, unsupported elements, Gmail clipping). Users who want formatted emails must know HTML and write it by hand.

This plan adds a rich text editor (Quill) that appears when the HTML toggle is checked, plus an email-compatibility wrapper that ensures the HTML sent via the Graph API renders correctly across major email clients.

## Approach: Quill Rich Text Editor + Source Toggle

**Library choice — Quill 2.x:**
- ~90KB min JS + ~5KB CSS (bundled as static assets, same pattern as the existing `pico.min.css`)
- Built-in customisable toolbar — no need to wire up individual formatting buttons
- Produces clean semantic HTML for basic formats: `<strong>`, `<em>`, `<u>`, `<a>`, `<h1>`–`<h3>`, `<ol>/<ul>/<li>`, `<blockquote>`, `<p>`
- No custom CSS classes for these basic formats (Quill only adds `ql-` classes for advanced features like alignment/indent, which we won't enable)
- Works from a single JS + CSS file — no build step
- MIT licensed, actively maintained
- Handles paste gracefully (strips non-whitelisted formatting)

**What the user sees when "Send as HTML" is checked:**
1. The plain `<textarea>` is hidden and a Quill rich text editor appears in its place.
2. A toolbar provides: Bold, Italic, Underline | Link | Heading (dropdown: H1, H2, H3) | Bulleted List, Numbered List | Blockquote | Clean Formatting.
3. A "View Source" toggle switches to a `<textarea>` showing the raw HTML for direct editing.
4. The existing live preview in Step 2 continues to work via the sandboxed iframe.

**What happens on submit:**
HTML is extracted from Quill (or the source textarea), wrapped in an email-compatible document structure, and passed to `send_merge()`.

---

## 1. Bundle Quill

**New files:**
- `src/mail_merge/web/static/quill.min.js` — Quill 2.x minified
- `src/mail_merge/web/static/quill.snow.css` — Quill Snow theme

Download from the Quill CDN / npm package and commit as static assets (same approach as `pico.min.css`). No CDN at runtime — fully self-contained.

**File:** `src/mail_merge/web/templates/index.html`

Add to `<head>`:
```html
<link rel="stylesheet" href="{{ url_for('static', filename='quill.snow.css') }}">
<script src="{{ url_for('static', filename='quill.min.js') }}" defer></script>
```

## 2. Editor HTML Structure

**File:** `src/mail_merge/web/templates/index.html`

Replace the body input area (currently lines 113–118) with a container that holds both the Quill editor and the source textarea, plus a source toggle:

```html
<label for="body-input">Body</label>

<!-- Plain-text mode (default) -->
<textarea id="body-input" rows="8" placeholder="Hello {{name}},&#10;&#10;Welcome from {{company}}."></textarea>

<!-- HTML editor mode (hidden by default) -->
<div id="html-editor-wrap" class="hidden">
    <div class="html-editor-header">
        <label>
            <input type="checkbox" id="source-toggle"> View source
        </label>
    </div>
    <div id="quill-editor"></div>
    <textarea id="html-source" rows="12" class="hidden" spellcheck="false"></textarea>
</div>

<label>
    <input type="checkbox" id="html-toggle"> Send as HTML
</label>
```

When "Send as HTML" is checked: hide `#body-input`, show `#html-editor-wrap`.
When unchecked: reverse. If the editor has content with HTML tags, confirm before discarding.

## 3. Quill Initialisation and Toolbar Config

**File:** `src/mail_merge/web/static/app.js`

```js
let quillEditor = null;

function initQuill() {
    if (quillEditor) return;
    quillEditor = new Quill('#quill-editor', {
        theme: 'snow',
        placeholder: 'Compose your HTML email...',
        modules: {
            toolbar: [
                ['bold', 'italic', 'underline'],
                ['link'],
                [{ header: [1, 2, 3, false] }],
                [{ list: 'ordered' }, { list: 'bullet' }],
                ['blockquote'],
                ['clean'],   // remove formatting
            ],
        },
        formats: [
            // Whitelist — only email-safe formats allowed
            'bold', 'italic', 'underline',
            'link',
            'header',
            'list',
            'blockquote',
        ],
    });

    // Sync changes to hidden textarea + trigger validation
    quillEditor.on('text-change', () => {
        syncQuillToTextarea();
        onTemplateChange();
    });
}
```

**Format whitelist rationale:** By restricting `formats` to this list, Quill will strip disallowed formatting on paste (images, colours, fonts, alignment, indent). This means content pasted from Word/web produces clean email-safe HTML automatically.

## 4. Content Syncing

**File:** `src/mail_merge/web/static/app.js`

Three-way sync between Quill, source textarea, and the hidden body-input (used for form submission and state persistence).

**Critical:** Never set `quillEditor.root.innerHTML` directly — this bypasses Quill's internal Delta model and causes state corruption. Always use the clipboard module to convert HTML into Deltas.

```js
function syncQuillToTextarea() {
    const html = quillEditor.root.innerHTML;
    // Quill represents an empty editor inconsistently across browsers:
    // <p><br></p>, <p></p>, or just \n. Normalise all to empty string.
    const cleaned = html.replace(/<p><br><\/p>/g, '')
                        .replace(/<p><\/p>/g, '')
                        .trim() || '';
    $('html-source').value = cleaned;
    $('body-input').value = cleaned;
}

function syncTextareaToQuill() {
    // Must go through Quill's clipboard module to build proper Deltas
    const html = $('html-source').value;
    const delta = quillEditor.clipboard.convert({ html });
    quillEditor.setContents(delta, 'silent');
    $('body-input').value = html;
}
```

`clipboard.convert()` parses HTML into Quill's Delta format, and `setContents()` replaces the editor content with that Delta. The `'silent'` source avoids triggering the `text-change` handler during sync (which would cause infinite loops).

The **source toggle** (`#source-toggle`) switches visibility:
- Checked (source view): call `syncQuillToTextarea()` to capture the latest rich text, then hide `#quill-editor`, show `#html-source`.
- Unchecked (rich text view): call `syncTextareaToQuill()` to parse source edits into Deltas, then hide `#html-source`, show `#quill-editor`.

The hidden `#body-input` textarea remains the canonical value for form submission (`buildJobFormData` reads `$("body-input").value`), state persistence (localStorage), and validation — no changes needed to those systems.

## 5. HTML Toggle Behaviour

**File:** `src/mail_merge/web/static/app.js`

Update the `html-toggle` change handler:

```js
$('html-toggle').addEventListener('change', () => {
    const isHtml = $('html-toggle').checked;
    if (isHtml) {
        initQuill();
        // Transfer existing body content to Quill via clipboard module
        const existingBody = $('body-input').value;
        if (existingBody) {
            const delta = quillEditor.clipboard.convert({ html: existingBody });
            quillEditor.setContents(delta, 'silent');
        }
        hide('body-input');
        show('html-editor-wrap');
    } else {
        // Warn if content has HTML tags
        const html = $('body-input').value;
        if (/<[a-zA-Z][^>]*>/.test(html)) {
            if (!confirm('Body contains HTML formatting. Switch to plain text? Tags will be preserved as text.')) {
                $('html-toggle').checked = true;
                return;
            }
        }
        show('body-input');
        hide('html-editor-wrap');
    }
    onTemplateChange();
});
```

## 6. Placeholder Chip Insertion

**File:** `src/mail_merge/web/static/app.js`

Update `showPlaceholderChips()` — when the Quill editor is active and focused, insert the placeholder at the Quill cursor position instead of the textarea:

```js
chip.addEventListener("mousedown", (e) => {
    e.preventDefault();
    const insertion = "{{" + col + "}}";

    if ($("html-toggle").checked && quillEditor && !$("source-toggle").checked) {
        // Insert into Quill editor.
        // getSelection(true) forces focus — if the editor was never focused,
        // cursor goes to index 0 (start of document). After inserting, scroll
        // the editor to the insertion point so the user sees visual feedback.
        const range = quillEditor.getSelection(true);
        if (range) {
            quillEditor.deleteText(range.index, range.length);
            quillEditor.insertText(range.index, insertion);
            const newPos = range.index + insertion.length;
            quillEditor.setSelection(newPos, 0);
            // Scroll insertion point into view
            const bounds = quillEditor.getBounds(newPos);
            if (bounds) {
                quillEditor.scrollingContainer.scrollTop = bounds.top;
            }
        }
    } else {
        // Existing textarea insertion logic (unchanged)
        let target = document.activeElement;
        if (target !== $("subject-input") && target !== $("body-input")
            && target !== $("html-source")) {
            target = $("html-toggle").checked ? $("html-source") : $("body-input");
        }
        // ... existing selectionStart/selectionEnd code ...
    }
    onTemplateChange();
});
```

## 7. Email Compatibility Wrapper

**File:** `src/mail_merge/api.py` — new function `_wrap_html_for_email(body: str) -> str`

Runs in `send_merge()` after template rendering but before passing to the sender, **only when `html=True`**.

**Logic:**
1. If the body already contains `<!DOCTYPE` or `<html` (case-insensitive), return it unchanged — the user provided a complete document and is responsible for their own compatibility.
2. Otherwise, wrap the body fragment in a minimal email-compatible document:

```html
<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml"
      xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
    <meta charset="utf-8">
    <!--[if mso]>
    <noscript><xml><o:OfficeDocumentSettings>
    <o:PixelsPerInch>96</o:PixelsPerInch>
    </o:OfficeDocumentSettings></xml></noscript>
    <![endif]-->
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        /* Reset Quill's semantic tags — without these, Outlook and Gmail
           apply their own user-agent margins, causing oversized gaps. */
        body, p, h1, h2, h3, ul, ol, li, blockquote {
            margin: 0;
            padding: 0;
        }
        p {
            margin: 0 0 0.75em 0;
        }
        h1 {
            font-size: 1.6em;
            margin: 0 0 0.5em 0;
        }
        h2 {
            font-size: 1.3em;
            margin: 0 0 0.5em 0;
        }
        h3 {
            font-size: 1.1em;
            margin: 0 0 0.5em 0;
        }
        ul, ol {
            margin: 0 0 0.75em 0;
            padding-left: 1.5em;
        }
        li {
            margin: 0 0 0.25em 0;
        }
        blockquote {
            margin: 0 0 0.75em 0;
            padding: 0.5em 0 0.5em 1em;
            border-left: 3px solid #ccc;
            color: #555;
        }
        a {
            color: #1a73e8;
        }
    </style>
</head>
<body style="margin: 0; padding: 16px; font-family: -apple-system, 'Segoe UI',
             Roboto, Arial, Helvetica, sans-serif; font-size: 14px;
             line-height: 1.5; color: #1a1a1a;">
{body}
</body>
</html>
```

**Why these specific elements:**
- **CSS resets:** Quill outputs `<p>`, `<h1>`–`<h3>`, `<ul>/<ol>`, `<blockquote>` — without explicit margins, Outlook (Word renderer) and Gmail apply their own user-agent stylesheets, resulting in oversized gaps and unreadable line heights. The `<style>` block normalises these. Supported by Outlook desktop, Apple Mail, Yahoo Mail, and most webmail. Gmail strips `<style>` from `<head>`, but Gmail's default margins for these tags are already reasonable, so the fallback is acceptable.
- `xmlns:o` + `PixelsPerInch` conditional comment: fixes Outlook DPI scaling issues that cause images and table widths to render at wrong sizes.
- `<meta charset="utf-8">`: ensures non-ASCII characters (recipient names from `{{name}}`) render correctly in all clients.
- `<meta name="viewport">`: makes the email readable on mobile clients.
- Body inline styles: `-apple-system, 'Segoe UI', Roboto, Arial, Helvetica, sans-serif` covers macOS/iOS, Windows/Outlook, Android, and generic fallbacks. `font-size: 14px; line-height: 1.5` is the most readable baseline. `margin: 0; padding: 16px` prevents the double-margin bug in some Outlook versions.

**Placement:** In `send_merge()` after the body template is read and before it's passed to `send_all()`/`send_one()`. The wrapping happens *per-message* (after template rendering) so each recipient gets a complete document. Benefits **all callers** — CLI `--html`, Python API `html=True`, and web UI.

## 8. Full-Document Bypass Warning

When the user provides a complete HTML document (containing `<html` or `<!DOCTYPE`), the compatibility wrapper is skipped. Add a UI hint and a validation warning for this case:

**Client-side (`app.js`):** In `validateHtmlBody()`, add:
```
if (/<html\b|<!doctype/i.test(body)) {
    warnings.push(
        "<strong>Full HTML document detected.</strong> Your own &lt;html&gt; structure will "
        + "be sent as-is, bypassing the app\u2019s standard email compatibility wrappers "
        + "(CSS resets, Outlook DPI fix, mobile viewport)."
    );
}
```

**Server-side (`app.py`):** Mirror in `_validate_html_body()`.

**Source view label:** In the `#html-editor-wrap` area, add a `<small>` hint below the source textarea:
```html
<small class="muted">Tip: if you include your own &lt;html&gt; tags, the app's email compatibility wrappers are skipped.</small>
```

## 9. Add `<style>` Block Warning

**Files:** `src/mail_merge/web/app.py`, `src/mail_merge/web/static/app.js`

Add a warning for `<style>` blocks to both the server-side `_validate_html_body()` and client-side `validateHtmlBody()`:

> **Embedded `<style>` blocks may be stripped.** Many email clients (Gmail, Outlook.com) remove `<style>` tags. Use inline `style` attributes for reliable rendering.

Regex: `/<style\b/i`

These functions already mirror each other for external stylesheets, unsupported tags, etc.

## 10. State Persistence

**File:** `src/mail_merge/web/static/app.js`

Add `mm_html` to the localStorage auto-save/restore cycle:
- **Save:** `localStorage.setItem("mm_html", $("html-toggle").checked ? "1" : "")`
- **Restore:** if `mm_html === "1"`, set the checkbox and trigger the toggle handler to show Quill.
- **Clear:** add `localStorage.removeItem("mm_html")` to `clearAll()`.

The body content itself is already saved as `mm_body` via `$("body-input").value`, which is kept in sync with Quill.

## 11. CSS Additions

**File:** `src/mail_merge/web/static/style.css`

```css
/* HTML editor wrapper */
.html-editor-header {
    display: flex;
    justify-content: flex-end;
    margin-bottom: 0.25rem;
    font-size: 0.85rem;
}

#quill-editor {
    min-height: 200px;
    margin-bottom: 1rem;
}

/* Source textarea in HTML mode */
#html-source {
    font-family: var(--pico-font-family-monospace);
    font-size: 0.85rem;
}

/* Override Quill toolbar to blend with Pico theme */
.ql-toolbar.ql-snow {
    border-color: var(--pico-form-element-border-color);
    border-radius: var(--pico-border-radius) var(--pico-border-radius) 0 0;
    background: var(--pico-card-background-color);
}

.ql-container.ql-snow {
    border-color: var(--pico-form-element-border-color);
    border-radius: 0 0 var(--pico-border-radius) var(--pico-border-radius);
    font-family: inherit;
    font-size: inherit;
}
```

## 12. Preview Integration (Step 2)

**File:** `src/mail_merge/web/static/app.js`

The existing `renderPreviewRecipient()` function reads from `$("body-input").value` and renders into a sandboxed iframe when HTML mode is on. Since `#body-input` is kept in sync with Quill, **no changes needed** to the Step 2 preview.

## 13. Files Modified

| File | Change |
|------|--------|
| `src/mail_merge/web/static/quill.min.js` | **New** — bundled Quill 2.x |
| `src/mail_merge/web/static/quill.snow.css` | **New** — bundled Quill Snow theme |
| `src/mail_merge/web/templates/index.html` | Add Quill CSS/JS refs, editor wrapper, source toggle |
| `src/mail_merge/web/static/app.js` | Quill init, sync, toggle, chip insertion update, state persistence |
| `src/mail_merge/web/static/style.css` | Editor/toolbar Pico theme overrides |
| `src/mail_merge/web/app.py` | Add `<style>` block warning to `_validate_html_body()` |
| `src/mail_merge/api.py` | Add `_wrap_html_for_email()`, call in `send_merge()` |
| `tests/test_api.py` | Tests for `_wrap_html_for_email()` |
| `tests/test_web.py` | Test `<style>` block warning |
| `tests/test_web_e2e.py` | E2E tests for Quill editor, source toggle, HTML toggle |

## 14. Implementation Order

1. **Email compatibility wrapper** (`api.py`) + unit tests — independent, benefits all callers
2. **Validation warnings** (`app.py` + `app.js`) — `<style>` block warning + full-document bypass warning
3. **Bundle Quill files** — download and commit static assets
4. **Editor HTML structure** (`index.html`) — add Quill container, source toggle, bypass hint, script/style refs
5. **Editor JS logic** (`app.js`) — Quill init, sync, toggle behaviour, chip insertion update
6. **CSS theming** (`style.css`) — Pico integration for Quill toolbar/container
7. **State persistence** (`app.js`) — save/restore HTML toggle
8. **E2E tests** (`test_web_e2e.py`)

## 15. Verification

1. `uv run pytest` — all existing tests pass
2. `uv run mypy` — no type errors
3. Manual testing via `uv run mergemail365-web`:
   - Toggle "Send as HTML" → Quill editor appears with formatting toolbar
   - Type and format text → bold, italic, links, headings, lists all work
   - Click placeholder chips → `{{name}}` inserted at cursor in Quill
   - Toggle "View source" → raw HTML textarea shows clean markup; edits sync back to Quill
   - Toggle HTML off → confirmation if content has tags; reverts to plain textarea
   - Step 2 preview → rendered HTML shown in sandboxed iframe
   - Send test email → received email has proper document wrapper, renders correctly in Gmail, Outlook, Apple Mail
   - Paste from Word/web → only whitelisted formatting preserved
4. CLI test: `uv run mergemail365 --html --body test.html ...` → wrapper applied
5. E2E: `uv run pytest tests/test_web_e2e.py` — new tests pass

## 16. Template Placeholder Caveat

If a user applies formatting to part of a `{{name}}` placeholder (e.g. makes `name` bold), Quill may produce `{{<strong>name}}</strong>` which breaks template matching. The existing placeholder validation (`validatePlaceholders()`) runs on the HTML source and will flag `{{name}}` as unresolved, alerting the user. No special handling needed beyond this — the warning is sufficient.

## 17. Assessment and Improvements

The plan is well-structured, maintainable, and correctly targets the integration points without disrupting the existing plain-text and template processing logic. The choice of Quill 2.x and the implementation of an email compatibility wrapper are excellent for ensuring clean and reliable HTML emails.

However, several critical improvements are required to address CSS conflicts and ensure robust state synchronization:

### Improvement 1: Pico CSS Conditional Styling Conflict with Quill Toolbar
**Issue:** The app uses Pico CSS conditional styling (`<body class="pico">`). Pico aggressively styles standard semantic tags like `<button>`, `<select>`, and `<svg>` within the `.pico` container. Since Quill's toolbar (`.ql-toolbar`) is built using these tags, Pico will style them as large, primary-colored application buttons, completely breaking the toolbar's layout and appearance.
**Fix:** In Section 11 (CSS Additions), add explicit CSS resets to isolate the Quill toolbar from Pico's styles:

```css
/* Reset Pico CSS overrides inside Quill Toolbar */
.pico .ql-toolbar button {
    background: none;
    border: none;
    padding: 3px 5px;
    margin: 0;
    width: 28px;
    height: 24px;
}
.pico .ql-toolbar button:hover {
    background: none;
    outline: none;
}
.pico .ql-toolbar button svg {
    width: 100%;
    height: 100%;
}
.pico .ql-toolbar .ql-picker {
    color: inherit;
}
```

### Improvement 2: Quill Editor Typography Inheritance
**Issue:** The content inside `.ql-editor` will inherit Pico's typography (fonts, margins, line-heights). This may misrepresent how the email will render on the recipient's end, since the email compatibility wrapper (Section 7) applies its own specific styles.
**Fix:** In Section 11, add a CSS rule to align the editor's base typography with the email wrapper's styles:

```css
/* Align editor appearance with email wrapper */
.ql-container .ql-editor {
    font-family: -apple-system, 'Segoe UI', Roboto, Arial, Helvetica, sans-serif;
    font-size: 14px;
    line-height: 1.5;
    color: #1a1a1a;
}
```

### Improvement 3: Use Quill 2.x Semantic HTML API
**Issue:** In Section 4, the plan extracts HTML using `quillEditor.root.innerHTML`. In Quill 2.x, this can sometimes include internal Quill classes (e.g., `ql-cursor`, `ql-indent`) or `contenteditable` attributes.
**Fix:** Update `syncQuillToTextarea()` to use Quill 2.0's `getSemanticHTML()` method, which guarantees clean, standards-compliant HTML output.

```javascript
// Replace quillEditor.root.innerHTML with:
const html = quillEditor.getSemanticHTML();
```

### Improvement 4: Source View State Synchronization
**Issue:** The plan states that syncing happens when the source toggle is clicked. However, if a user edits the HTML in the `#html-source` textarea and clicks "Next" or "Send" *without* toggling back to rich text view, their edits won't be captured because the hidden `#body-input` (the canonical field for form submission) hasn't been updated.
**Fix:** Add an `input` event listener to `#html-source` to keep `#body-input` continuously synchronized and to trigger template validation while typing in source mode.

```javascript
$('html-source').addEventListener('input', () => {
    $('body-input').value = $('html-source').value;
    onTemplateChange();
});
```

### Improvement 5: Preserve Undo Stack by Avoiding 'silent' Source
**Issue:** In Sections 4 and 5, the plan uses `quillEditor.setContents(delta, 'silent')` to avoid triggering an infinite loop with the `text-change` listener. However, the Quill API documentation explicitly warns that using the `'silent'` source is not recommended because it breaks the undo stack and history module.
**Fix:** Remove `'silent'` from `setContents()`. Since setting a textarea's `.value` programmatically (in `syncQuillToTextarea`) does *not* trigger DOM `input` or `change` events, there is no risk of an infinite event loop. The `text-change` event will fire, sync the identical content to the textarea once, and stop cleanly, while preserving the user's ability to undo changes.

```javascript
// Change this:
// quillEditor.setContents(delta, 'silent');

// To this:
quillEditor.setContents(delta);
```

Additionally, in Section 6, when inserting placeholder chips, explicitly pass the `'user'` source so the insertion is captured properly in the undo stack:
```javascript
// Change this:
// quillEditor.insertText(range.index, insertion);

// To this:
quillEditor.insertText(range.index, insertion, 'user');
```
