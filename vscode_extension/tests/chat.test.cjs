const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const root = path.join(__dirname, '..');
const manifest = require('../package.json');

function loadExtension(vscode) {
  const exports = {};
  const source = fs.readFileSync(path.join(root, 'out/extension.js'), 'utf8');
  const context = {
    exports,
    require: name => name === 'vscode' ? vscode : require(name),
    Buffer, URL, TextDecoder, Uint8Array
  };
  vm.runInNewContext(source, context, { filename: 'extension.js' });
  return exports;
}

function createHarness(baseUrl, overrides = {}, settings = {}) {
  const commands = new Map();
  const providers = new Map();
  const posts = new EventEmitter();
  const errors = [];
  const disposable = { dispose() {} };
  const vscode = {
    ConfigurationTarget: { Global: 1 },
    workspace: {
      getConfiguration: () => ({
        get: (name, fallback) => name === 'harold.apiBaseUrl' ? baseUrl : settings[name] ?? (name === 'harold.autoApproveWorkspaceActions' ? false : fallback),
        update: async (name, value, target) => { assert.equal(target, 1); settings[name] = value; }
      })
    },
    window: {
      registerWebviewViewProvider: (id, provider) => {
        providers.set(id, provider);
        return disposable;
      },
      showErrorMessage: message => errors.push(message)
    },
    commands: {
      registerCommand: (id, callback) => {
        commands.set(id, callback);
        return disposable;
      }
    }
  };
  for (const [name, value] of Object.entries(overrides)) {
    vscode[name] = ['workspace', 'window', 'commands'].includes(name) ? { ...vscode[name], ...value } : value;
  }
  const extension = loadExtension(vscode);
  extension.activate({
    subscriptions: [],
    secrets: { get: async () => 'test-key-not-a-real-secret' }
  });
  let onMessage;
  const webview = {
    cspSource: 'vscode-webview:',
    onDidReceiveMessage: callback => {
      onMessage = callback;
      return disposable;
    },
    postMessage: message => {
      posts.emit('message', message);
      return Promise.resolve(true);
    }
  };
  const view = manifest.contributes.views.haroldSidebar[0];
  assert.equal(view.type, 'webview', 'VS Code defaults to a tree view if type is missing');
  assert.ok(providers.has(view.id), 'The manifest and registered provider IDs must match');
  providers.get(view.id).resolveWebviewView({ webview });
  return { webview, commands, posts, errors, send: message => onMessage(message) };
}

function waitForPost(harness, type) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      harness.posts.removeListener('message', listener);
      reject(new Error(`Timed out waiting for ${type}`));
    }, 5000);
    const listener = message => {
      if (message.type !== type) return;
      clearTimeout(timer);
      harness.posts.removeListener('message', listener);
      resolve(message);
    };
    harness.posts.on('message', listener);
  });
}

test('chat is declared as a webview and all contributed commands are registered', () => {
  const harness = createHarness('https://lubuntu.tail239f3d.ts.net');
  for (const command of manifest.contributes.commands) {
    assert.ok(harness.commands.has(command.command), command.command);
  }
  assert.ok(manifest.activationEvents.includes('onView:haroldChat'));
  assert.match(harness.webview.html, /<textarea id="prompt"/);
  assert.match(harness.webview.html, /<button id="send" type="submit">Send<\/button>/);
  assert.equal(harness.webview.options.enableScripts, true);
  assert.ok(!harness.webview.html.includes('test-key-not-a-real-secret'));
});

test('webview script sends input and renders assistant messages as text', () => {
  const harness = createHarness('https://lubuntu.tail239f3d.ts.net');
  class Element {
    children = [];
    listeners = {};
    value = '';
    textContent = '';
    checked = false;
    appendChild(child) { this.children.push(child); }
    addEventListener(name, callback) { this.listeners[name] = callback; }
    replaceChildren() { this.children = []; }
    requestSubmit() { this.listeners.submit({ preventDefault() {} }); }
  }
  const elements = new Map(
    ['messages', 'status', 'edit-count', 'approval-mode', 'auto-approve-all', 'prompt', 'form', 'send', 'include-file', 'workspace-tools', 'assistant-pool'].map(id => [id, new Element()])
  );
  const sent = [];
  let receive;
  const script = harness.webview.html.match(/<script nonce="[^"]+">([\s\S]*?)<\/script>/)[1];
  vm.runInNewContext(script, {
    acquireVsCodeApi: () => ({ postMessage: message => sent.push(message) }),
    document: {
      getElementById: id => elements.get(id),
      createElement: () => new Element()
    },
    window: { addEventListener: (_, listener) => { receive = listener; } }
  });
  assert.equal(sent[0].type, 'ready');
  elements.get('prompt').value = 'Hello Harold';
  elements.get('form').listeners.submit({ preventDefault() {} });
  assert.equal(sent[1].type, 'send');
  assert.equal(sent[1].content, 'Hello Harold');
  receive({ data: { type: 'assistant', content: '<b>Reply is plain text</b>', blocks: [] } });
  assert.equal(elements.get('messages').children[1].children[1].textContent, '<b>Reply is plain text</b>');
  receive({ data: { type: 'workspace-mode', enabled: true } });
  receive({ data: { type: 'edit-count', count: 3 } });
  assert.equal(elements.get('edit-count').textContent, 'Edits applied: 3');
  receive({ data: { type: 'approval-mode', enabled: true } });
  assert.match(elements.get('approval-mode').textContent, /auto-approved/);
  receive({ data: { type: 'approval-mode', enabled: true, all: true } });
  assert.equal(elements.get('auto-approve-all').checked, true);
  elements.get('auto-approve-all').checked = false;
  elements.get('auto-approve-all').listeners.change();
  assert.equal(sent.at(-1).type, 'auto-approve-all');
  assert.equal(sent.at(-1).enabled, false);
  assert.equal(elements.get('auto-approve-all').disabled, true);
  receive({ data: { type: 'pool-mode', enabled: true } });
  assert.equal(elements.get('assistant-pool').checked, true);
  elements.get('assistant-pool').checked = false;
  elements.get('assistant-pool').listeners.change();
  assert.equal(sent.at(-1).type, 'assistant-pool');
  assert.equal(sent.at(-1).enabled, false);
  assert.equal(elements.get('assistant-pool').disabled, true);
  assert.equal(elements.get('workspace-tools').checked, true);
  elements.get('workspace-tools').checked = false;
  elements.get('workspace-tools').listeners.change();
  assert.equal(sent.at(-1).type, 'workspace-mode');
  assert.equal(sent.at(-1).enabled, false);

  const input = elements.get('prompt');
  let prevented = false;
  const keydown = event => input.listeners.keydown({ preventDefault: () => { prevented = true; }, ...event });
  input.value = 'Shortcut message';
  const before = sent.length;
  keydown({ key: 'Enter', ctrlKey: false, isComposing: false });
  assert.equal(prevented, false);
  assert.equal(sent.length, before);
  keydown({ key: 'Enter', ctrlKey: true, isComposing: true });
  assert.equal(prevented, false);
  assert.equal(sent.length, before);
  keydown({ key: 'Enter', ctrlKey: true, isComposing: false });
  assert.equal(prevented, true);
  assert.equal(sent.at(-1).type, 'send');
  assert.equal(sent.at(-1).content, 'Shortcut message');
  assert.equal(input.value, '');
  receive({ data: { type: 'busy', value: true } });
  input.value = 'Next message';
  const whileBusy = sent.length;
  keydown({ key: 'Enter', ctrlKey: true, isComposing: false });
  assert.equal(sent.length, whileBusy);
  assert.equal(input.value, 'Next message');
  receive({ data: { type: 'busy', value: false } });
  keydown({ key: 'Enter', ctrlKey: true, isComposing: false });
  assert.equal(sent.at(-1).content, 'Next message');
});

