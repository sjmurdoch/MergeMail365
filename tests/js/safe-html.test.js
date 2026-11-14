// Unit tests for src/mail_merge/web/static/safe-html.js (node --test).
// Run through tests/test_wizard_core_js.py, so `uv run pytest` covers them.
const test = require("node:test");
const assert = require("node:assert/strict");
const { escapeHtml, html, joinHtml, raw, setHtml, SafeHtml } = require("../../src/mail_merge/web/static/safe-html.js");

const PAYLOAD = `<img src=x onerror="window.__xss=1">`;

test("escapeHtml covers element content and both kinds of quoted attribute", () => {
    assert.equal(escapeHtml(`a & b < c > d "e" 'f'`), "a &amp; b &lt; c &gt; d &quot;e&quot; &#39;f&#39;");
    assert.equal(escapeHtml(42), "42");
});

test("html`` escapes every interpolated value", () => {
    const out = html`<td title="${`x" onmouseover="alert(1)`}">${PAYLOAD}</td>`;
    assert.ok(out instanceof SafeHtml);
    assert.equal(
        String(out),
        `<td title="x&quot; onmouseover=&quot;alert(1)">&lt;img src=x onerror=&quot;window.__xss=1&quot;&gt;</td>`,
    );
});

test("html`` leaves its own literal markup and nested html`` alone", () => {
    const cell = html`<td>${"R&D"}</td>`;
    assert.equal(String(html`<tr>${cell}</tr>`), "<tr><td>R&amp;D</td></tr>");
});

test("an array is concatenated, each item escaped unless it is SafeHtml", () => {
    const items = ["a<b", html`<b>c</b>`];
    assert.equal(String(html`<p>${items}</p>`), "<p>a&lt;b<b>c</b></p>");
});

test("null and undefined render as nothing; numbers and booleans as text", () => {
    assert.equal(String(html`[${null}${undefined}${0}${false}]`), "[0false]");
});

test("a value that looks like a placeholder or template is still just text", () => {
    assert.equal(String(html`<p>${"${PAYLOAD} {{name}} `x`"}</p>`), "<p>${PAYLOAD} {{name}} `x`</p>");
});

test("joinHtml escapes the items and the separator unless they are SafeHtml", () => {
    assert.equal(String(joinHtml(["a<b", html`<i>c</i>`], html`<hr>`)), "a&lt;b<hr><i>c</i>");
    assert.equal(String(joinHtml(["a", "b"], " < ")), "a &lt; b");
});

test("raw() is the only way to pass markup through unescaped", () => {
    assert.equal(String(html`<p>${raw("<b>bold</b>")}</p>`), "<p><b>bold</b></p>");
});

test("setHtml escapes a plain string: forgetting html`` shows markup as text", () => {
    const el = { innerHTML: "" };
    setHtml(el, PAYLOAD);
    assert.equal(el.innerHTML, "&lt;img src=x onerror=&quot;window.__xss=1&quot;&gt;");
    setHtml(el, html`<b>${PAYLOAD}</b>`);
    assert.equal(el.innerHTML, "<b>&lt;img src=x onerror=&quot;window.__xss=1&quot;&gt;</b>");
    setHtml(el, [html`<i>a</i>`, "<b>"]);
    assert.equal(el.innerHTML, "<i>a</i>&lt;b&gt;");
});
