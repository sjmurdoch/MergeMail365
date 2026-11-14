/* MergeMail365: placeholders, {{column name}} in a subject or body.
 *
 * The same grammar as src/mail_merge/template.py, which renders what is
 * sent; this renders the preview. Both run every case in
 * tests/data/template_vectors.json (tests/js/template.test.js and
 * tests/test_template.py), so the preview and the email cannot differ.
 * Read template.py's docstring for the grammar; change the two together.
 *
 * No DOM: loaded before app.js (window.TemplateCore) and by the Node tests.
 */
((root) => {
    const PLACEHOLDER_SRC = String.raw`\{\{([^{}]*)\}\}`;
    const TAG_RE = /<[^<>]*>/g;
    // Spelt out, not \s: Python's and JavaScript's \s differ.
    const SPACES_RE = /[ \t\n\r\f\v ]+/g;
    const HTML_ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
    const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };
    const ENTITY_RE = /&(?:#([0-9]{1,7})|#[xX]([0-9a-fA-F]{1,6})|([a-zA-Z]+));/g;

    function placeholderRe() { return new RegExp(PLACEHOLDER_SRC, "g"); }

    /** A column or placeholder name as compared. */
    function normalizeName(name) {
        return name.replace(SPACES_RE, " ").trim().toLowerCase();
    }

    /** A placeholder's text as shown in messages. */
    function displayName(raw) {
        return raw.replace(SPACES_RE, " ").trim();
    }

    function unescapeEntities(text) {
        return text.replace(ENTITY_RE, (match, decimal, hexadecimal, name) => {
            if (name !== undefined) return Object.hasOwn(ENTITIES, name) ? ENTITIES[name] : match;
            const code = decimal !== undefined ? parseInt(decimal, 10) : parseInt(hexadecimal, 16);
            const valid = code > 0 && code <= 0x10ffff && !(code >= 0xd800 && code <= 0xdfff);
            return valid ? String.fromCodePoint(code) : match;
        });
    }

    /** The column names the text between the braces may mean, most likely
     *  first. In HTML it may be HTML-escaped, raw, or have tags inside. */
    function candidateNames(raw, html) {
        if (!html) return [normalizeName(raw)];
        return [...new Set([
            normalizeName(unescapeEntities(raw)),
            normalizeName(raw),
            normalizeName(unescapeEntities(raw.replace(TAG_RE, ""))),
        ])];
    }

    /** A cell's text as HTML: markup characters escaped, line breaks kept. */
    function escapeValue(value) {
        return value.replace(/[&<>"']/g, c => HTML_ESCAPES[c])
            .replace(/\r\n/g, "\n").replace(/\r/g, "\n").replace(/\n/g, "<br>");
    }

    function lookup(columns, raw, html) {
        for (const name of candidateNames(raw, html)) {
            if (columns.has(name)) return columns.get(name);
        }
        return undefined;
    }

    /** Whether the text has any placeholder at all (BCC mode allows none). */
    function hasPlaceholders(template) {
        return placeholderRe().test(template);
    }

    /** The placeholders that name no column, sorted. */
    function unresolved(template, columns, html = false) {
        const known = new Map(columns.map(c => [normalizeName(c), c]));
        const bad = new Set();
        for (const m of template.matchAll(placeholderRe())) {
            if (lookup(known, m[1], html) === undefined) bad.add(displayName(m[1]));
        }
        return [...bad].sort();
    }

    /** Whether a {{ or }} is left once the placeholders are taken out. */
    function hasStrayBraces(template) {
        const rest = template.replace(placeholderRe(), "");
        return rest.includes("{{") || rest.includes("}}");
    }

    /** Columns that no placeholder can name, because the name has a brace. */
    function unusableColumns(columns) {
        return columns.filter(c => c.includes("{") || c.includes("}"));
    }

    /** Substitute {{column}} placeholders with the row's values; with
     *  `html`, names are read as HTML and values are escaped. */
    function render(template, row, html = false) {
        const values = new Map(Object.entries(row).map(([k, v]) => [normalizeName(k), String(v)]));
        return template.replace(placeholderRe(), (match, raw) => {
            const value = lookup(values, raw, html);
            if (value === undefined) return match;
            return html ? escapeValue(value) : value;
        });
    }

    const TemplateCore = {
        normalizeName, displayName, candidateNames, escapeValue, unescapeEntities,
        hasPlaceholders, unresolved, hasStrayBraces, unusableColumns, render,
    };

    if (typeof module === "object" && module.exports) {
        module.exports = TemplateCore;
    } else {
        root.TemplateCore = TemplateCore;
    }
})(typeof globalThis !== "undefined" ? globalThis : this);
