# Harold AI Agent for VS Code

## Automatic consensus in Harold Chat

Enable **Assistant pool**, then enter `/pool Your question` in Harold Chat,
or run **Harold: Ask Consensus Pool**. Sharing follows the existing Harold
Approvals terminal policy; **Always approve all Harold actions** also approves
this provider sharing. Once approved, collection and synthesis run automatically.

The server queries its independently configured Google, Groq and OpenRouter
API adapters in parallel, retains explicit provider failures, requires at least
two answers, then asks Harold's configured non-tool synthesis helper to evaluate
the evidence. The final answer and labeled source answers appear in Harold Chat.
Provider billing settings still apply. This is **server-model consensus**, not
automatic execution of Cline, Kilo or CodeGeeX. Native extension connectors
remain separate; the manual response coordinator still supports their answers.

The tool `query_consensus_pool` exposes the same operation to Harold's coding
chat. It never shares an active file implicitly or executes workspace tools.
Questions are limited to 4,000 characters. Failures never count as votes, and
retrying an automatic request may query the source providers again.

Chat with Harold from a VS Code sidebar, ask questions about the active file, and generate code. By default, workspace coding requests automatically read non-secret files and apply edits without confirmation; the chat displays the number of applied edits. For persistent approval of all Harold actions, including sharing with configured assistant providers, select **Always approve all Harold actions (including provider sharing)** in the chat. The choice is saved globally. When confirmation is needed, answer y or n in the **Harold Approvals** terminal instead of a popup. Closing the terminal declines the action.

## Use your home-PC workspace from a browser

The extension edits the workspace opened in VS Code. For remote access, connect to the VS Code instance on your home PC with a signed-in VS Code Tunnel; the extension and workspace then continue running on that PC.

