const vscode = require("vscode");
const http = require("node:http");
const https = require("node:https");
const path = require("node:path");

const KEY_NAME = "grammarLogicChecker.apiKey";
const MAX_FILE_BYTES = 64 * 1024;
const MAX_CONTEXT_CHARS = 55_000;
const MAX_FILE_LIST = 200;
const MAX_READS = 8;
const MAX_EDITS = 8;
const MAX_ROUNDS = 5;
const EXCLUDE = "**/{.git,.venv,venv,__pycache__,node_modules,dist,build,target,runtime}/**";
const BLOCKED_DIRS = new Set([".git", ".venv", "venv", "__pycache__", "node_modules", "dist", "build", "target", "runtime"]);
const SECRET_PART = /(^|[._-])(api[-_]?keys?|keys?|credentials?|secret|private[-_]?key|password|token|id_rsa|id_ed25519)([._-]|$)/i;
const SECRET_EXT = /\.(pem|key|p12|pfx|env)$/i;
const ROOT_CONTEXT = new Set(["README.md", "AGENTS.md", "pyproject.toml", "package.json", "Cargo.toml", "go.mod", "requirements.txt", "tsconfig.json", "composer.json", "Gemfile"]);
const PROTOCOL = `You are Harold, an expert coding assistant with exceptional linguistic knowledge. Analyze the provided code with attention to grammar, logic, and best practices. First, understand the code thoroughly, then identify improvements in syntax, structure, and clarity. Return ONLY one JSON object in this shape: {"message":"detailed explanation of your analysis and changes","edits":[{"path":"file/path","content":"improved code","reason":"how this change enhances grammar, logic, or readability"}]}. Provide thorough explanations of your analysis. Do not return markdown fences or text outside the JSON.`;

function safePath(value) {
  if (typeof value !== "string" || !value || value.includes("\\") || value.startsWith("/")) return false;
  const parts = value.split("/");
  return !parts.some((part) => !part || part === "." || part === ".." || BLOCKED_DIRS.has(part) || part === ".env" || part === ".ssh" || part.startsWith(".env.") || SECRET_PART.test(part)) && !SECRET_EXT.test(value);
}

function endpointFor(base) {
  const url = new URL(base);
  if (!["http:", "https:"].includes(url.protocol)) throw new Error("API URL must use HTTP or HTTPS.");
  url.pathname = `${url.pathname.replace(/\/+$/, "")}/chat/completions`;
  return url;
}

function requestHarold(url, key, payload) {
  return new Promise((resolve, reject) => {
    const transport = url.protocol === "https:" ? https : http;
    const req = transport.request(url, {
      method: "POST",
      headers: { 
        "Content-Type": "application/json", 
        "Content-Length": Buffer.byteLength(payload), 
        "Authorization": `Bearer ${key}`,
        "Accept": "application/json"
      },
      timeout: 120_000, // 2 minutes should be sufficient for grammar and logic checks
    }, (res) => {
      const chunks = [];
      
      res.on("data", (chunk) => {
        chunks.push(chunk);
      });
      
      res.on("end", () => {
        const text = Buffer.concat(chunks).toString("utf8");
        if (res.statusCode < 200 || res.statusCode >= 300) {
          reject(new Error(`API error: ${res.statusCode} - ${text.slice(0, 200)}`));
          return;
        }
        
        try {
          const data = JSON.parse(text);
          const answer = data.choices?.[0]?.message?.content || data.response || data.content || data.text;
          
          if (!answer || typeof answer !== "string" || !answer.trim()) {
            throw new Error("Invalid or empty response from API");
          }
          
          // Clean up markdown fences if present
          const cleaned = answer.trim().replace(/^```(?:json)?\s*([\s\S]*?)\s*```$/i, "$1");
          resolve(cleaned);
        } catch (error) {
          reject(new Error(`Invalid API response: ${error.message}`));
        }
      });
    });
    
    req.on("timeout", () => {
      req.destroy();
      reject(new Error("Request timed out"));
    });
    
    req.on("error", (error) => {
      reject(new Error(`Network error: ${error.message}`));
    });
    
    req.end(payload);
  });
}

