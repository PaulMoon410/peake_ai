# Grammar & Logic Checker for VS Code

This workspace extension checks your code for grammar and logical correctness with minimal API calls. It analyzes your code for syntax errors, variable declarations, function definitions, and code structure. Every proposed change opens as a VS Code diff and is applied only after you choose **Apply**; applied changes remain undoable in the editor.

## Run it

The extension is a VS Code **workspace** extension. Open `~/peake_ai/vscode-extension` through Remote - SSH on `lubuntu`, then press **F5** to launch the Extension Development Host using the included debug configuration. In that host, open the project folder Harold should work on. For permanent installation, package the folder as a VSIX with `@vscode/vsce` and choose **Extensions: Install from VSIX...**.

1. In the Extension Development Host, open the project folder you want to check.
2. Run **Grammar & Logic: Set API Key** from the Command Palette and enter the server's API key. VS Code SecretStorage keeps it out of settings and project files.
3. Run **Grammar & Logic: Check Code**, describe what code should be checked, and confirm the context-sharing notice.
4. Review each suggested change; apply or decline it. You can save or undo applied changes in VS Code.

By default, the extension uses the API `https://lubuntu.tail239f3d.ts.net/v1`. You can change `grammarLogicChecker.apiBaseUrl` in the settings if needed. The model defaults to `harold`.

## Context and safety

The extension sends the user's task, the workspace file list (up to 200 paths), relevant open files and common root project manifests, and selected editor text. Each included file is limited to 64 KiB and initial context to about 55,000 characters. Environment/secret/key files and generated/dependency directories are blocked. The extension asks before sending context, does not execute shell commands, and will not write a file without showing a diff and obtaining approval.
