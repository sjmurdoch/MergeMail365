/* MergeMail365: building HTML from strings without injection.
 *
 * Spreadsheet cells and column headers, file and sheet names, addresses,
 * error text from the server and from Microsoft all end up on the page, and
 * script injected there could send email as the signed-in user. So markup
 * is only ever built with the html`...` template tag, which escapes every
 * value interpolated into it, and only ever put on the page with setHtml().
 * app.js contains no other use of innerHTML (tests/test_spec_coverage.py
 * checks), so a value can't reach the page unescaped by oversight: leaving
 * the escaping out takes a deliberate raw().
 *
 * No DOM here except in setHtml(), so the Node tests in tests/js/ cover it.
 */
((root) => {
    const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

    /** Text as HTML, safe in element content and in quoted attribute values. */
    function escapeHtml(text) {
        return String(text).replace(/[&<>"']/g, c => ESCAPES[c]);
    }

    /** Markup that is already safe: made by html`...`, joinHtml() or raw(). */
    class SafeHtml {
        constructor(markup) { this.markup = markup; }
        toString() { return this.markup; }
    }

    function toMarkup(value) {
        if (value instanceof SafeHtml) return value.markup;
        if (Array.isArray(value)) return value.map(toMarkup).join("");
        if (value === null || value === undefined) return "";
        return escapeHtml(value);
    }

    /** Template tag: the literal parts are markup, every ${value} is escaped
     *  unless it is itself SafeHtml (or an array of values, which are
     *  concatenated). */
    function html(strings, ...values) {
        let out = strings[0];
        values.forEach((value, i) => { out += toMarkup(value) + strings[i + 1]; });
        return new SafeHtml(out);
    }

    /** Values (escaped unless SafeHtml) joined by a separator (likewise). */
    function joinHtml(values, separator = "") {
        return new SafeHtml(values.map(toMarkup).join(toMarkup(separator)));
    }

    /** Trusted markup, taken as it is. Only for text this app wrote itself;
     *  never for anything from a spreadsheet, a file, the clipboard or a
     *  server response. */
    function raw(markup) {
        return new SafeHtml(String(markup));
    }

    /** The one place markup reaches the page. A plain string is escaped, so
     *  forgetting html`...` shows the markup as text rather than running it. */
    function setHtml(element, content) {
        element.innerHTML = toMarkup(content);
    }

    const SafeHtmlLib = { escapeHtml, html, joinHtml, raw, setHtml, SafeHtml };

    if (typeof module === "object" && module.exports) {
        module.exports = SafeHtmlLib;
    } else {
        root.SafeHtmlLib = SafeHtmlLib;
    }
})(typeof globalThis !== "undefined" ? globalThis : this);
