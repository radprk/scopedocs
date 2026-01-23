# Integrations Testing

This guide covers end-to-end testing for Slack, GitHub, and Linear integrations, including local webhook receivers, tunnel configuration, fixture scripts, and optional Postgres readbacks.

## Prerequisites

- Backend API running locally (default: `http://localhost:8001`).
- A tunnel provider (ngrok or Cloudflare Tunnel).
- Sandbox accounts:
  - **Slack**: Dev workspace + test app configured with Events API.
  - **GitHub**: Test repo with a webhook pointing to your tunnel URL.
  - **Linear**: Test workspace + API key to configure webhook.
- Optional: Postgres for write verification (set `POSTGRES_DSN`).

## 1) Start the API

```bash
cd backend
uvicorn server:app --reload --port 8001
```

## 2) Start a Tunnel

Pick one:

### ngrok
```bash
ngrok http 8001
```

### Cloudflare Tunnel
```bash
cloudflared tunnel --url http://localhost:8001
```

Use the public URL to configure webhooks in Slack/GitHub/Linear.

## 3) Configure Webhooks

### Slack (Events API)
- Request URL: `<TUNNEL_URL>/api/webhooks/slack`
- Subscribe to `message.channels` or `message.groups`.
- During verification, the endpoint responds with the Slack challenge.

### GitHub
- Payload URL: `<TUNNEL_URL>/api/webhooks/github`
- Content type: `application/json`
- Events: `pull_request`

### Linear
- Webhook URL: `<TUNNEL_URL>/api/webhooks/linear`
- Events: Issue updates

## 4) Seed Sample Events (Local)

Use the fixture scripts to seed a baseline of events through the local webhook receiver.

```bash
python tests/integrations/fixtures/seed_linear_event.py --issue-id LIN-123
python tests/integrations/fixtures/seed_github_event.py --issue-id LIN-123 --pr-number 101
python tests/integrations/fixtures/seed_slack_event.py --issue-id LIN-123
```

## 5) Validate Writes (Mongo + Optional Postgres)

### MongoDB (via API)
```bash
curl http://localhost:8001/api/stats
curl http://localhost:8001/api/relationships
```

### Postgres (optional)
If `POSTGRES_DSN` is set, the API mirrors incoming webhook data into Postgres tables (`work_items`, `pull_requests`, `conversations`, `relationships`, `artifact_events`).

```bash
export POSTGRES_DSN="postgresql://user:pass@localhost:5432/scopedocs"
```

Once the API is running, you can check counts and FK relationships:

```bash
psql "$POSTGRES_DSN" -c "SELECT COUNT(*) FROM work_items;"
psql "$POSTGRES_DSN" -c "SELECT COUNT(*) FROM pull_requests;"
psql "$POSTGRES_DSN" -c "SELECT COUNT(*) FROM relationships;"
```

## 6) Run Integration Tests

```bash
export RUN_INTEGRATION_TESTS=1
pytest tests/integrations
```

These tests call the webhook endpoints and verify counts + relationships (and Postgres readbacks if configured).