function parsePlan(raw) {
  let text = raw.trim();
  const fence = text.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
  if (fence) text = fence[1];
  const plan = JSON.parse(text);
  if (!plan || typeof plan !== "object" || Array.isArray(plan) || typeof plan.message !== "string" || !Array.isArray(plan.readFiles) || !Array.isArray(plan.edits)) {
    throw new Error("Response must include message, readFiles, and edits as JSON.");
  }
  if (plan.readFiles.length > MAX_READS || plan.edits.length > MAX_EDITS) throw new Error("Requested too many file operations.");
  for (const edit of plan.edits) {
    if (!edit || typeof edit.path !== "string" || typeof edit.content !== "string" || typeof edit.reason !== "string") throw new Error("Returned an invalid edit.");
    if (Buffer.byteLength(edit.content, "utf8") > MAX_FILE_BYTES) throw new Error(`Proposed file exceeds ${MAX_FILE_BYTES} bytes: ${edit.path}`);
  }
  return plan;
}

function relativePath(folder, uri) {
  const owner = vscode.workspace.getWorkspaceFolder(uri);
  if (!owner || owner.uri.toString() !== folder.uri.toString()) return null;
  const name = vscode.workspace.asRelativePath(uri, false).replace(/\\/g, "/");
  return name && !name.startsWith("../") && !path.posix.isAbsolute(name) ? name : null;
}

async function checkPath(folder, name, allowMissing) {
  if (!safePath(name)) throw new Error(`Unsafe or protected workspace path: ${name}`);
  let uri = folder.uri;
  const parts = name.split("/");
  for (let i = 0; i < parts.length; i += 1) {
    uri = vscode.Uri.joinPath(uri, parts[i]);
    try {
      const stat = await vscode.workspace.fs.stat(uri);
      if (stat.type & vscode.FileType.SymbolicLink) throw new Error(`Symbolic links are not allowed: ${name}`);
      if (i < parts.length - 1 && !(stat.type & vscode.FileType.Directory)) throw new Error(`Not a directory: ${name}`);
      if (i === parts.length - 1 && !(stat.type & vscode.FileType.File)) throw new Error(`Not a regular file: ${name}`);
    } catch (error) {
      if (error.code === "FileNotFound" && allowMissing && i === parts.length - 1) return uri;
      throw error;
    }
  }
  return uri;
}

async function readFile(folder, name) {
  const uri = await checkPath(folder, name, false);
  const doc = await vscode.workspace.openTextDocument(uri);
  const text = doc.getText();
  if (Buffer.byteLength(text, "utf8") > MAX_FILE_BYTES) throw new Error(`File exceeds ${MAX_FILE_BYTES} bytes: ${name}`);
  if (text.includes("\0")) throw new Error(`Binary file not included: ${name}`);
  return text;
}

async function collectContext(folder) {
  const uris = await vscode.workspace.findFiles("**/*", EXCLUDE, MAX_FILE_LIST);
  const files = uris.map((uri) => relativePath(folder, uri)).filter((name) => name && safePath(name)).sort();
  const priorities = [];
  const active = vscode.window.activeTextEditor;
  if (active) priorities.push(relativePath(folder, active.document.uri));
  for (const doc of vscode.workspace.textDocuments) priorities.push(relativePath(folder, doc.uri));
  for (const name of files) if (ROOT_CONTEXT.has(path.posix.basename(name))) priorities.push(name);
  const contents = [];
  let used = 0;
  for (const name of [...new Set(priorities)]) {
    if (!name || !files.includes(name) || used >= MAX_CONTEXT_CHARS) continue;
    try {
      const text = await readFile(folder, name);
      const excerpt = text.slice(0, MAX_CONTEXT_CHARS - used);
      contents.push(`--- ${name} ---\n${excerpt}`);
      used += excerpt.length;
    } catch (error) {
      if (error.code !== "FileNotFound") contents.push(`--- ${name} ---\nCould not read: ${error.message}`);
    }
  }
  return { files, contents };
}

