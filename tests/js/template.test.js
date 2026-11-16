// The JavaScript placeholder renderer (the preview) against the cases it
// shares with the Python one (what is sent): tests/data/template_vectors.json.
// Run through tests/test_wizard_core_js.py, so `uv run pytest` covers them.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const T = require("../../src/mail_merge/web/static/template-core.js");

const data = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "data", "template_vectors.json"), "utf8"));

for (const v of data.vectors) {
    test(`vector: ${v.name}`, () => {
        const columns = Object.keys(v.row);
        assert.deepEqual(T.unresolved(v.template, columns, v.html), v.unresolved, "unresolved placeholders");
        assert.equal(T.render(v.template, v.row, v.html), v.rendered, "rendered text");
        assert.equal(T.hasStrayBraces(v.template), v.stray, "stray braces");
    });
}

// The property that failed for {{First-Name}}: the text a chip inserts for
// a column renders to that column's value, whatever the column is called.
for (const column of data.chip_columns) {
    test(`chip for column ${JSON.stringify(column)}`, () => {
        const value = `value of <${column}> & more`;
        const row = { email: "a@example.com", [column]: value };
        const chip = `{{${column}}}`;
        assert.deepEqual(T.unresolved(chip, Object.keys(row)), []);
        assert.equal(T.render(`[${chip}]`, row), `[${value}]`);
        // In an HTML body: typed raw (the source view), or as the rich-text
        // editor writes it, with the name HTML-escaped.
        const escapedChip = `{{${T.escapeValue(column)}}}`;
        for (const written of [chip, escapedChip]) {
            assert.deepEqual(T.unresolved(written, Object.keys(row), true), [], written);
            assert.equal(T.render(`<p>${written}</p>`, row, true), `<p>${T.escapeValue(value)}</p>`, written);
        }
        assert.equal(T.hasStrayBraces(chip), false);
    });
}

test("columns with a brace in the name are reported as unusable", () => {
    assert.deepEqual(T.unusableColumns([...data.chip_columns, ...data.unusable_columns]), data.unusable_columns);
});

test("hasPlaceholders", () => {
    assert.equal(T.hasPlaceholders("Hi {{ anything at all }}"), true);
    assert.equal(T.hasPlaceholders("Hi {name} and {{unfinished"), false);
    // No state is kept between calls (a shared /g regex would alternate).
    assert.equal(T.hasPlaceholders("{{a}}"), true);
    assert.equal(T.hasPlaceholders("{{a}}"), true);
});

test("unescapeEntities knows a fixed list, and numeric references", () => {
    assert.equal(T.unescapeEntities("&amp;&lt;&gt;&quot;&apos;&nbsp;&#65;&#x42;&#X43;"), "&<>\"' ABC");
    assert.equal(T.unescapeEntities("&eacute; &unknown; &#0; &#xD800; &#99999999; & ;"), "&eacute; &unknown; &#0; &#xD800; &#99999999; & ;");
});
