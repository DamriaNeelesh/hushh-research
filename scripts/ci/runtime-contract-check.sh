#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"

backend_helper="$REPO_ROOT/hushh-webapp/app/api/_utils/backend.ts"
frontend_cloudbuild="$REPO_ROOT/deploy/frontend.cloudbuild.yaml"

if grep -q 'consent-protocol-rpphvsc3tq-uc.a.run.app' "$backend_helper"; then
  echo "❌ backend route helper still hardcodes a production backend fallback."
  exit 1
fi

if ! grep -q 'do not guess a backend origin' "$backend_helper"; then
  echo "❌ backend route helper is missing the hosted fail-fast contract."
  exit 1
fi

if ! grep -q 'BACKEND_URL=BACKEND_URL:latest' "$frontend_cloudbuild"; then
  echo "❌ frontend Cloud Run deploy must inject BACKEND_URL at runtime."
  exit 1
fi

if ! grep -q 'DEVELOPER_API_URL=BACKEND_URL:latest' "$frontend_cloudbuild"; then
  echo "❌ frontend Cloud Run deploy must inject DEVELOPER_API_URL at runtime."
  exit 1
fi

if ! grep -q -- '--set-env-vars=NEXT_PUBLIC_APP_ENV=' "$frontend_cloudbuild"; then
  echo "❌ frontend Cloud Run deploy must inject NEXT_PUBLIC_APP_ENV at runtime."
  exit 1
fi

echo "✅ Runtime contract check passed."