function makePrompt(task, context, selection) {
  return `${PROTOCOL}\n\nWorkspace files (relative paths):\n${context.files.join("\n") || "(none found)"}\n\nAvailable file contents:\n${context.contents.join("\n\n") || "(none; request files with readFiles)"}\n\n${selection ? `Selected code:\n${selection.slice(0, 12000)}\n\n` : ""}User request:\n${task}`;
}

async function reviewEdit(folder, edit, output) {
  const uri = await checkPath(folder, edit.path, true);
  let document;
  let before = "";
  let version = null;
  try {
    document = await vscode.workspace.openTextDocument(uri);
    before = document.getText();
    version = document.version;
  } catch (error) {
    if (error.code !== "FileNotFound") throw error;
  }
  if (before === edit.content) {
    output.appendLine(`No change needed for ${edit.path}.`);
    return;
  }
  const preview = await vscode.workspace.openTextDocument({ content: edit.content, language: document && document.languageId });
  const oldDoc = document || await vscode.workspace.openTextDocument({ content: before });
  await vscode.commands.executeCommand("vscode.diff", oldDoc.uri, preview.uri, `Harold: ${edit.path} - ${edit.reason}`);
  const answer = await vscode.window.showWarningMessage(`Apply Harold's change to ${edit.path}?`, { modal: true, detail: edit.reason }, "Apply");
  if (answer !== "Apply") {
    output.appendLine(`Skipped ${edit.path}; no change applied.`);
    return;
  }
  const target = await checkPath(folder, edit.path, true);
  const workspaceEdit = new vscode.WorkspaceEdit();
  if (document) {
    const latest = await vscode.workspace.openTextDocument(target);
    if (latest.version !== version || latest.getText() !== before) throw new Error(`${edit.path} changed while you reviewed the diff; rerun the request to avoid overwriting newer edits.`);
    workspaceEdit.replace(target, new vscode.Range(new vscode.Position(0, 0), latest.positionAt(before.length)), edit.content);
  } else {
    workspaceEdit.createFile(target, { ignoreIfExists: false });
    workspaceEdit.insert(target, new vscode.Position(0, 0), edit.content);
  }
  if (!await vscode.workspace.applyEdit(workspaceEdit)) throw new Error(`VS Code could not apply the change to ${edit.path}.`);
  output.appendLine(`Applied ${edit.path}; the change is open in VS Code and can be saved or undone.`);
}

async function runCodingTask(folder, task, key, config, output, selection) {
  output.appendLine("Analyzing workspace...");
  const context = await collectContext(folder);
  
  // First, let Harold analyze the code with his linguistic expertise
  output.appendLine("Harold is analyzing the code with his linguistic expertise...");
  const analysisPrompt = `As Harold, an expert coding assistant with exceptional linguistic knowledge, analyze the following code:\n\n${context}\n\nProvide a detailed analysis of the code's grammar, logic, and structure. Identify areas for improvement in syntax, readability, and best practices.`;
  
  const history = [
    { role: "system", content: PROTOCOL },
    { role: "user", content: analysisPrompt }
  ];
  
  try {
    // First API call for linguistic analysis
    const analysisPayload = {
      model: config.model,
      messages: history,
      stream: false,
      temperature: 0.7, // Higher temperature for more creative and detailed analysis
      max_tokens: 3000  // Larger token limit for thorough analysis
    };
    
    const analysisResponse = await requestHarold(endpointFor(config.apiBaseUrl), key, JSON.stringify(analysisPayload));
    output.appendLine("Harold completed linguistic analysis...");
    output.appendLine(analysisResponse);
    
    // Now, use the analysis to make targeted improvements
    const improvementPrompt = `Based on your linguistic analysis, improve the code in the following task:\n\nTask: ${task}\n\nCurrent code context:\n${context}\n\nYour analysis:\n${analysisResponse}\n\nReturn your improved code with explanations.`;
    
    history.push({ role: "assistant", content: analysisResponse });
    history.push({ role: "user", content: improvementPrompt });
    
    // Second API call for code improvements
    const improvementPayload = {
      model: config.model,
      messages: history,
      stream: false,
      temperature: 0.3, // Lower temperature for more precise code changes
      max_tokens: 4000
    };
    
    output.appendLine("Harold is suggesting improvements...");
    const raw = await requestHarold(endpointFor(config.apiBaseUrl), key, JSON.stringify(improvementPayload));
    output.appendLine("Processing response...");
    
    let plan;
    try {
      plan = parsePlan(raw);
    } catch (error) {
      output.appendLine(`Error processing response: ${error.message}`);
      output.appendLine(raw);
      return;
    }
    
    if (plan.message) output.appendLine(plan.message);
    
    // Apply all edits
    for (const edit of plan.edits) {
      await reviewEdit(folder, edit, output);
    }
    
    if (!plan.message && !plan.edits.length) {
      output.appendLine("No changes proposed by Harold.");
    }
  } catch (error) {
    output.appendLine(`Error: ${error.message}`);
    vscode.window.showErrorMessage(`Harold coding assistance failed: ${error.message}`);
  }
}

