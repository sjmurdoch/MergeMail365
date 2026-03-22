After sign in completes show confirmation in the app that sign in has been completed successfully.

If the signin fails the app will get stuck at "Waiting for browser sign-in" for a long time. Allow the user to abort the sign-in and try again.

Now that authentication happens in the system browser there's no need to have the desktop application listen on localhost. In desktop mode, pass the Flask application directly to pywebview so there is no risk of CSRF. For example, consider reverting the changes in commit b33867444c27c9a6058396683c5df279e8d9fd29.

-----

Mail merge is a very generic application name. Come up with a selection of few good names to call it. It should be professional, indicate the function, and be memorable. Don't change the name, just suggest some ideas.

Here are some options:

**Descriptive & professional:**
- **MergePost** — clear function, concise
- **SendForge** — forging personalised sends
- **MailStamp** — evokes personalisation (like stamping each letter)

**Graph API / Microsoft angle:**
- **GraphMail** — direct reference to the underlying API
- **MergeMail365** — ties to the Microsoft 365 ecosystem

**Template/personalisation angle:**
- **TemplateSend** — what it does in two words
- **BulkInk** — bulk sending + "ink" as writing/personalisation
- **FormPost** — form letters + posting mail

**Short & punchy:**
- **Meld** — to merge/blend, one syllable, memorable
- **Dispatch** — professional, implies sending at scale
- **Corresponder** — correspondence + sender

My favourites would be **MergePost** (clear, professional, available as a package name likely) or **Dispatch** (short, memorable, implies the bulk-sending use case well).