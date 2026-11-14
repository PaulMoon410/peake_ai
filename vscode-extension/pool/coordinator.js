const crypto = require("node:crypto");
const CONNECTORS = {
  cline: {id: "saoudrizwan.claude-dev", command: "cline.focusChatInput"},
  kilo: {id: "kilocode.kilo-code", command: "kilo-code.new.focusChatInput"},
  codegeex: {id: "aminer.codegeex", command: "codegeex.chat.focus"},
};

function boundedText(text) {
  if (typeof text !== "string" || !text.trim() || text.length > 4000) {
    throw new Error("Text must contain 1 to 4,000 characters; nothing was truncated.");
  }
  return text;
}

function createSession(prompt, contributors) {
  boundedText(prompt);
  if (!Array.isArray(contributors) || contributors.length < 2 || contributors.length > 3
      || new Set(contributors).size !== contributors.length
      || contributors.some(name => !Object.hasOwn(CONNECTORS, name))) {
    throw new Error("Select two or three unique independent contributors.");
  }
  return {session_id: crypto.randomUUID(), prompt, contributors, results: [], final: null};
}

function recordResult(session, name, text, failed = false) {
  if (!session || session.final) throw new Error("Start an unfinished pool session first.");
  if (!session.contributors.includes(name)) throw new Error("Contributor is not in this session.");
  if (session.results.some(result => result.name === name)) throw new Error("This contributor already submitted a result.");
  boundedText(text);
  return {...session, results: [...session.results, {
    name, source: "operator-submitted", [failed ? "error" : "answer"]: text,
  }]};
}

function submission(session) {
  if (!session || session.final) throw new Error("Start an unfinished pool session first.");
  if (session.results.length !== session.contributors.length) {
    throw new Error("Submit an answer or mark a failure for every selected contributor.");
  }
  if (session.results.filter(result => result.answer).length < 2) {
    throw new Error("At least two completed answers are needed; failures are not votes.");
  }
  const {session_id, prompt, contributors, results} = session;
  return {session_id, prompt, contributors, results};
}

module.exports = {CONNECTORS, boundedText, createSession, recordResult, submission};
