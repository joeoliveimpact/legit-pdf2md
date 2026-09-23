# Tools reference and known limits

Read this when a Composio call fails validation, when you need a tool's name for a step, or when the wording check reports something the steps in `SKILL.md` do not explain.

## Known limits

- The wording check compares letters and digits, not punctuation. That is why Step 3 never touches code; a changed symbol elsewhere in the text is not caught.
- Letter-spaced type is recognized by pattern: three or more single characters in a row, separated by plain spaces, with two- or three-letter OCR chunks allowed between them as long as the run still starts on a single character and is mostly single characters. Unusual spacing may need a closer look at the `split_words` and `merged_words` lists.
- A run may end on one such chunk (`P A S TE:`), so a real two- or three-letter capital word sitting immediately after display type could be absorbed into it without the check objecting. Leading words are never absorbed.
- Indented code blocks (four spaces, no fence) are not detected. Google's export uses fences, so this rarely matters.
- Link addresses do not survive Google's export; only the link text does.

## Tools reference

| Step | Composio tool | Note |
|---|---|---|
| Find | `GOOGLEDRIVE_FIND_FILE`, `GOOGLEDRIVE_GET_FILE_METADATA` | `fileId`, plus `fields` for `parents` |
| Wrong account? | `GOOGLEDRIVE_GET_ABOUT` | run on any 404 |
| PDF to Doc | `GOOGLEDRIVE_COPY_FILE_ADVANCED` | `fileId`, `ocrLanguage` |
| Export | `GOOGLEDRIVE_EXPORT_GOOGLE_WORKSPACE_FILE` | link expires in 1 hour |
| Clean up temp Doc | `GOOGLEDRIVE_TRASH_FILE` | `file_id`, not `fileId` |
| Run a tool via the connector | `COMPOSIO_MULTI_EXECUTE_TOOL` | pass `tool_slug`, `arguments`, `account` |
| Run script remotely | `COMPOSIO_REMOTE_WORKBENCH` | chat app; script from the repo raw URL |
| Save | `GOOGLEDRIVE_CREATE_FILE_FROM_TEXT` | `parent_id` |

Parameter casing differs between these tools; when a call fails validation, read that tool's schema rather than assuming (`--get-schema` on the CLI). Every `GOOGLEDRIVE_*` tool above works unchanged through the Composio MCP connection and through the CLI (`composio execute <TOOL> -d '{...}'`), which is why Step 0 only has to decide which one is live.
