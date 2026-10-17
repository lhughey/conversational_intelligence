# Consumer client example

Proves the component is usable across the language boundary — a Node consumer
talking to the Python component over HTTP, sharing nothing but
`contracts/v1/*.schema.json`.

```bash
# terminal 1
convint serve --port 8000

# terminal 2
node client.mjs
```

Or let the test harness do both:

```bash
make test-e2e
```

## Notes for a real integration

- **Pin the major version.** `assertContract()` fails loudly on a mismatch
  rather than drifting.
- **Generate types, don't hand-write them:**
  `npx json-schema-to-typescript contracts/v1/turn-request.schema.json`
- **The consumer owns state.** The component is stateless; persist
  `state_delta` after each call and pass the whole state back next time.
- **`generate_text: false`** returns `message: null` and lets you write the
  words yourself — the escape hatch that keeps brand voice on your side.
- **`assess`** is `"server"` by default (the operator's configured assessor);
  `"deterministic"` forces the free regex assessor for that call, which is what
  this example sends. The client never names a model.
- **Check `diagnostics.degraded`.** A failed model call does not fail the turn:
  `message` / `artifact` come back null and `diagnostics.warnings` says why.
- MCP instead of HTTP: run `convint mcp` and call the `decide_turn` tool with
  the identical payload.
