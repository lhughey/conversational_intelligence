/**
 * Minimal consumer client — how career-identity-app would call this component.
 *
 * No dependencies: Node 18+ global fetch. Run against a server started with
 *   convint serve --port 8000
 *
 *   node client.mjs [baseUrl]
 *
 * Types: generate them from contracts/v1/*.schema.json rather than hand-writing
 * them, e.g.  npx json-schema-to-typescript contracts/v1/turn-request.schema.json
 */

const BASE = process.argv[2] ?? "http://127.0.0.1:8000";
const EXPECTED_MAJOR = "1";

/** Pin the major version. A mismatch is a hard failure, never a silent drift. */
async function assertContract() {
  const res = await fetch(`${BASE}/v1/contract`);
  if (!res.ok) throw new Error(`contract fetch failed: ${res.status}`);
  const { contract_version } = await res.json();
  const [major] = contract_version.split(".");
  if (major !== EXPECTED_MAJOR) {
    throw new Error(
      `contract major mismatch: server ${contract_version}, client expects ${EXPECTED_MAJOR}.x`,
    );
  }
  return contract_version;
}

async function decideTurn(request) {
  const res = await fetch(`${BASE}/v1/turn`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) throw new Error(`turn failed: ${res.status} ${await res.text()}`);
  return res.json();
}

/**
 * The consumer owns the state. The component is stateless: pass the whole
 * thing every call and persist `state_delta` afterwards.
 */
const plan = {
  plan_id: "your-canon",
  stages: [
    { stage_id: "early_life", required: true, completion_signal: "childhood_complete" },
    { stage_id: "career", required: true, completion_signal: "career_reflection_complete" },
  ],
  topics: [
    { topic_id: "childhood", stage: "early_life" },
    { topic_id: "role", stage: "career" },
  ],
  default_budget: { floor: 1, ceiling: 3 },
};

let state = {
  turns: [
    { role: "assistant", content: "What were you like as a kid?" },
    { role: "user", content: "I helped out at my parents' dry cleaner in Queens." },
  ],
  topics: [{ topic_id: "childhood", stage: "early_life" }],
  current_topic_id: "childhood",
  coverage: {},
  signal: "none",
  pattern_confirmed: false,
};

const version = await assertContract();
console.log(`contract ${version} OK`);

const response = await decideTurn({
  contract_version: version,
  plan,
  state,
  options: { generate_text: false, assess: "deterministic" },
});

const { action, sub_action, rule_fired } = response.decision;
const { specificity, ownership } = response.assessment;

console.log(`decision   : ${action} / ${sub_action}`);
console.log(`rule_fired : ${rule_fired}`);
console.log(`sufficiency: ${specificity} / ${ownership}`);
console.log(`readiness  : ${response.readiness.ready} ${JSON.stringify(response.readiness.missing)}`);

// Persist what the component tells you to persist, then loop.
state = { ...state, ...response.state_delta };
console.log(`followups  : ${state.topics[0].followups_used}`);

if (!rule_fired) {
  console.error("FAIL: decision was not attributable");
  process.exit(1);
}
console.log("OK");
