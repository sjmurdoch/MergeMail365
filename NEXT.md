UX can be confusing if an action on a page invalidates data on the same page, but when someone uploads a new workbook or changes the worksheet to be loaded, that affects the preview, placeholders, and field definitions. Split the first step in the Wizard. The first step should be performing the authentication to the GraphAPI, uploading the excel file, selecting the sheet, and showing the preview. The next step should be previewing the data again, selecting the relevant columns and the rest of what is currently in step 1. Pay careful attention to what state is stored, when it is invalidated, and whether it is client side, server side, or local storage to ensure good UX. The app is local so only ever has one session at any one time.

Verify stage didn't show the results of the dry-run (once)

Reload on last page

Review documentation for Pico CSS at https://picocss.com/. Check whether CSS is being used properly in the application and whether Pico CSS has in built facilities that would replace any custom-built features currently in the application. Aim for a functional, consistent, easy-to-use, and maintainable application. Delete redundant and unnecessary CSS and other code.

Implement html-editor-plan.md. Note that Pico is now configured in conditional styling mode so only applies within .pico class containers so that we can avoid conflicts between Pico CSS and Quill CSS.

Add a script to update vendored code with the latest version.