1. On the home PC, install VS Code and sign in with a Microsoft or GitHub account.
2. Start a VS Code Tunnel from the Command Palette with **Remote Tunnels: Turn on Remote Tunnel Access**, or run `code tunnel` in a terminal and complete the sign-in prompts. Leave the tunnel host running while you need remote access.
3. From a browser, open [vscode.dev](https://vscode.dev), sign in with the same account, and connect to the home PC under **Remote Explorer: Tunnels**. You can also use `https://vscode.dev/tunnel/<machine-name>` after the tunnel has been created.
4. Open your project folder in the remote VS Code window. Install Harold in that window if it is not already available there. Run **Harold: Open Chat**.
5. To provide file context, select **Include active file** before sending a chat message. Or use **Harold: Read Current File** / **Harold: Propose Edit to Current File** from the Command Palette.
6. Workspace coding actions are automatically approved by default. To review each proposed edit, disable both `harold.autoApproveAllActions` and `harold.autoApproveWorkspaceActions`; then review the diff and answer y or n in the **Harold Approvals** terminal.

The Tunnel is authenticated through your VS Code account. A Tailscale Funnel is publicly reachable and is not an appropriate access-control boundary for a service that can edit workspace files; do not expose a file-editing bridge through it. If you use Tailscale for private network access, keep it private and do not substitute Funnel exposure for authentication.

## Install and configure

1. In this directory, run `npm install` and `npm run compile`.
2. To create an installable VSIX, run `npm run package`.
3. In VS Code, choose **Extensions: Install from VSIX...** and select the generated `harold-*.vsix`.
4. Run **Harold: Configure Chat API Key** and enter the Harold API key. It is stored using VS Code SecretStorage, not in workspace files or webview content.
5. Run **Harold: Open Chat** from the Command Palette or open the Harold activity-bar view.

The extension uses Harold's OpenAI-compatible chat endpoint. Its default API base is `https://lubuntu.tail239f3d.ts.net`; configure `harold.apiBaseUrl` if needed. The extension adds `/v1/chat/completions` (or `/chat/completions` when the configured URL already ends in `/v1`).

The full default endpoint is `https://lubuntu.tail239f3d.ts.net/v1/chat/completions`.
The server's `/api/chat` route uses a different request/response format and is not the endpoint used by this extension.

### Fixing an empty chat panel

Version 0.4.1 fixes the view declaration responsible for the message
“There is no data provider registered that can provide view data.”
Install `harold-chat-0.4.1.vsix`, run **Developer: Reload Window**, then run
**Harold: Open Chat**. The panel should show a message input and a **Send** button
even before an API key is configured. Configure the key if prompted when sending.

Run `npm test` to check view registration, rendering, and the extension's chat
request/reply flow against a local test server.

Press **Ctrl+Enter** to send a chat message; Enter inserts a new line.

## Commands

| Command | Description |
|---------|-------------|
| `Harold: Open Chat` | Open the Harold chat sidebar |
| `Harold: Configure Chat API Key` | Store the API key securely |
| `Harold: Create File/Program` | Describe a new file to generate |
| `Harold: Read Current File` | Ask Harold to summarize the active file |
| `Harold: Propose Edit to Current File` | Ask Harold to rewrite the active file from an instruction |

Generated fenced code blocks include **Apply to active file** and **Save as file...** actions. Unless `harold.autoApproveAllActions` is enabled, both open a diff and ask for confirmation in the **Harold Approvals** terminal before writing. If a target file changes while its diff is open, the extension refuses to apply the stale proposal.

## Settings

- `harold.apiBaseUrl` — Harold API base URL; default `https://lubuntu.tail239f3d.ts.net`.
- `harold.model` — model name; default `harold`.
- `harold.stream` — request a streamed response; default `false`.
- `harold.assistantPoolEnabled` — let Harold query the AI Bridge assistant pool; default `false`. Toggle it with the **Use assistant pool (AI Bridge)** checkbox in Harold Chat. When off, the pool tool is not offered to Harold and nothing is shared.
- `harold.autoApproveAllActions` — persistently approve all supported Harold reads, edits and sharing with configured assistant providers without confirmations; default `false`. File contents may be sent to external providers. You can toggle this in Harold Chat.
- `harold.autoApproveWorkspaceActions` — automatically share requested non-secret workspace files with Harold and configured providers and apply workspace-tool edits without a diff or confirmation; default `true`. Disable this and `harold.autoApproveAllActions` to review edits and reads; answer y or n in the **Harold Approvals** terminal.
- `harold.autoApproveWorkspaceReads` — allow reads without prompts even when automatic workspace actions are disabled; default `false`.

The extension can also be used as a Harold API backend by other extensions that can access its VS Code extension exports: `getHaroldApiKey()` (returns a promise), `getHaroldApiBaseUrl()`, and `getHaroldModel()`.

## Workspace coding in Harold Chat

Coding requests in the sidebar automatically use the OpenAI-compatible workspace-tool route. You can also select **Use workspace tools** for a request that does not mention coding. Ordinary conversation continues to use Harold's existing chat route and own-model behavior. No Ollama model or separate coding extension is required.

Once a coding request starts, **Use workspace tools** remains checked for follow-up instructions (for example, "Now add a greeting"). Uncheck it to return to ordinary chat. **Create File/Program** and **Propose Edit to Current File** request actual workspace edit proposals, not just fenced code in chat. Version 0.4.6 also preserves provider tool-call metadata required by Google to continue after file reads or edits. Install the update in the VS Code window hosting your workspace, then reload that window.

Open and trust a workspace first. No active editor is required for chat or workspace tools. If **Include active file** is selected without an open editor, Harold sends the message without file contents, displays a notice, and clears the checkbox; explicit current-file commands still require an editor. By default, workspace tools can share requested non-secret UTF-8 files with Harold and configured AI providers and create or replace files without a popup or diff. Disable both `harold.autoApproveAllActions` and `harold.autoApproveWorkspaceActions` to review changes and reads; `harold.autoApproveWorkspaceReads` can separately allow reads. Automatic edits refuse dirty open documents; save them first. Paths outside the workspace, symbolic links, and credential paths are blocked. No deletion or terminal tool is available. The chat counts applied file edits per request; unchanged or declined proposals are not counted. Direct fenced-code actions require a diff and terminal confirmation unless `harold.autoApproveAllActions` is enabled. Declined actions are reported as `declined`, not as a successful write.

The assistant pool is off by default; tick **Use assistant pool (AI Bridge)** in the chat window to enable it. When you ask Harold to query AI Bridge or other assistants, the workspace tool invokes the installed `moon.ai-bridge-extension` through VS Code’s local extension API, passing the open non-secret file when applicable. Harold asks for confirmation in the **Harold Approvals** terminal before sharing the prompt/file with the pool unless `harold.autoApproveAllActions` is enabled; workspace-only auto-approval does not approve pool sharing. Harold itself is excluded from that pool call to prevent recursion. No public HTTP endpoint exposes the VS Code pool tool; it only runs inside the trusted local/remote VS Code extension host.

Version 0.4.7 reports missing read/list paths to Harold so he can check the workspace and retry; it still displays an error and does not retry permission, safety, or edit failures.

The client allows ten minutes per API request. Coding tool requests use complete JSON responses even if ordinary chat streaming is enabled. A coding task can use up to 32 tool-response rounds plus a final response; provider-side limits may be shorter. Errors are displayed rather than converted into ordinary chat.

The source and build are maintained on lubuntu under `~/harold-client/harold-chat`; the unmodified 0.4.1 package and source backup are retained alongside it. Files are edited in the workspace of the extension host: a Remote-SSH window operates on lubuntu, while a local window operates on the PC. The Harold API continues running only on lubuntu.

## Pool and build

Run **Harold: Pool and Build Workspace** with a trusted project folder open. The bridge reads all `.md`, `.markdown`, `.txt`, and `.text` sources recursively under `.ai-pool`, excluding `cleaned-master.md`. It includes source paths and SHA-256 provenance, requests sharing permission in the **Harold Approvals** terminal unless `harold.autoApproveAllActions` is enabled before sending material to Harold/its configured providers, and uses the existing validated workspace-tool loop to propose the master specification and deliverable. No active editor is needed.

Symbolic links, credential paths, invalid UTF-8, more than 64 files / 128 folders / 16 directory levels, or more than 100,000 aggregate characters fail explicitly without sharing a partial pool. Missing sources are reported, not invented. File edits follow the workspace approval setting. Deliverable edits are refused until the master proposal is applied or confirmed unchanged; declining the master does not authorize later writes. The bridge cannot run terminal commands or synthesize binary images/audio; it reports execution or rendering that still needs verification rather than claiming success. Actual source reads, file proposals, declines and API errors remain visible.
