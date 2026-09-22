# legit-pdf2md

Stop PDFs eating your tokens. Turn one into clean Markdown, in your own Drive, without changing a word of it.

A free Claude skill by [Joe Olive / Engine For Impact](https://engineforimpact.com).

## Why

A PDF is the most expensive thing you can hand an AI. It reads the words, **and** it takes a picture of every single page. The same 9-page document loaded two ways:

| | tokens |
|---|---|
| PDF | 17,600 |
| Markdown | 3,350 |

That is **81% smaller** - about five times the room to think before Claude runs out of memory, starts summarising, and forgets what you gave it.

You can already do this by hand: upload to Drive, open with Google Docs, download as Markdown. The catch is what comes out. Google's export is mostly junk - on a real 12-page guide, **78% of the file was images stored as base64 text**, plus `&nbsp;` everywhere and display type broken into `S T A R T W H E R E Y O U A R E`. This skill does the whole thing and cleans up after it.

## Install (about 2 minutes)

1. Open Claude (desktop app or claude.com). In the message box, click the **+** button, then **Plugins**, then **Manage plugins**.
2. Top right of that window, click **Add**, then **Add marketplace**.
3. Paste this in and hit **Sync**:
   ```
   joeoliveimpact/legit-pdf2md
   ```
4. Find **legit-pdf2md** in the list and click **Install**. (Claude will warn you it is a third-party plugin - that is just because it is mine and not Anthropic's. You are good.)
5. Start a new chat and say *"turn this PDF into markdown"* with a Drive link.

Because you installed it as a plugin, it updates itself whenever it improves. Nothing to re-download.

## Connect Google Drive (about 5 minutes, once)

The skill reaches your Drive through [Composio](https://composio.dev). You only do this once.

1. Sign up at [composio.dev](https://composio.dev). The free plan is plenty: 100,000 tool calls a month, unlimited connected accounts, no credit card.
2. In Claude, click the **+** button in the message box, then **Connectors** > **Add connector** > **Add custom connector**. Name it `Composio`, paste this URL, and click **Add**:
   ```
   https://connect.composio.dev/mcp
   ```
   A browser window opens so you can authorise it. That is the whole connection.
3. In Composio, connect the **Google Drive** toolkit to the Google account that holds your PDFs.

That is it. The skill looks for that connection by itself.

### This is worth doing even if you never use this skill again

Composio is one place that holds all of your connections, across 1000+ apps: Drive, Gmail, Calendar, Slack, Notion, your CRM, whatever you run your business on.

That matters because of the wiring. Normally every AI tool you use needs its own connection to every service you use, so ten tools and six services is sixty separate logins to set up and keep alive. With Composio you connect **Composio** to your AI platforms and agents once, and you connect your **services** to Composio once. After that:

- **Adding a new service** - connect it in Composio, and everything already wired to Composio can use it. Nothing else to touch.
- **Removing one** - disconnect it in Composio, and it is gone everywhere at once. No hunting through settings screens wondering what still has access.
- **A new AI tool or agent** - point it at Composio and it arrives with your whole stack already connected.

So the five minutes is not the price of this skill. It is the last time you set up Google Drive for anything.

**On Claude Code instead?** Composio ship their own plugin, which drives the CLI rather than the connector above: add the marketplace `ComposioHQ/composio-plugin-cc`, install **Composio**, then `composio link googledrive`. The skill checks for the connector and the CLI, and uses whichever you have.

**Two Google accounts connected?** That is normal and it is handled - Composio will not act until one is named, so the skill names it and confirms whose Drive it is opening before it writes anything.

**No connection at all?** The skill still works. Do the Drive steps yourself (upload, open with Google Docs, File > Download > Markdown), hand it the file, and it does the cleanup - which is the part you actually wanted. No account needed for that path.

## What you get back

A new file, `<your document> - clean.md`, in the **same Drive folder** as the original, plus a short report: tokens before and after, what was fixed, and what could not be recovered.

Then start a new chat and add the clean file. That is the whole point.

## What it will not do

**It never changes your wording.** Not a rephrase, not a correction, not a "better" heading. After cleaning, it runs a check that compares the result against the source and fails if anything was invented, cut or merged. Headings, spacing and structure are restored by reading the document; the words are yours.

Some things a PDF cannot give back, and it tells you when that happens:

- **Images become `[image N]` placeholders.** The picture is gone from the text; the position is kept.
- **Scans depend on the OCR.** Google reads them well, but a bad scan is still a bad scan.
- **Complex tables and multi-column layouts** come through as best it can and are worth a look.

## Under the hood

- `SKILL.md` - the procedure Claude follows, including how it finds your connection.
- `skills/legit-pdf2md/scripts/clean_gdoc_md.py` - the cleaner. **Standard library only**: no network, no API key, no dependencies. `strip` removes the junk, `check` proves the wording survived, `selftest` proves both work.

```bash
python clean_gdoc_md.py selftest
```

## Licence

MIT. Use it, change it, ship it.