test('chat posts to the OpenAI route and delivers the response to the webview', async t => {
  const requests = [];
  const server = http.createServer((request, response) => {
    let body = '';
    request.setEncoding('utf8');
    request.on('data', chunk => { body += chunk; });
    request.on('end', () => {
      requests.push({ path: request.url, headers: request.headers, body: JSON.parse(body) });
      response.setHeader('Content-Type', 'application/json');
      response.end(JSON.stringify({
        choices: [{ message: { role: 'assistant', content: 'Hello from Harold' } }]
      }));
    });
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => server.close(resolve)));
  const origin = `http://127.0.0.1:${server.address().port}`;
  for (const baseUrl of [origin, `${origin}/v1`, `${origin}/v1/chat/completions`]) {
    const harness = createHarness(baseUrl);
    const reply = waitForPost(harness, 'assistant');
    harness.send({ type: 'send', content: 'Hello' });
    assert.equal((await reply).content, 'Hello from Harold');
    assert.equal(harness.errors.length, 0);
  }
  for (const request of requests) {
    assert.equal(request.path, '/v1/chat/completions');
    assert.equal(request.headers.authorization, 'Bearer test-key-not-a-real-secret');
    assert.equal(request.body.model, 'harold');
    assert.deepEqual(request.body.messages, [{ role: 'user', content: 'Hello' }]);
  }
});


function workspaceFixture(approve = true) {
  class FileSystemError extends Error { constructor(code) { super(code); this.code = code; } }
  const uri = value => ({ path: value, toString: () => `file:${value}` });
  const files = new Map(), writes = [], diffs = [], notices = [], terminals = [];
  const terminalEvents = new EventEmitter();
  const FileType = { File: 1, Directory: 2, SymbolicLink: 64 };
  const missing = () => { throw new FileSystemError('FileNotFound'); };
  let preview = 0;
  return { files, writes, diffs, notices, terminals,
    waitForTerminal: () => new Promise(resolve => terminalEvents.once('created', resolve)),
    overrides: {
    FileSystemError, FileType,
    EventEmitter: class {
      constructor() { this.listeners = []; this.event = listener => { this.listeners.push(listener); return { dispose() {} }; }; }
      fire(value) { for (const listener of this.listeners) listener(value); }
      dispose() { this.listeners = []; }
    },
    Uri: { joinPath: (root, ...parts) => uri(path.posix.join(root.path, ...parts)) },
    workspace: {
      isTrusted: true, workspaceFolders: [{ name: 'test', uri: uri('/workspace') }], textDocuments: [],
      asRelativePath: value => value.path.replace('/workspace/', ''),
      fs: {
        stat: async value => value.path === '/workspace' ? { type: FileType.Directory }
          : value.path === '/workspace/linked' ? { type: FileType.Directory | FileType.SymbolicLink }
          : files.has(value.path) ? { type: FileType.File } : missing(),
        readFile: async value => files.has(value.path) ? Buffer.from(files.get(value.path)) : missing(),
        readDirectory: async () => [['hello.py', FileType.File], ['.env', FileType.File], ['linked', FileType.SymbolicLink | FileType.Directory]],
        writeFile: async (value, content) => { writes.push(value.path); files.set(value.path, content.toString()); }
      },
      openTextDocument: async value => ({ uri: uri(`/preview/${++preview}`), languageId: value.language, getText: () => value.content })
    },
    window: {
      showInformationMessage: async message => { notices.push('POPUP: ' + message); },
      createTerminal: ({ name, pty }) => {
        assert.equal(name, 'Harold Approvals');
        const terminal = { pty, output: '', show: () => {
          pty.onDidWrite(text => { terminal.output += text; notices.push(text); });
          pty.open();
          terminalEvents.emit('created', terminal);
          if (approve !== null) queueMicrotask(() => pty.handleInput(approve ? 'y\r' : 'n\r'));
        }, dispose: () => pty.close() };
        terminals.push(terminal);
        return terminal;
      }
    },
    commands: { executeCommand: async (...args) => diffs.push(args) },
    extensions: { getExtension: () => undefined }
  } };
}

async function toolServer(t, answer) {
  const requests = [];
  const server = http.createServer((request, response) => {
    let body = '';
    request.setEncoding('utf8');
    request.on('data', chunk => { body += chunk; });
    request.on('end', () => {
      const payload = JSON.parse(body); requests.push(payload);
      response.setHeader('Content-Type', 'application/json');
      response.end(JSON.stringify({ choices: [{ message: answer(payload, requests.length) }] }));
    });
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => server.close(resolve)));
  return { requests, baseUrl: `http://127.0.0.1:${server.address().port}` };
}

function toolCall(name, args, id = 'call-test') {
  return { role: 'assistant', content: null, tool_calls: [{ id, type: 'function', function: { name, arguments: JSON.stringify(args) } }] };
}