function activate(context) {
  const output = vscode.window.createOutputChannel("Grammar & Logic Checker");
  context.subscriptions.push(output);
  context.subscriptions.push(vscode.commands.registerCommand("grammarLogicChecker.setApiKey", async () => {
    const key = await vscode.window.showInputBox({ prompt: "Grammar & Logic API Key", password: true, ignoreFocusOut: true });
    if (key && key.trim()) {
      await context.secrets.store(KEY_NAME, key.trim());
      vscode.window.showInformationMessage("Grammar & Logic API key stored securely in VS Code.");
    }
  }));
  context.subscriptions.push(vscode.commands.registerCommand("grammarLogicChecker.clearApiKey", async () => {
    await context.secrets.delete(KEY_NAME);
    vscode.window.showInformationMessage("Grammar & Logic API key removed from VS Code.");
  }));
  context.subscriptions.push(vscode.commands.registerCommand("grammarLogicChecker.start", async () => {
    const folders = vscode.workspace.workspaceFolders || [];
    const activeEditor = vscode.window.activeTextEditor;
    const folder = activeEditor && vscode.workspace.getWorkspaceFolder(activeEditor.document.uri) || folders[0];
    if (!folder) return void vscode.window.showErrorMessage("Open a project folder before checking code grammar and logic.");
    const key = await context.secrets.get(KEY_NAME);
    if (!key) {
      const action = await vscode.window.showErrorMessage("Set your Grammar & Logic API key before starting.", "Set API Key");
      if (action) await vscode.commands.executeCommand("grammarLogicChecker.setApiKey");
      return;
    }
    const task = await vscode.window.showInputBox({ prompt: "What code should be checked for grammar and logic?", placeHolder: "Check syntax, variables, functions, and code structure...", ignoreFocusOut: true });
    if (!task || !task.trim()) return;
    const proceed = await vscode.window.showWarningMessage("This will send your request and project context to the API for grammar and logic checking. Proposed changes require your approval.", { modal: true }, "Continue");
    if (proceed !== "Continue") return;
    const activeName = activeEditor && relativePath(folder, activeEditor.document.uri);
    const selection = activeName && safePath(activeName) && !activeEditor.selection.isEmpty
      ? activeEditor.document.getText(activeEditor.selection) : "";
    const config = vscode.workspace.getConfiguration("harold");
    output.clear();
    output.show(true);
    try {
      await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: "Harold is working in your workspace..." }, () =>
        runCodingTask(folder, task.trim(), key, {
          apiBaseUrl: config.get("apiBaseUrl", "https://lubuntu.tail239f3d.ts.net/v1"),
          model: config.get("model", "harold"),
          temperature: 0.1, // Lower temperature for more precise responses
          max_tokens: 4000, // Increase token limit for more detailed responses
        }, output, selection));
    } catch (error) {
      output.appendLine(`Grammar & Logic checking failed: ${error.message}`);
      vscode.window.showErrorMessage(`Grammar & Logic checking failed: ${error.message}`);
    }
  }));
}

function deactivate() {}
module.exports = { activate, deactivate };
