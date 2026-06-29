#!/usr/bin/env bash
# Управление сервисами «Научный клубок»: API + Qdrant
# Использование:
#   ./scripts/services.sh start|stop|restart|status
#   ./scripts/services.sh --docker start|stop|restart|status
#   ./scripts/services.sh start --seed    # пересобрать демо-граф перед стартом

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="${ROOT}/.run"
API_PID_FILE="${RUN_DIR}/api.pid"
API_LOG_FILE="${RUN_DIR}/api.log"
QDRANT_CONTAINER="scinikel_qdrant"
API_PORT="${SCINIKEL_PORT:-8000}"
QDRANT_PORT="${QDRANT_PORT:-6333}"
MODE="local"
SEED_ON_START=0

usage() {
  cat <<'EOF'
Научный клубок — управление сервисами

Команды:
  start     Запустить Qdrant и API
  stop      Остановить Qdrant и API
  restart   Перезапустить все сервисы
  status    Показать статус сервисов

Опции:
  --docker      Полный стек через docker compose (api + qdrant)
  --seed        Перед стартом: python scripts/seed_data.py
  --help        Эта справка

Примеры:
  ./scripts/services.sh start
  ./scripts/services.sh restart
  ./scripts/services.sh --docker start
  ./scripts/services.sh start --seed

Локальный режим (по умолчанию):
  · Qdrant — Docker-контейнер scinikel_qdrant
  · API    — uvicorn на http://localhost:8000 (лог: .run/api.log)

Docker-режим:
  · docker compose up/down для api и qdrant
EOF
}

log() { printf '[services] %s\n' "$*"; }
warn() { printf '[services] WARN: %s\n' "$*" >&2; }

parse_args() {
  local cmd=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      start|stop|restart|status)
        cmd="$1"
        shift
        ;;
      --docker)
        MODE="docker"
        shift
        ;;
      --seed)
        SEED_ON_START=1
        shift
        ;;
      --help|-h)
        usage
        exit 0
        ;;
      *)
        warn "Неизвестный аргумент: $1"
        usage
        exit 1
        ;;
    esac
  done

  if [[ -z "$cmd" ]]; then
    usage
    exit 1
  fi
  COMMAND="$cmd"
}

require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    warn "Docker не найден. Установите Docker или используйте только API без Qdrant."
    exit 1
  fi
}

