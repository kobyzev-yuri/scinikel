#!/usr/bin/env bash
# Только Qdrant (для обратной совместимости). Полное управление: ./scripts/services.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
QDRANT_PORT="${QDRANT_PORT:-6333}"
QDRANT_CONTAINER="scinikel_qdrant"

docker run -d --name "$QDRANT_CONTAINER" \
  -p "${QDRANT_PORT}:6333" -p "$((QDRANT_PORT + 1)):6334" \
  -v scinikel_qdrant_data:/qdrant/storage \
  qdrant/qdrant:latest 2>/dev/null || docker start "$QDRANT_CONTAINER"
echo "Qdrant: http://localhost:${QDRANT_PORT}"
