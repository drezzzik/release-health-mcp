# Roadmap

Milestones 1–2 (scaffold plus read-only tools) are implemented in this repo. This file plans the rest.

## Milestone 3: Approval-gated rollout changes (about 2 weeks)

**Principle:** the agent can propose; only a human can approve. All limits are enforced in code, never in the prompt.

### New modules
```
src/release_health_mcp/
  actions/
    limits.py      # pure: validate(proposal, current_track, recommendation, thresholds) -> list[Violation]
    proposals.py   # create / load / expire proposals; one-time codes (stored hashed)
    executor.py    # the ONLY module that loads the release-permission key
    audit.py       # append-only JSONL audit log
  cli.py           # `release-health approve|reject|list-proposals|audit` (human-only entrypoint)
```

### Tools
| Tool | Behaviour |
|---|---|
| `propose_rollout_change(app, version_code, action, target_fraction?)` | `action` ∈ `expand`, `halt`, `resume`, `complete`. Re-reads the track and health data and runs `limits.validate`. If valid, stores a proposal (id, data snapshot, expiry of 30 min by default) and returns the plan, the proposal id and how to approve it. **The one-time code is never returned to the agent.** |
| `get_proposal(proposal_id)` | Read-only status: pending, approved, executed, rejected or expired, plus the result. |

### Approval paths (`approval_mode` in config, default `cli`)
1. **CLI (default, works with every client):** the human runs `uv run release-health approve <proposal-id>`. The CLI shows the diff and the snapshot, asks for interactive confirmation, and records `$USER` as the approver. The agent cannot run it, because it requires a TTY. Add the command to the client's deny list in the docs.
2. **Elicitation (for clients that support it):** the tool calls `ctx.elicit(...)` with a form (`approve: bool`, `reason: str`). The client shows the form to the human, not to the model. If the client doesn't support elicitation, the tool falls back to path 1 automatically.

### Hard limits (`limits.py`, unit-tested)
- An expand can add at most `max_step_pp` (20) percentage points, and the target must be greater than the current fraction.
- `complete` is blocked if `recommend_rollout` says hold or halt, or if the thresholds are broken.
- `expand`/`resume` are blocked when the decision is `halt`.
- `halt` is always allowed, regardless of the data.
- Only tracks in `allowed_tracks` can change (start with `["internal"]`; add `production` explicitly).
- **Drift check:** before executing, re-read the track. If its state differs from the proposal snapshot, abort.
- Proposals are single-use and expire.

### Executor
`edits.insert` → `edits.tracks.get` → change the release (`userFraction`, `status`) → `edits.tracks.update` → **dry-run (the default): `edits.validate` then `edits.delete`**, **live (`--live` flag or `dry_run: false`): `edits.commit`**. It uses `RELEASE_HEALTH_RELEASE_KEY`, a separate service account with release permission for the target app only. The note in the Google docs that changes can take hours applies, so the result says "submitted", not "applied".

### Audit log
JSONL at `$XDG_STATE_HOME/release-health/audit.jsonl` (configurable). It's append-only. Each event (`proposed`, `approved`, `rejected`, `expired`, `executed`, `failed`) holds: timestamp, proposal id, app, version, action, from and to fraction, health snapshot, approver, dry_run, and the API response or error. Optionally, each line can hold a hash of the previous line so tampering is detectable.

### Tests
- Limits: table-driven, including that halt is always allowed and complete is blocked.
- Proposal lifecycle: expired, reused, rejected.
- Executor via `HttpMockSequence`: asserts `validate` is called in dry-run and `commit` is called only in live mode.
- Drift abort, and the elicitation decline/cancel paths through the in-memory `Client`.

### Rollout of the feature itself
1. Use the internal track of a test app, in dry-run.
2. Then the internal track, live.
3. Then `production` for one low-traffic app, with halt-only at first.

## Milestone 4: Showcase (about 1 week)
- **README:** a Mermaid architecture diagram (read path plus approval-gated action path), quick start in fixture mode, Claude Code and Gemini CLI setup, a tools table, the safety model, and a threat model ("what if the agent is prompt-injected?" → it can only propose).
- **CI:** a GitHub Actions workflow with ruff, mypy and pytest on 3.12/3.13. Badge in the README.
- **Demo video (2–3 min):** Claude Code asks "is leo 4.12 healthy?" → recommend → propose expand → human approves in the CLI → audit entry. Then the same question in Gemini CLI to show the server works with any client.
- **Blog/LinkedIn post:** "Designing approval for agent actions": two-step proposals, codes the agent never sees, limits in code, least privilege, audit.
- **CV update** (text in the project plan).

### Optional extensions
- **Crashlytics BigQuery enrichment** for `top_crashes`: custom keys, full stack traces, and non-fatals (`google-cloud-bigquery`, an optional extra).
- **iOS** through the App Store Connect API (`perfPowerMetrics`, `diagnosticSignatures`): check the API's coverage first, then add an `ios` backend that implements the same `Backend` protocol.
- **Remote:** `server.run("streamable-http")` with a token verifier or OAuth, deployed to Cloud Run.
- **Tracing:** the SDK ships an `OpenTelemetryMiddleware` (`mcp.server._otel`). Wire it in with an OTLP exporter to trace tool calls.
