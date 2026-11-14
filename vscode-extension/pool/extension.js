const vscode = require("vscode");
const {CONNECTORS, boundedText, createSession, recordResult, submission} = require("./coordinator");
const STATE = "haroldPool.session";
const KEY = "haroldPool.apiKey";

function activate(context) {
  const output = vscode.window.createOutputChannel("Harold Consensus Pool");
  let busy = false;
  const load = () => context.workspaceState.get(STATE);
  const save = session => context.workspaceState.update(STATE, session);
  function show() {
    const session = load();
    output.clear();
    if (!session) output.appendLine("No session. Run Harold Pool: Start Question.");
    else {
      output.appendLine(`Session ${session.session_id}\nQuestion: ${session.prompt}`);
      for (const name of session.contributors) {
        const result = session.results.find(item => item.name === name);
        output.appendLine(`\n${name}: ${result ? (result.error ? "FAILED" : "operator-submitted answer") : "pending"}`);
        if (result) output.appendLine(result.answer || result.error);
      }
      if (session.final) output.appendLine(`\nHarold synthesis (${session.final.synthesizer}):\n${session.final.response}`);
    }
    output.show();
  }
  function register(name, action) {
    context.subscriptions.push(vscode.commands.registerCommand(name, async () => {
      if (busy) return vscode.window.showWarningMessage("Another pool action is still running.");
      busy = true;
      try {
        if (!vscode.workspace.isTrusted) throw new Error("Trust this workspace before collecting or sharing answers.");
        await action();
      } catch (error) {
        output.appendLine(`Pool error: ${error.message}`);
        await vscode.window.showErrorMessage(`Harold Pool: ${error.message}`);
      } finally { busy = false; }
    }));
  }
  async function pickPending() {
    const session = load();
    if (!session || session.final) throw new Error("Start an unfinished pool session first.");
    const pending = session.contributors.filter(name => !session.results.some(result => result.name === name));
    if (!pending.length) throw new Error("All contributors have a result; finish with Harold.");
    const name = await vscode.window.showQuickPick(pending, {title: `Contributor for session ${session.session_id}`});
    return name ? {session, name} : null;
  }
  register("haroldPool.configureKey", async () => {
    const key = await vscode.window.showInputBox({password: true, ignoreFocusOut: true, prompt: "Harold CHAT_API_KEY (stored in VS Code SecretStorage)"});
    if (key === undefined) return;
    if (!key.trim()) throw new Error("API key cannot be empty.");
    await context.secrets.store(KEY, key.trim());
    await vscode.window.showInformationMessage("Harold Pool API key saved.");
  });
  register("haroldPool.start", async () => {
    const previous = load();
    if (previous && !previous.final) {
      const replace = await vscode.window.showWarningMessage("Discard the unfinished pool session and its collected answers?", {modal: true}, "Discard and start");
      if (!replace) return;
    }
    const prompt = await vscode.window.showInputBox({prompt: "One question for all independent contributors (maximum 4,000 characters)", ignoreFocusOut: true});
    if (prompt === undefined) return;
    boundedText(prompt);
    const available = Object.keys(CONNECTORS).filter(name => vscode.extensions.getExtension(CONNECTORS[name].id));
    const names = await vscode.window.showQuickPick(available, {canPickMany: true, title: "Choose at least two independently configured extensions"});
    if (!names) return;
    const session = createSession(prompt, names);
    const approved = await vscode.window.showWarningMessage(
      "Confirm these extensions use independent models, not Harold. You will manually send the question and submit final answers. Questions and answers are saved in this workspace's VS Code state. Each extension's own approval and billing settings apply.",
      {modal: true}, "Start collection",
    );
    if (!approved) return;
    await save(session);
    show();
  });
  register("haroldPool.ask", async () => {
    const chosen = await pickPending();
    if (!chosen) return;
    const {session, name} = chosen;
    const connector = CONNECTORS[name];
    const extension = vscode.extensions.getExtension(connector.id);
    if (!extension) throw new Error(`${name} is not installed in this extension host.`);
    await extension.activate();
    if (!(await vscode.commands.getCommands(true)).includes(connector.command)) {
      throw new Error(`${name}'s supported chat-focus command is unavailable.`);
    }
    const approved = await vscode.window.showInformationMessage(
      `Copy session ${session.session_id}'s question to the clipboard and open ${name}? Paste and send it there yourself.`,
      {modal: true}, "Copy and open",
    );
    if (!approved) return;
    await vscode.env.clipboard.writeText(`Pool session: ${session.session_id}\nAnswer independently. Do not change files or run tools for this request.\n\n${session.prompt}`);
    await vscode.commands.executeCommand(connector.command);
    output.appendLine(`${name}: question copied and chat focused; delivery is not automatic.`);
  });
  register("haroldPool.submit", async () => {
    const chosen = await pickPending();
    if (!chosen) return;
    const text = await vscode.env.clipboard.readText();
    boundedText(text);
    const approved = await vscode.window.showWarningMessage(
      `Submit ${text.length} clipboard characters as ${chosen.name}'s final answer to this exact question?\n${chosen.session.prompt}\n\nPreview: ${text.slice(0, 300)}\nOnly use a completed answer, not private reasoning or unrelated text.`,
      {modal: true}, "Submit answer",
    );
    if (!approved) return;
    await save(recordResult(chosen.session, chosen.name, text));
    show();
  });
  register("haroldPool.fail", async () => {
    const chosen = await pickPending();
    if (!chosen) return;
    const reason = await vscode.window.showInputBox({prompt: `Why did ${chosen.name} fail or become unavailable?`});
    if (reason === undefined) return;
    await save(recordResult(chosen.session, chosen.name, reason, true));
    show();
  });
  register("haroldPool.finish", async () => {
    const session = load();
    const payload = submission(session);
    const key = await context.secrets.get(KEY);
    if (!key) throw new Error("Run Harold Pool: Configure API Key first.");
    const base = new URL(vscode.workspace.getConfiguration("haroldPool").get("serverUrl"));
    if (base.username || base.password || base.search || base.hash || !["", "/"].includes(base.pathname)
        || (base.protocol !== "https:" && !(base.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(base.hostname)))) {
      throw new Error("Server URL must be an HTTPS origin or loopback HTTP origin, with no credentials or base path.");
    }
    const approved = await vscode.window.showWarningMessage(
      `Send this question and all ${payload.results.length} labeled results to Harold at ${base.origin}? Harold's configured synthesis providers may receive the contents. Do not include credentials or private reasoning.`,
      {modal: true}, "Send to Harold",
    );
    if (!approved) return;
    await vscode.window.withProgress({location: vscode.ProgressLocation.Notification, title: "Harold is evaluating the collected answers"}, async () => {
      const response = await fetch(new URL("/api/extension/pool/synthesize", base), {
        method: "POST", headers: {"Authorization": `Bearer ${key}`, "Content-Type": "application/json"},
        body: JSON.stringify(payload), signal: AbortSignal.timeout(120000), redirect: "error",
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.error === "string" ? data.error : `Harold returned HTTP ${response.status}`);
      if (data.session_id !== session.session_id || typeof data.response !== "string" || !data.response.trim()
          || typeof data.synthesizer !== "string") throw new Error("Harold returned an invalid or mismatched session result.");
      await save({...session, final: {response: data.response, synthesizer: data.synthesizer}});
    });
    show();
  });
  register("haroldPool.status", show);
  context.subscriptions.push(output);
}

module.exports = {activate};
