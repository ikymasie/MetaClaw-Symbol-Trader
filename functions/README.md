# TradeClaw — Scheduled Cloud Functions

Serverless maintenance and intelligence functions that run on GCP Cloud Scheduler.
These operate independently of the main Cloud Run backend.

## Structure

```
functions/
├── main.py                   # Cloud Functions entry points (HTTP triggers)
├── shared.py                 # Shared Firestore init + helpers
├── firestore_pruner.py       # P0: Data hygiene — prune stale docs
├── recommendation_scorer.py  # P0: Score agent signals against forward returns
├── requirements.txt          # Python dependencies
├── .env.yaml                 # Environment variables for deploy
├── deploy.sh                 # One-command deploy + scheduler setup
└── README.md                 # This file
```

## Functions

| Function | Schedule | Purpose |
|----------|----------|---------|
| `firestore-pruner` | Every 6 hours | Prune old market bars, strategy embeddings, agent recommendations, signals, and stale telemetry |
| `recommendation-scorer` | Every 4 hours (Mon-Fri) | Score unscored agent recommendations against actual forward returns |

## Deploy

```bash
# Deploy everything
cd functions && chmod +x deploy.sh && ./deploy.sh all

# Deploy individually
./deploy.sh pruner
./deploy.sh scorer
```

## Local Testing

```bash
cd functions
pip install -r requirements.txt

# Test pruner
functions-framework --target firestore_pruner --port 8081
curl http://localhost:8081

# Test scorer
functions-framework --target recommendation_scorer --port 8082
curl http://localhost:8082
```

## Observability

Each function writes its execution report to Firestore:
- `system_metrics/last_prune` — Pruner results
- `system_metrics/last_scoring` — Scorer results

Check these docs in the Firebase console to verify runs.