test('coding chat executes an approved file proposal and forwards the linked result with a ten-minute timeout', async t => {
  const fixture = workspaceFixture();
  const code = 'def greet(name):\n    return f"Hello, {name}!"\n';
  const server = await toolServer(t, (payload, step) => step === 1
    ? toolCall('propose_edit', { path: 'hello.py', content: code }) : { role: 'assistant', content: 'Created hello.py.' });
  const timeouts = [], request = http.request;
  t.mock.method(http, 'request', (url, options, callback) => { timeouts.push(options.timeout); return request.call(http, url, options, callback); });
  const harness = createHarness(server.baseUrl, fixture.overrides), reply = waitForPost(harness, 'assistant');
  harness.send({ type: 'send', content: 'Write a Python file hello.py.' });
  assert.equal((await reply).content, 'Created hello.py.');
  assert.deepEqual(fixture.writes, ['/workspace/hello.py']);
  assert.equal(fixture.files.get('/workspace/hello.py'), code);
  assert.equal(fixture.diffs[0][0], 'vscode.diff');
  assert.ok(fixture.notices.some(message => message.includes('Create hello.py')));
  assert.deepEqual(server.requests[0].tools.map(tool => tool.function.name), ['list_files', 'read_file', 'propose_edit']);
  assert.equal(server.requests[0].stream, false);
  assert.equal(server.requests[0].tool_choice, 'required');
  assert.equal(server.requests[1].tool_choice, 'auto');
  const result = server.requests[1].messages.at(-1);
  assert.equal(result.role, 'tool'); assert.equal(result.tool_call_id, 'call-test');
  assert.deepEqual(JSON.parse(result.content), { status: 'applied', path: 'hello.py' });
  assert.ok(timeouts.length >= 2 && timeouts.every(timeout => timeout >= 600_000));
  assert.deepEqual(harness.errors, []);
});

test('Create File command requests and applies a workspace proposal rather than chat-only code', async t => {
  const fixture = workspaceFixture();
  fixture.overrides.window.showInputBox = async () => 'A hello world file';
  const server = await toolServer(t, (payload, step) => step === 1
    ? toolCall('propose_edit', { path: 'hello.py', content: 'print("Hello")\n' })
    : { role: 'assistant', content: 'Created hello.py.' });
  const harness = createHarness(server.baseUrl, fixture.overrides);
  await harness.commands.get('harold.createFile')();
  assert.deepEqual(fixture.writes, ['/workspace/hello.py']);
  assert.ok(server.requests[0].messages.at(-1).content.includes('Use propose_edit'));
  assert.deepEqual(harness.errors, []);
});

test('coding mode continues across follow-ups until explicitly disabled', async t => {
  const fixture = workspaceFixture();
  const server = await toolServer(t, payload => {
    if (!payload.tools) return { role: 'assistant', content: 'Ordinary chat.' };
    if (payload.messages.at(-1).role === 'tool') return { role: 'assistant', content: 'Done.' };
    return toolCall('propose_edit', { path: 'hello.py', content: 'print("Hello")\n' });
  });
  const harness = createHarness(server.baseUrl, fixture.overrides);
  let reply = waitForPost(harness, 'assistant');
  harness.send({ type: 'send', content: 'Write hello.py.' });
  await reply;
  await new Promise(resolve => setImmediate(resolve));
  const firstFollowUp = server.requests.length;
  reply = waitForPost(harness, 'assistant');
  harness.send({ type: 'send', content: 'Now add a greeting.' });
  await reply;
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(server.requests[firstFollowUp].tools, 'Follow-ups must not fall back to ordinary chat');
  harness.send({ type: 'workspace-mode', enabled: false });
  reply = waitForPost(harness, 'assistant');
  harness.send({ type: 'send', content: 'Thank you.' });
  assert.equal((await reply).content, 'Ordinary chat.');
  assert.equal(server.requests.at(-1).tools, undefined);
});

test('Google tool-call signatures survive an approved edit and its follow-up', async t => {
  const fixture = workspaceFixture();
  const extra_content = { google: { thought_signature: 'test-required-signature' } };
  const server = await toolServer(t, (payload, step) => {
    if (step === 1) {
      const message = toolCall('propose_edit', { path: 'hello.py', content: 'print("Hello")\n' });
      message.tool_calls[0].extra_content = extra_content;
      return message;
    }
    return { role: 'assistant', content: 'Created hello.py.' };
  });
  const harness = createHarness(server.baseUrl, fixture.overrides);
  const reply = waitForPost(harness, 'assistant');
  harness.send({ type: 'send', content: 'Write hello.py.' });
  await reply;
  assert.deepEqual(server.requests[1].messages.at(-2).tool_calls[0].extra_content, extra_content);
  assert.deepEqual(fixture.writes, ['/workspace/hello.py']);
});

test('declining a diff leaves files untouched and returns declined rather than success', async t => {
  const fixture = workspaceFixture(false);
  const server = await toolServer(t, (payload, step) => step === 1
    ? toolCall('propose_edit', { path: 'hello.py', content: 'print("hello")' }) : { role: 'assistant', content: 'No file written.' });
  const harness = createHarness(server.baseUrl, fixture.overrides), reply = waitForPost(harness, 'assistant');
  harness.send({ type: 'send', content: 'Please help.', useWorkspaceTools: true });
  assert.equal((await reply).content, 'No file written.');
  assert.equal(fixture.writes.length, 0);
  assert.equal(JSON.parse(server.requests[1].messages.at(-1).content).status, 'declined');
});

test('unsafe tool paths fail explicitly with no file write or conversational fallback', async t => {
  for (const target of ['../outside.py', '/outside.py', '.env', 'linked/escape.py']) {
    const fixture = workspaceFixture();
    const server = await toolServer(t, () => toolCall('propose_edit', { path: target, content: 'print("hello")' }));
    const harness = createHarness(server.baseUrl, fixture.overrides), error = waitForPost(harness, 'error');
    harness.send({ type: 'send', content: 'Write a Python file.' });
    assert.match((await error).content, /relative path|credential|symbolic-link/);
    assert.equal(fixture.writes.length, 0); assert.equal(server.requests.length, 1); assert.equal(harness.errors.length, 1);
  }
});