is_api_running() {
  if [[ -f "$API_PID_FILE" ]]; then
    local pid
    pid="$(cat "$API_PID_FILE")"
    if kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    rm -f "$API_PID_FILE"
  fi
  if curl -fsS "http://127.0.0.1:${API_PORT}/api/graph/stats" >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

is_qdrant_running() {
  if curl -fsS "http://127.0.0.1:${QDRANT_PORT}/readyz" >/dev/null 2>&1; then
    return 0
  fi
  if curl -fsS "http://127.0.0.1:${QDRANT_PORT}/" >/dev/null 2>&1; then
    return 0
  fi
  if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$QDRANT_CONTAINER"; then
    return 0
  fi
  return 1
}

activate_venv() {
  if [[ -f "${ROOT}/.venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "${ROOT}/.venv/bin/activate"
    return 0
  fi
  if [[ -f "${ROOT}/venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "${ROOT}/venv/bin/activate"
    return 0
  fi
  warn "Виртуальное окружение не найдено. Создайте: ./scripts/setup_venv.sh"
  exit 1
}

maybe_seed() {
  if [[ "$SEED_ON_START" -eq 1 ]]; then
    log "Загрузка демо-данных…"
    activate_venv
    python "${ROOT}/scripts/seed_data.py"
  fi
}

start_qdrant_local() {
  require_docker
  if is_qdrant_running; then
    log "Qdrant уже запущен (порт ${QDRANT_PORT})"
    return 0
  fi

  if docker ps -a --format '{{.Names}}' | grep -qx "$QDRANT_CONTAINER"; then
    log "Запуск контейнера ${QDRANT_CONTAINER}…"
    docker start "$QDRANT_CONTAINER" >/dev/null
  else
    log "Создание контейнера ${QDRANT_CONTAINER}…"
    docker run -d --name "$QDRANT_CONTAINER" \
      -p "${QDRANT_PORT}:6333" -p "$((QDRANT_PORT + 1)):6334" \
      -v scinikel_qdrant_data:/qdrant/storage \
      qdrant/qdrant:latest >/dev/null
  fi

  for _ in $(seq 1 30); do
    if is_qdrant_running; then
      log "Qdrant: http://localhost:${QDRANT_PORT}"
      return 0
    fi
    sleep 0.5
  done
  warn "Qdrant не ответил вовремя, но контейнер запущен"
}

stop_qdrant_local() {
  require_docker
  if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$QDRANT_CONTAINER"; then
    log "Остановка ${QDRANT_CONTAINER}…"
    docker stop "$QDRANT_CONTAINER" >/dev/null
  else
    log "Qdrant не запущен"
  fi
}

start_api_local() {
  if is_api_running; then
    log "API уже запущен: http://localhost:${API_PORT}"
    return 0
  fi

  activate_venv
  mkdir -p "$RUN_DIR"

  if [[ ! -f "${ROOT}/data/graph.json" ]]; then
    warn "data/graph.json не найден — запускаю seed_data.py"
    python "${ROOT}/scripts/seed_data.py"
  fi

  log "Запуск API на порту ${API_PORT}…"
  cd "$ROOT"
  nohup uvicorn scinikel.api.app:app \
    --host 0.0.0.0 \
    --port "$API_PORT" \
    >"$API_LOG_FILE" 2>&1 &
  echo $! >"$API_PID_FILE"

  for _ in $(seq 1 40); do
    if curl -fsS "http://127.0.0.1:${API_PORT}/api/graph/stats" >/dev/null 2>&1; then
      log "API: http://localhost:${API_PORT} (pid $(cat "$API_PID_FILE"), лог ${API_LOG_FILE})"
      return 0
    fi
    if ! kill -0 "$(cat "$API_PID_FILE")" 2>/dev/null; then
      warn "API завершился при старте. См. ${API_LOG_FILE}"
      tail -n 20 "$API_LOG_FILE" >&2 || true
      rm -f "$API_PID_FILE"
      exit 1
    fi
    sleep 0.5
  done
  warn "API не ответил вовремя. См. ${API_LOG_FILE}"
}

stop_api_local() {
  local stopped=0
  if [[ -f "$API_PID_FILE" ]]; then
    local pid
    pid="$(cat "$API_PID_FILE")"
    if kill -0 "$pid" 2>/dev/null; then
      log "Остановка API (pid ${pid})…"
      kill "$pid" 2>/dev/null || true
      sleep 1
      kill -9 "$pid" 2>/dev/null || true
      stopped=1
    fi
    rm -f "$API_PID_FILE"
  fi

  # На случай ручного запуска scinikel / uvicorn
  if pgrep -f "uvicorn scinikel.api.app:app" >/dev/null 2>&1; then
    log "Остановка оставшихся процессов uvicorn…"
    pkill -f "uvicorn scinikel.api.app:app" 2>/dev/null || true
    stopped=1
  fi

  if [[ "$stopped" -eq 0 ]]; then
    log "API не запущен"
  fi
}

start_docker() {
  require_docker
  maybe_seed
  log "Docker compose up…"
  cd "$ROOT"
  docker compose up -d --build
  log "API: http://localhost:${API_PORT}"
  log "Qdrant: http://localhost:${QDRANT_PORT}"
}

stop_docker() {
  require_docker
  log "Docker compose down…"
  cd "$ROOT"
  docker compose down
}

status_local() {
  printf '\n=== Статус (локальный режим) ===\n'
  if is_qdrant_running; then
    printf 'Qdrant:  UP   http://localhost:%s\n' "$QDRANT_PORT"
  else
    printf 'Qdrant:  DOWN\n'
  fi
  if is_api_running; then
    if [[ -f "$API_PID_FILE" ]]; then
      printf 'API:     UP   http://localhost:%s  pid %s\n' "$API_PORT" "$(cat "$API_PID_FILE")"
    else
      printf 'API:     UP   http://localhost:%s\n' "$API_PORT"
    fi
    printf 'Лог API: %s\n' "$API_LOG_FILE"
  else
    printf 'API:     DOWN\n'
  fi
  printf '\n'
}

status_docker() {
  require_docker
  printf '\n=== Статус (docker compose) ===\n'
  cd "$ROOT"
  docker compose ps
  printf '\n'
}

start_local() {
  maybe_seed
  start_qdrant_local
  start_api_local
  status_local
}

stop_local() {
  stop_api_local
  stop_qdrant_local
  status_local
}

restart_local() {
  stop_local
  sleep 1
  start_local
}

restart_docker() {
  stop_docker
  sleep 1
  start_docker
  status_docker
}

main() {
  parse_args "$@"

  case "$MODE:$COMMAND" in
    local:start) start_local ;;
    local:stop) stop_local ;;
    local:restart) restart_local ;;
    local:status) status_local ;;
    docker:start) start_docker; status_docker ;;
    docker:stop) stop_docker ;;
    docker:restart) restart_docker ;;
    docker:status) status_docker ;;
    *)
      warn "Неизвестная комбинация: $MODE $COMMAND"
      exit 1
      ;;
  esac
}

main "$@"
