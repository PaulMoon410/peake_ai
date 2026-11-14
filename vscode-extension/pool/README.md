# Harold Consensus Coordinator

A truthful manual-response coordinator for Cline, Kilo and CodeGeeX. It does
not pretend that these extensions expose HTTP chat servers or intercept their
private webviews. It opens their registered chat-focus commands; it does not
automatically send prompts, capture private reasoning, or execute their tools.

The source and synthesis service live in `peake_ai` on lubuntu. Install the VSIX
in the VS Code extension host where the contributors are installed (local or
Remote SSH). Clipboard access occurs in the client; synthesis occurs on the
server. No Ollama installation is needed.

Command Palette workflow:

1. **Harold Pool: Configure API Key**: enter Harold's CHAT_API_KEY. It is held
   in VS Code SecretStorage, never a settings file.
2. **Harold Pool: Start Question**: select at least two independent contributors
   and confirm their model/account configuration. Do not choose Harold-backed
   contributors. The extension cannot independently verify their model choices.
3. **Harold Pool: Ask Contributor**: copies the common question and session ID,
   then focuses the contributor chat. Paste and send manually.
4. Copy that contributor's completed answer and run **Harold Pool: Submit
   Clipboard Response**. Confirm the contributor and question. Repeat for each;
   use **Mark Contributor Failed** for explicit failures.
5. **Harold Pool: Finish with Harold**: approve sharing the question and results.
   At least two actual answers are required, and every selected contributor must
   have a result. The server evaluates agreements, disagreements and uncertainty
   through Harold's existing non-tool completion helper. Its provider identity
   is shown; this is not guaranteed local-only inference.

**Show Session** displays source answers, failures and Harold's final synthesis
in the **Harold Consensus Pool** output channel. This does not insert text into
another extension's private chat UI. You can copy the final answer where needed.

One session per workspace is saved in VS Code workspace state and survives a
reload. Replacing an unfinished session requires confirmation. Failed synthesis
retains collected answers for retry. Questions, answers and failure messages
are limited to 4,000 characters each, with no silent truncation. Source labels
are operator assertions, not cryptographic proof; agreement is not correctness.
The finish operation times out after 120 seconds on the client; an existing
server model call may continue until its configured provider timeout.

Backend: authenticated `POST /api/extension/pool/synthesize`. Configure
`haroldPool.serverUrl` as `https://lubuntu.tail239f3d.ts.net` (no `/ollama` or
`/v1` suffix). HTTPS is required except for loopback. No extension state or
responses are sent to the server until you approve **Finish with Harold**.

Run `npm test` for the pure coordinator tests. Package with the existing VSCE
tool; no new runtime dependencies are required.