test('Harold calls the local AI Bridge pool with approved active-file context', async t => {
  const fixture = workspaceFixture(); fixture.files.set('/workspace/hello.py', 'print("hello")');
  const poolCalls = [];
  const activeFile = { path: 'hello.py', content: 'print("hello")', languageId: 'python',
    uri: { scheme: 'file', path: '/workspace/hello.py', toString: () => 'file:/workspace/hello.py' },
    getText: () => 'print("hello")' };
  const poolApi = { queryPoolForHarold: async (prompt, context) => {
    poolCalls.push({ prompt, context });
    return [{ provider: 'g4f', content: 'This prints hello.' }];
  } };
  const server = await toolServer(t, (_payload, step) => step === 1
    ? toolCall('query_assistant_pool', { prompt: 'Review this code for bugs.' }, 'pool-id')
    : { role: 'assistant', content: 'The pool says it prints hello.' });
  const harness = createHarness(server.baseUrl, {
    ...fixture.overrides,
    workspace: { ...fixture.overrides.workspace, asRelativePath: value => value.path.replace('/workspace/', '') },
    window: { ...fixture.overrides.window, activeTextEditor: { document: activeFile } },
    extensions: { getExtension: id => {
      assert.equal(id, 'moon.ai-bridge-extension');
      return { isActive: true, exports: poolApi };
    } }
  }, { 'harold.assistantPoolEnabled': true });
  const reply = waitForPost(harness, 'assistant');
  harness.send({ type: 'send', content: 'Ask the AI Bridge pool to review this open file.' });
  assert.equal((await reply).content, 'The pool says it prints hello.');
  assert.equal(poolCalls.length, 1);
  assert.equal(poolCalls[0].prompt, 'Review this code for bugs.');
  assert.equal(poolCalls[0].context.activeFile.path, 'hello.py');
  assert.equal(poolCalls[0].context.activeFile.content, 'print("hello")');
  assert.equal(poolCalls[0].context.activeFile.language, 'python');
  assert.equal(server.requests[0].tools.some(tool => tool.function.name === 'query_assistant_pool'), true);
  assert.deepEqual(JSON.parse(server.requests[1].messages.at(-1).content), {
    status: 'completed', responses: [{ provider: 'g4f', content: 'This prints hello.' }]
  });
  assert.ok(fixture.notices.some(message => message.includes('Harold is excluded')));
});

test('declining an assistant-pool query prevents all calls to AI Bridge', async t => {
  const fixture = workspaceFixture(false);
  let poolCalls = 0;
  const server = await toolServer(t, (_payload, step) => step === 1
    ? toolCall('query_assistant_pool', { prompt: 'Review the code.' })
    : { role: 'assistant', content: 'The pool query was declined.' });
  const harness = createHarness(server.baseUrl, {
    ...fixture.overrides,
    window: { ...fixture.overrides.window, showInformationMessage: async () => undefined },
    extensions: { getExtension: () => ({ isActive: true, exports: { queryPoolForHarold: async () => { poolCalls++; return []; } } }) }
  }, { 'harold.assistantPoolEnabled': true });
  const reply = waitForPost(harness, 'assistant');
  harness.send({ type: 'send', content: 'Use AI Bridge to check this.' });
  assert.equal((await reply).content, 'The pool query was declined.');
  assert.equal(poolCalls, 0);
  assert.equal(JSON.parse(server.requests[1].messages.at(-1).content).status, 'declined');
});

test('auto-approved reads stay read-only and edits still require approval', async t => {
  const fixture = workspaceFixture(false); fixture.files.set('/workspace/hello.py', 'print("hello")');
  const server = await toolServer(t, (_payload, step) => step === 1
    ? toolCall('read_file', { path: 'hello.py' }, 'read-id')
    : step === 2 ? toolCall('propose_edit', { path: 'hello.py', content: 'print("changed")' }, 'edit-id')
      : { role: 'assistant', content: 'The edit was declined.' });
  const harness = createHarness(server.baseUrl, fixture.overrides, { 'harold.autoApproveWorkspaceReads': true });
  const reply = waitForPost(harness, 'assistant');
  harness.send({ type: 'send', content: 'Read this file and change it.', useWorkspaceTools: true });
  assert.equal((await reply).content, 'The edit was declined.');
  assert.equal(server.requests[1].messages.at(-1).content, 'print("hello")');
  assert.equal(JSON.parse(server.requests[2].messages.at(-1).content).status, 'declined');
  assert.deepEqual(fixture.writes, []);
  assert.equal(fixture.diffs.length, 1);
  assert.ok(!fixture.notices.some(message => message.startsWith('Allow Harold to read')));
  assert.deepEqual(server.requests[0].tools.map(tool => tool.function.name), ['list_files', 'read_file', 'propose_edit']);
});

test('missing workspace files are reported to Harold so he can recover', async t => {
  for (const kind of ['FileNotFound', 'ENOENT']) {
    const fixture = workspaceFixture();
    fixture.files.set('/workspace/hello.py', 'labor rates');
    if (kind === 'ENOENT') {
      const originalStat = fixture.overrides.workspace.fs.stat;
      fixture.overrides.workspace.fs.stat = async value => {
        if (value.path.endsWith('/}}{')) { const error = new Error('private absolute path'); error.code = 'ENOENT'; throw error; }
        return originalStat(value);
      };
    }
    const server = await toolServer(t, (_payload, step) => step === 1
      ? toolCall('read_file', {path: '}}{'}, 'missing-id')
      : step === 2 ? toolCall('read_file', {path: 'hello.py'}, 'read-id')
        : {role: 'assistant', content: 'Labor rates found.'});
    const harness = createHarness(server.baseUrl, fixture.overrides), reply = waitForPost(harness, 'assistant');
    harness.send({type: 'send', content: 'Labor rates', useWorkspaceTools: true});
    assert.equal((await reply).content, 'Labor rates found.');
    const failed = server.requests[1].messages.at(-1);
    assert.equal(failed.tool_call_id, 'missing-id');
    assert.equal(JSON.parse(failed.content).status, 'error');
    assert.match(JSON.parse(failed.content).error, /not found/i);
    assert.ok(!failed.content.includes('/workspace'));
    assert.equal(server.requests[2].messages.at(-1).content, 'labor rates');
    assert.ok(harness.errors.length === 0);
  }
});

test('read permission errors remain explicit and are not converted into missing-file results', async t => {
  const fixture = workspaceFixture();
  const originalStat = fixture.overrides.workspace.fs.stat;
  fixture.overrides.workspace.fs.stat = async value => {
    if (value.path.endsWith('/protected.py')) { const error = new Error('Access denied'); error.code = 'EACCES'; throw error; }
    return originalStat(value);
  };
  const server = await toolServer(t, () => toolCall('read_file', {path: 'protected.py'}));
  const harness = createHarness(server.baseUrl, fixture.overrides), error = waitForPost(harness, 'error');
  harness.send({type: 'send', content: 'Read protected.py', useWorkspaceTools: true});
  assert.match((await error).content, /Access denied/);
  assert.equal(server.requests.length, 1);
});

