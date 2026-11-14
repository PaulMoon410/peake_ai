const test = require("node:test");
const assert = require("node:assert/strict");
const Module = require("node:module");
const commands = new Map();
let state;
let clipboard = "";
let choice = "cline";
let approve = true;
const errors = [];
const opened = [];
const vscode = {
  workspace: {isTrusted: true, getConfiguration: () => ({get: () => "https://example.invalid"})},
  commands: {
    registerCommand: (name, action) => {commands.set(name, action); return {dispose() {}};},
    getCommands: async () => ["cline.focusChatInput", "kilo-code.new.focusChatInput"],
    executeCommand: async name => opened.push(name),
  },
  extensions: {getExtension: () => ({activate: async () => {}})},
  env: {clipboard: {writeText: async text => {clipboard = text;}, readText: async () => clipboard}},
  ProgressLocation: {Notification: 1},
  window: {
    createOutputChannel: () => ({clear() {}, appendLine() {}, show() {}, dispose() {}}),
    showInputBox: async () => "A common question",
    showQuickPick: async (items, options) => options.canPickMany ? ["cline", "kilo"] : choice,
    showWarningMessage: async () => approve ? "Approved" : undefined,
    showInformationMessage: async () => approve ? "Approved" : undefined,
    showErrorMessage: async message => errors.push(message),
    withProgress: async (options, action) => action(),
  },
};
const loader = Module._load;
Module._load = function(name, ...args) {
  return name === "vscode" ? vscode : loader.call(this, name, ...args);
};
const {activate} = require("./extension");
Module._load = loader;
activate({
  subscriptions: [],
  workspaceState: {get: () => state, update: async (key, value) => {state = value;}},
  secrets: {get: async () => "test-key", store: async () => {}},
});

test("manual workflow requires approval and preserves answers after failed synthesis", async t => {
  await commands.get("haroldPool.start")();
  await commands.get("haroldPool.ask")();
  assert.equal(opened[0], "cline.focusChatInput");
  assert.ok(clipboard.includes(state.session_id));
  assert.ok(clipboard.includes(state.prompt));
  clipboard = "Cline's completed answer";
  approve = false;
  await commands.get("haroldPool.submit")();
  assert.equal(state.results.length, 0);
  approve = true;
  await commands.get("haroldPool.submit")();
  choice = "kilo";
  clipboard = "Kilo's completed answer";
  await commands.get("haroldPool.submit")();
  let requests = 0;
  t.mock.method(global, "fetch", async (url, options) => {
    requests++;
    assert.equal(new URL(url).pathname, "/api/extension/pool/synthesize");
    assert.equal(options.redirect, "error");
    const payload = JSON.parse(options.body);
    assert.deepEqual(payload.results, state.results);
    return {ok: false, status: 503, json: async () => ({error: "Busy"})};
  });
  approve = false;
  await commands.get("haroldPool.finish")();
  assert.equal(requests, 0);
  approve = true;
  await commands.get("haroldPool.finish")();
  assert.equal(state.final, null);
  assert.equal(state.results.length, 2);
  assert.ok(errors.some(message => message.includes("Busy")));
  t.mock.method(global, "fetch", async () => ({
    ok: true, json: async () => ({session_id: state.session_id, response: "Harold's final evaluation", synthesizer: "test-model"}),
  }));
  await commands.get("haroldPool.finish")();
  assert.equal(state.final.response, "Harold's final evaluation");
  assert.equal(state.final.synthesizer, "test-model");
});
