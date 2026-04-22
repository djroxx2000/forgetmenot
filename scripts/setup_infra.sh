#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo "==> Starting forgetmenot infrastructure..."
docker compose up -d

echo ""
echo "==> Waiting for services to become healthy..."

services=("forgetmenot-qdrant" "forgetmenot-neo4j" "forgetmenot-postgres")
max_wait=120
elapsed=0

all_healthy=false
while [ "$elapsed" -lt "$max_wait" ]; do
    all_healthy=true
    for svc in "${services[@]}"; do
        status=$(docker inspect --format='{{.State.Health.Status}}' "$svc" 2>/dev/null || echo "not_found")
        if [ "$status" != "healthy" ]; then
            all_healthy=false
            break
        fi
    done

    if $all_healthy; then
        break
    fi

    sleep 3
    elapsed=$((elapsed + 3))
    printf "\r  Elapsed: %ds / %ds" "$elapsed" "$max_wait"
done

echo ""

if $all_healthy; then
    echo "==> All services healthy!"
else
    echo "==> WARNING: Not all services healthy after ${max_wait}s. Check 'docker compose ps'."
    exit 1
fi

echo ""
echo "Service endpoints:"
echo "  Qdrant:    http://localhost:6333"
echo "  Neo4j:     http://localhost:7474 (bolt://localhost:7687)"
echo "  Postgres:  postgresql://memzero:memzero_dev@localhost:5432/memzero"
