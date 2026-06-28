#!/usr/bin/env bash
# Запуск Qdrant — паттерн из 3dtoday/scripts/start_qdrant.sh
set -euo pipefail
docker run -d --name scinikel_qdrant \
  -p 6333:6333 -p 6334:6334 \
  -v scinikel_qdrant_data:/qdrant/storage \
  qdrant/qdrant:latest 2>/dev/null || docker start scinikel_qdrant
echo "Qdrant: http://localhost:6333"