test('list/read tool results preserve IDs, filter secret paths, and require permission to share contents', async t => {
  const fixture = workspaceFixture(); fixture.files.set('/workspace/hello.py', 'print("hello")');
  const server = await toolServer(t, (payload, step) => step === 1 ? toolCall('list_files', { path: '.' }, 'list-id')
    : step === 2 ? toolCall('read_file', { path: 'hello.py' }, 'read-id') : { role: 'assistant', content: 'It prints hello.' });
  const harness = createHarness(server.baseUrl, fixture.overrides), reply = waitForPost(harness, 'assistant');
  harness.send({ type: 'send', content: 'Inspect my project.', useWorkspaceTools: true });
  assert.equal((await reply).content, 'It prints hello.');
  assert.deepEqual(JSON.parse(server.requests[1].messages.at(-1).content), [{ name: 'hello.py', type: 'file' }]);
  assert.equal(server.requests[1].messages.at(-1).tool_call_id, 'list-id');
  assert.equal(server.requests[2].messages.at(-1).tool_call_id, 'read-id');
  assert.equal(server.requests[2].messages.at(-1).content, 'print("hello")');
  assert.ok(fixture.notices.some(message => message.includes('configured AI providers')));
  assert.equal(fixture.writes.length, 0);
});


test('explaining code without a workspace remains ordinary own-model chat', async t => {
  const server = await toolServer(t, () => ({ role: 'assistant', content: 'I can explain the code.' }));
  const harness = createHarness(server.baseUrl), reply = waitForPost(harness, 'assistant');
  harness.send({ type: 'send', content: 'Explain what this code means.' });
  assert.equal((await reply).content, 'I can explain the code.');
  assert.equal(server.requests[0].tools, undefined);
  assert.deepEqual(harness.errors, []);
});


test('no active editor does not block a message when Include active file was left selected', async t => {
  const server = await toolServer(t, () => ({ role: 'assistant', content: 'I can see your message.' }));
  const harness = createHarness(server.baseUrl);
  const notices = [];
  harness.posts.on('message', message => { if (message.type === 'notice' || message.type === 'file-unavailable') notices.push(message); });
  const reply = waitForPost(harness, 'assistant');
  await harness.send({ type: 'send', content: 'Can you see?', includeActiveFile: true });
  assert.equal((await reply).content, 'I can see your message.');
  assert.deepEqual(server.requests[0].messages, [{ role: 'user', content: 'Can you see?' }]);
  assert.ok(notices.some(message => message.type === 'notice' && message.content.includes('No active file')));
  assert.ok(notices.some(message => message.type === 'file-unavailable'));
  assert.deepEqual(harness.errors, []);
});

function poolFixture(contents) {
  const fixture = workspaceFixture();
  for (const [name, content] of Object.entries(contents)) fixture.files.set('/workspace/.ai-pool/' + name, content);
  const dirs = new Map([
    ['/workspace/.ai-pool', Object.keys(contents).filter(name => !name.includes('/')).map(name => [name, 1])],
    ['/workspace/.ai-pool/nested', Object.keys(contents).filter(name => name.startsWith('nested/')).map(name => [name.slice(7), 1])]
  ]);
  if (Object.keys(contents).some(name => name.startsWith('nested/'))) dirs.get('/workspace/.ai-pool').push(['nested', 2]);
  const original = fixture.overrides.workspace.fs;
  fixture.overrides.workspace.fs = {
    ...original,
    stat: async uri => dirs.has(uri.path) ? { type: 2 } : original.stat(uri),
    readDirectory: async uri => dirs.get(uri.path) || []
  };
  return fixture;
}

test('pool bridge reads every Markdown/text source, excludes master, and writes through approved native tools without an editor', async t => {
  const fixture = poolFixture({ 'one.md': 'Goal: create hello.py.', 'two.txt': 'Use no extra dependencies.',
    'nested/three.markdown': 'Return Hello, World!.', 'cleaned-master.md': 'OLD MASTER MUST NOT BE SHARED' });
  const server = await toolServer(t, (payload, step) => step === 1
    ? toolCall('propose_edit', { path: '.ai-pool/cleaned-master.md', content: '# Goal\nCreate hello.py with no dependencies.\n' })
    : step === 2 ? toolCall('propose_edit', { path: 'hello.py', content: 'def hello_world():\n    return "Hello, World!"\n' })
    : { role: 'assistant', content: 'Created the specification and hello.py; execution is not verified.' });
  const harness = createHarness(server.baseUrl, fixture.overrides);
  const reply = waitForPost(harness, 'assistant');
  await harness.commands.get('harold.poolAndBuild')();
  assert.match((await reply).content, /execution is not verified/);
  const prompt = server.requests[0].messages.find(message => message.role === 'user').content;
  for (const source of ['Goal: create hello.py.', 'Use no extra dependencies.', 'Return Hello, World!.']) assert.ok(prompt.includes(source));
  assert.ok(prompt.includes('SHA-256 (UTF-8 content):'));
  assert.ok(!prompt.includes('OLD MASTER MUST NOT BE SHARED'));
  assert.deepEqual(fixture.writes, ['/workspace/.ai-pool/cleaned-master.md', '/workspace/hello.py']);
  assert.ok(fixture.notices.some(message => message.includes('Share all 3 AI-pool source files')));
  assert.equal(server.requests[0].tool_choice, 'required');
  assert.deepEqual(harness.errors, []);
});

test('empty and oversized pools fail explicitly before any provider call or write', async t => {
  const server = await toolServer(t, () => ({ role: 'assistant', content: 'must not be called' }));
  for (const [contents, message] of [
    [{ 'cleaned-master.md': 'Only the old master exists.' }, /No AI-pool source files/],
    [{ 'huge.md': 'x'.repeat(100001) }, /100,000 characters/]
  ]) {
    const fixture = poolFixture(contents);
    const harness = createHarness(server.baseUrl, fixture.overrides);
    await harness.commands.get('harold.poolAndBuild')();
    assert.equal(harness.errors.length, 1);
    assert.match(harness.errors[0], message);
    assert.equal(fixture.writes.length, 0);
  }
  assert.equal(server.requests.length, 0);
});


test('pool bridge refuses deliverable edits before an approved master', async t => {
  const fixture = poolFixture({ 'goal.md': 'Build hello.py after the master.' });
  const server = await toolServer(t, () => toolCall('propose_edit', { path: 'hello.py', content: 'print("hello")' }));
  const harness = createHarness(server.baseUrl, fixture.overrides);
  await harness.commands.get('harold.poolAndBuild')();
  assert.equal(fixture.writes.length, 0);
  assert.equal(harness.errors.length, 1);
  assert.match(harness.errors[0], /cleaned-master.md first/);
});

