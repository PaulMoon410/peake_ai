const test = require("node:test");
const assert = require("node:assert/strict");
const {createSession, recordResult, submission} = require("./coordinator");

test("a common question retains source answers and explicit failures", () => {
  let session = createSession("Question", ["cline", "kilo", "codegeex"]);
  const original = session;
  session = recordResult(session, "cline", "Answer one");
  session = recordResult(session, "kilo", "Answer two");
  session = recordResult(session, "codegeex", "Not available", true);
  const payload = submission(session);
  assert.equal(payload.prompt, "Question");
  assert.equal(payload.session_id, original.session_id);
  assert.equal(original.results.length, 0);
  assert.equal(payload.results[2].error, "Not available");
  assert.equal(payload.results[0].source, "operator-submitted");
  assert.equal(Object.hasOwn(payload, "final"), false);
});

test("partial, duplicate, oversized and single-answer pools are rejected", () => {
  assert.throws(() => createSession("Q", ["cline"]), /two or three/);
  assert.throws(() => createSession("Q", ["cline", "cline"]), /unique/);
  assert.throws(() => createSession("x".repeat(4001), ["cline", "kilo"]), /4,000/);
  let session = createSession("x".repeat(4000), ["cline", "kilo"]);
  assert.throws(() => submission(session), /every selected/);
  assert.throws(() => recordResult(session, "unknown", "A"), /not in/);
  session = recordResult(session, "cline", "x".repeat(4000));
  assert.throws(() => recordResult(session, "cline", "Again"), /already/);
  session = recordResult(session, "kilo", "Failed", true);
  assert.throws(() => submission(session), /two completed/);
  assert.throws(() => recordResult({...session, final: {}}, "kilo", "A"), /unfinished/);
});