test('automatic workspace actions read and edit without popups and count only applied edits', async t => {
  const fixture = workspaceFixture(false);
  fixture.files.set('/workspace/hello.py', 'old');
  const server = await toolServer(t, (_payload, step) => step === 1
    ? toolCall('read_file', { path: 'hello.py' })
    : step === 2 ? toolCall('propose_edit', { path: 'hello.py', content: 'new' })
      : step === 3 ? toolCall('propose_edit', { path: 'hello.py', content: 'new' })
        : { role: 'assistant', content: 'Done.' });
  const harness = createHarness(server.baseUrl, fixture.overrides, { 'harold.autoApproveWorkspaceActions': true });
  const counts = [];
  harness.posts.on('message', message => { if (message.type === 'edit-count') counts.push(message.count); });
  const reply = waitForPost(harness, 'assistant');
  harness.send({ type: 'send', content: 'Edit this file.', useWorkspaceTools: true });
  await reply;
  assert.equal(server.requests[1].messages.at(-1).content, 'old');
  assert.equal(JSON.parse(server.requests[2].messages.at(-1).content).status, 'applied');
  assert.equal(JSON.parse(server.requests[3].messages.at(-1).content).status, 'unchanged');
  assert.deepEqual(fixture.writes, ['/workspace/hello.py']);
  assert.deepEqual(fixture.notices, []);
  assert.deepEqual(fixture.diffs, []);
  assert.deepEqual(counts, [0, 1]);
  harness.send({ type: 'ready' });
  assert.equal(counts.at(-1), 1);
});

test('automatic edits never overwrite unsaved open documents', async t => {
  const fixture = workspaceFixture(false);
  fixture.files.set('/workspace/hello.py', 'saved');
  fixture.overrides.workspace.textDocuments.push({
    uri: { path: '/workspace/hello.py', scheme: 'file', toString: () => 'file:/workspace/hello.py' },
    isDirty: true, version: 1, getText: () => 'unsaved'
  });
  const server = await toolServer(t, () => toolCall('propose_edit', { path: 'hello.py', content: 'new' }));
  const harness = createHarness(server.baseUrl, fixture.overrides, { 'harold.autoApproveWorkspaceActions': true });
  const error = waitForPost(harness, 'error');
  harness.send({ type: 'send', content: 'Edit hello.py.', useWorkspaceTools: true });
  assert.match((await error).content, /Save or close the modified file/);
  assert.equal(fixture.files.get('/workspace/hello.py'), 'saved');
  assert.deepEqual(fixture.writes, []);
});

test('automatic approval preserves workspace boundaries and pool sharing consent', async t => {
  const fixture = workspaceFixture(false);
  const server = await toolServer(t, (_payload, step) => step === 1
    ? toolCall('query_assistant_pool', { prompt: 'Get a second opinion' })
    : toolCall('propose_edit', { path: '../outside.py', content: 'unsafe' }));
  const harness = createHarness(server.baseUrl, fixture.overrides, { 'harold.autoApproveWorkspaceActions': true, 'harold.assistantPoolEnabled': true });
  const error = waitForPost(harness, 'error');
  harness.send({ type: 'send', content: 'Ask the pool and edit the file.', useWorkspaceTools: true });
  assert.match((await error).content, /relative path/);
  assert.equal(JSON.parse(server.requests[1].messages.at(-1).content).status, 'declined');
  assert.deepEqual(fixture.writes, []);
});

test('coding tasks can continue past eight tool rounds', async t => {
  const fixture = workspaceFixture();
  const server = await toolServer(t, (_payload, step) => step <= 10
    ? toolCall('list_files', { path: '.' }, 'list-' + step)
    : { role: 'assistant', content: 'Finished after inspection.' });
  const harness = createHarness(server.baseUrl, fixture.overrides, { 'harold.autoApproveWorkspaceActions': true });
  const reply = waitForPost(harness, 'assistant');
  harness.send({ type: 'send', content: 'Inspect the workspace.', useWorkspaceTools: true });
  assert.equal((await reply).content, 'Finished after inspection.');
  assert.equal(server.requests.length, 11);
});

test('automatic edits apply and save a clean open document without a diff', async t => {
  const fixture = workspaceFixture(false);
  let content = 'old', saves = 0;
  const uri = { path: '/workspace/hello.py', scheme: 'file', toString: () => 'file:/workspace/hello.py' };
  const document = { uri, isDirty: false, version: 1, languageId: 'python', getText: () => content,
    positionAt: offset => offset, save: async () => { saves++; return true; } };
  fixture.files.set('/workspace/hello.py', 'old');
  fixture.overrides.workspace.textDocuments.push(document);
  fixture.overrides.WorkspaceEdit = class { replace(_uri, _range, text) { this.content = text; } };
  fixture.overrides.Range = class { constructor(start, end) { this.start = start; this.end = end; } };
  fixture.overrides.workspace.applyEdit = async edit => { content = edit.content; return true; };
  const server = await toolServer(t, (_payload, step) => step === 1
    ? toolCall('propose_edit', { path: 'hello.py', content: 'new' }) : { role: 'assistant', content: 'Done.' });
  const harness = createHarness(server.baseUrl, fixture.overrides, { 'harold.autoApproveWorkspaceActions': true });
  const reply = waitForPost(harness, 'assistant');
  harness.send({ type: 'send', content: 'Edit hello.py.', useWorkspaceTools: true });
  await reply;
  assert.equal(content, 'new'); assert.equal(saves, 1);
  assert.deepEqual(fixture.diffs, []); assert.deepEqual(fixture.notices, []);
  assert.equal(JSON.parse(server.requests[1].messages.at(-1).content).status, 'applied');
});

test('32 tool rounds permit a final answer but no extra tool execution', async t => {
  for (const finalAnswer of [true, false]) {
    const fixture = workspaceFixture();
    const server = await toolServer(t, (_payload, step) => step <= 32 || !finalAnswer
      ? toolCall('list_files', { path: '.' }, 'list-' + step)
      : { role: 'assistant', content: 'Finished.' });
    const harness = createHarness(server.baseUrl, fixture.overrides);
    const result = waitForPost(harness, finalAnswer ? 'assistant' : 'error');
    harness.send({ type: 'send', content: 'Inspect the workspace.', useWorkspaceTools: true });
    const message = await result;
    if (finalAnswer) assert.equal(message.content, 'Finished.');
    else assert.match(message.content, /32-round workspace-tool limit/);
    assert.equal(server.requests.length, 33);
  }
});

test('terminal approval accepts valid answers and rejects invalid input without popups', async t => {
  const fixture = workspaceFixture(null);
  const server = await toolServer(t, (_payload, step) => step === 1
    ? toolCall('propose_edit', { path: 'hello.py', content: 'print("hello")' })
    : { role: 'assistant', content: 'Done.' });
  const harness = createHarness(server.baseUrl, fixture.overrides);
  const terminalReady = fixture.waitForTerminal(), reply = waitForPost(harness, 'assistant');
  harness.send({ type: 'send', content: 'Create a file.', useWorkspaceTools: true });
  const terminal = await terminalReady;
  assert.match(terminal.output, /Create hello.py/);
  assert.match(terminal.output, /Approve\? \[y\/N\]/);
  assert.deepEqual(fixture.writes, []);
  terminal.pty.handleInput('maybe\r');
  assert.match(terminal.output, /Please enter y or n/);
  assert.deepEqual(fixture.writes, []);
  terminal.pty.handleInput('YES\r');
  await reply;
  assert.deepEqual(fixture.writes, ['/workspace/hello.py']);
  assert.ok(!fixture.notices.some(text => text.startsWith('POPUP:')));
});

test('closing the approval terminal declines a read without sharing file contents', async t => {
  const fixture = workspaceFixture(null);
  fixture.files.set('/workspace/hello.py', 'private contents');
  const server = await toolServer(t, (_payload, step) => step === 1
    ? toolCall('read_file', { path: 'hello.py' }) : { role: 'assistant', content: 'Read declined.' });
  const harness = createHarness(server.baseUrl, fixture.overrides);
  const terminalReady = fixture.waitForTerminal(), reply = waitForPost(harness, 'assistant');
  harness.send({ type: 'send', content: 'Read this file.', useWorkspaceTools: true });
  const terminal = await terminalReady;
  assert.match(terminal.output, /may be sent to configured AI providers/);
  terminal.dispose();
  assert.equal((await reply).content, 'Read declined.');
  assert.equal(JSON.parse(server.requests[1].messages.at(-1).content).status, 'declined');
  assert.ok(!JSON.stringify(server.requests[1]).includes('private contents'));
  assert.ok(!fixture.notices.some(text => text.startsWith('POPUP:')));
});

test('reviewed terminal approval still refuses a file changed while waiting', async t => {
  const fixture = workspaceFixture(null);
  fixture.files.set('/workspace/hello.py', 'original');
  const server = await toolServer(t, () => toolCall('propose_edit', { path: 'hello.py', content: 'proposed' }));
  const harness = createHarness(server.baseUrl, fixture.overrides);
  const terminalReady = fixture.waitForTerminal(), error = waitForPost(harness, 'error');
  harness.send({ type: 'send', content: 'Edit hello.py.', useWorkspaceTools: true });
  const terminal = await terminalReady;
  fixture.files.set('/workspace/hello.py', 'changed by user');
  terminal.pty.handleInput('y\r');
  assert.match((await error).content, /changed while the diff was open/);
  assert.equal(fixture.files.get('/workspace/hello.py'), 'changed by user');
  assert.deepEqual(fixture.writes, []);
});

test('always approve persists, covers workspace and provider sharing, and can be disabled', async t => {
  const fixture = workspaceFixture(false);
  fixture.files.set('/workspace/hello.py', 'original');
  const poolCalls = [];
  fixture.overrides.extensions = { getExtension: () => ({ isActive: true, exports: {
    queryPoolForHarold: async prompt => { poolCalls.push(prompt); return [{ provider: 'test', content: 'ok' }]; }
  } }) };
  const settings = { 'harold.autoApproveWorkspaceActions': false, 'harold.assistantPoolEnabled': true };
  const server = await toolServer(t, (_payload, step) => step === 1
    ? toolCall('query_assistant_pool', { prompt: 'Review the file' })
    : step === 2 ? toolCall('read_file', { path: 'hello.py' })
    : step === 3 ? toolCall('propose_edit', { path: 'hello.py', content: 'updated' })
    : step === 5 ? toolCall('read_file', { path: 'hello.py' })
    : { role: 'assistant', content: 'Finished.' });
  const harness = createHarness(server.baseUrl, fixture.overrides, settings);
  let mode = waitForPost(harness, 'approval-mode');
  harness.send({ type: 'auto-approve-all', enabled: true });
  assert.equal((await mode).all, true);
  assert.equal(settings['harold.autoApproveAllActions'], true);
  const reply = waitForPost(harness, 'assistant');
  harness.send({ type: 'send', content: 'Inspect and edit this file.', useWorkspaceTools: true });
  await reply;
  assert.deepEqual(poolCalls, ['Review the file']);
  assert.equal(server.requests[2].messages.at(-1).content, 'original');
  assert.deepEqual(fixture.writes, ['/workspace/hello.py']);
  assert.deepEqual(fixture.terminals, []);
  assert.ok(!fixture.notices.some(text => text.startsWith('POPUP:')));

  const reopened = createHarness(server.baseUrl, fixture.overrides, settings);
  mode = waitForPost(reopened, 'approval-mode');
  reopened.send({ type: 'ready' });
  assert.equal((await mode).all, true);
  mode = waitForPost(reopened, 'approval-mode');
  reopened.send({ type: 'auto-approve-all', enabled: false });
  assert.equal((await mode).all, false);
  const secondReply = waitForPost(reopened, 'assistant');
  reopened.send({ type: 'send', content: 'Read this file.', useWorkspaceTools: true });
  await secondReply;
  assert.equal(fixture.terminals.length, 1);
  assert.equal(JSON.parse(server.requests[5].messages.at(-1).content).status, 'declined');
});

test('always approve covers direct save and pool build without confirmation', async t => {
  const fixture = poolFixture({ 'goal.md': 'Create a small file.' });
  fixture.overrides.window.showInputBox = async () => 'saved.py';
  const settings = { 'harold.autoApproveAllActions': true, 'harold.autoApproveWorkspaceActions': false };
  const server = await toolServer(t, (_payload, step) => step === 1
    ? toolCall('propose_edit', { path: '.ai-pool/cleaned-master.md', content: '# Goal' })
    : { role: 'assistant', content: 'Master created.' });
  const harness = createHarness(server.baseUrl, fixture.overrides, settings);
  const saved = waitForPost(harness, 'notice');
  harness.send({ type: 'save', code: 'print(1)', lang: 'python' });
  assert.equal((await saved).content, 'File save: applied');
  const reply = waitForPost(harness, 'assistant');
  await harness.commands.get('harold.poolAndBuild')();
  await reply;
  assert.deepEqual(fixture.writes, ['/workspace/saved.py', '/workspace/.ai-pool/cleaned-master.md']);
  assert.deepEqual(fixture.terminals, []);
  assert.ok(!fixture.notices.some(text => text.startsWith('POPUP:')));
  assert.equal(fixture.diffs.filter(args => args[0] === 'vscode.diff').length, 0);
});

test('always approve does not bypass secret path protection', async t => {
  const fixture = workspaceFixture(false);
  const server = await toolServer(t, () => toolCall('propose_edit', { path: '.env', content: 'unsafe' }));
  const harness = createHarness(server.baseUrl, fixture.overrides, { 'harold.autoApproveAllActions': true });
  const error = waitForPost(harness, 'error');
  harness.send({ type: 'send', content: 'Edit a file.', useWorkspaceTools: true });
  assert.match((await error).content, /credential|secret/);
  assert.deepEqual(fixture.writes, []);
  assert.deepEqual(fixture.terminals, []);
});

test('assistant pool toggle persists, hides the pool tool when off, and refuses pool calls', async t => {
  const fixture = workspaceFixture();
  let poolCalls = 0;
  fixture.overrides.extensions = { getExtension: () => ({ isActive: true, exports: {
    queryPoolForHarold: async () => { poolCalls++; return [{ provider: 'test', content: 'ok' }]; }
  } }) };
  const settings = { 'harold.autoApproveAllActions': true };
  const server = await toolServer(t, (_payload, step) => step === 1 || step === 3
    ? toolCall('query_assistant_pool', { prompt: 'Second opinion' })
    : { role: 'assistant', content: 'Done.' });
  const harness = createHarness(server.baseUrl, fixture.overrides, settings);
  let mode = waitForPost(harness, 'pool-mode');
  harness.send({ type: 'ready' });
  assert.equal((await mode).enabled, false);

  let reply = waitForPost(harness, 'assistant');
  harness.send({ type: 'send', content: 'Check this code.', useWorkspaceTools: true });
  await reply;
  assert.equal(server.requests[0].tools.some(tool => tool.function.name === 'query_assistant_pool'), false);
  assert.equal(JSON.parse(server.requests[1].messages.at(-1).content).status, 'disabled');
  assert.equal(poolCalls, 0);

  mode = waitForPost(harness, 'pool-mode');
  harness.send({ type: 'assistant-pool', enabled: true });
  assert.equal((await mode).enabled, true);
  assert.equal(settings['harold.assistantPoolEnabled'], true);
  reply = waitForPost(harness, 'assistant');
  harness.send({ type: 'send', content: 'Check this code again.', useWorkspaceTools: true });
  await reply;
  assert.equal(server.requests[2].tools.some(tool => tool.function.name === 'query_assistant_pool'), true);
  assert.equal(JSON.parse(server.requests[3].messages.at(-1).content).status, 'completed');
  assert.equal(poolCalls, 1);
});

function automaticResult() {
  return {
    source: 'server-api', synthesizer: 'test-synthesizer', response: 'Final synthesis',
    results: [
      { name: 'google', source: 'server-api', answer: 'Peer answer A' },
      { name: 'groq', source: 'server-api', answer: 'Peer answer B' },
      { name: 'openrouter', source: 'server-api', error: 'Provider failed' }
    ]
  };
}

test('/pool runs one automatic request and renders synthesis plus truthful source labels', async t => {
  const requests = [];
  const server = http.createServer((request, response) => {
    let body = '';
    request.on('data', chunk => { body += chunk; });
    request.on('end', () => {
      requests.push({ path: request.url, authorization: request.headers.authorization, payload: JSON.parse(body) });
      response.setHeader('Content-Type', 'application/json');
      response.end(JSON.stringify(automaticResult()));
    });
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => server.close(resolve)));
  const origin = `http://127.0.0.1:${server.address().port}`;
  for (const base of [origin, origin + '/v1', origin + '/v1/chat/completions']) {
    const harness = createHarness(base, {}, {'harold.assistantPoolEnabled': true, 'harold.autoApproveAllActions': true});
    const reply = waitForPost(harness, 'assistant');
    harness.send({type: 'send', content: '/pool Compare the approaches'});
    const result = await reply;
    assert.match(result.content, /Final synthesis/);
    assert.match(result.content, /not VS Code extension execution/);
    assert.match(result.content, /openrouter \(FAILED\)/);
    assert.equal(harness.errors.length, 0);
  }
  assert.equal(requests.length, 3);
  for (const request of requests) {
    assert.equal(request.path, '/api/extension/pool/query');
    assert.equal(request.authorization, 'Bearer test-key-not-a-real-secret');
    assert.deepEqual(request.payload, {prompt: 'Compare the approaches'});
  }
});

test('disabled or declined automatic pooling shares nothing', async t => {
  let requests = 0;
  t.mock.method(http, 'request', () => { requests++; throw new Error('No request should be sent'); });
  const disabled = createHarness('http://127.0.0.1:9');
  const error = waitForPost(disabled, 'error');
  disabled.send({type: 'send', content: '/pool Question'});
  assert.match((await error).content, /Enable the assistant pool/);
  const fixture = workspaceFixture(false);
  const declined = createHarness('http://127.0.0.1:9', fixture.overrides, {'harold.assistantPoolEnabled': true});
  const reply = waitForPost(declined, 'assistant');
  declined.send({type: 'send', content: '/pool Question'});
  assert.match((await reply).content, /declined/);
  assert.equal(requests, 0);
  assert.equal(fixture.terminals.length, 1);
});

test('query_consensus_pool tool uses automatic transport rather than the AI Bridge', async t => {
  const calls = [];
  const server = http.createServer((request, response) => {
    let body = '';
    request.on('data', chunk => { body += chunk; });
    request.on('end', () => {
      const data = JSON.parse(body);
      calls.push({path: request.url, data});
      response.setHeader('Content-Type', 'application/json');
      if (request.url === '/api/extension/pool/query') response.end(JSON.stringify(automaticResult()));
      else response.end(JSON.stringify({choices: [{message: calls.length === 1
        ? toolCall('query_consensus_pool', {prompt: 'Question'}, 'consensus-id')
        : {role: 'assistant', content: 'Used automatic consensus.'}}]}));
    });
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => server.close(resolve)));
  const fixture = workspaceFixture();
  const harness = createHarness(`http://127.0.0.1:${server.address().port}`, fixture.overrides,
    {'harold.assistantPoolEnabled': true, 'harold.autoApproveAllActions': true});
  const reply = waitForPost(harness, 'assistant');
  harness.send({type: 'send', content: 'Query consensus', useWorkspaceTools: true});
  assert.equal((await reply).content, 'Used automatic consensus.');
  assert.deepEqual(calls.map(call => call.path), ['/v1/chat/completions', '/api/extension/pool/query', '/v1/chat/completions']);
  assert.equal(calls[2].data.messages.at(-1).tool_call_id, 'consensus-id');
  assert.match(calls[2].data.messages.at(-1).content, /Final synthesis/);
  assert.deepEqual(fixture.writes, []);
});
