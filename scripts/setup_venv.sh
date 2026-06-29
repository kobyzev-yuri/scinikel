#!/usr/bin/env bash
# Создать .venv на системном Python (без Anaconda).
# Использование: ./scripts/setup_venv.sh [--search] [--multimodal]

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WITH_SEARCH=0
WITH_MULTIMODAL=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --search) WITH_SEARCH=1; shift ;;
    --multimodal) WITH_MULTIMODAL=1; shift ;;
    -h|--help)
      echo "Использование: ./scripts/setup_venv.sh [--search] [--multimodal]"
      echo "  --search      sentence-transformers / e5 (Qdrant)"
      echo "  --multimodal  open-clip-torch, Pillow (CLIP ingest)"
      exit 0
      ;;
    *) echo "Неизвестный аргумент: $1" >&2; exit 1 ;;
  esac
done

pick_python() {
  if [[ -n "${PYTHON:-}" ]] && [[ -x "${PYTHON}" ]]; then
    printf '%s\n' "${PYTHON}"
    return 0
  fi
  local candidate resolved
  for candidate in /usr/bin/python3.12 /usr/bin/python3 /usr/local/bin/python3.12; do
    [[ -x "$candidate" ]] || continue
    resolved="$(readlink -f "$candidate" 2>/dev/null || echo "$candidate")"
    if [[ "$resolved" == *anaconda* ]] || [[ "$resolved" == *conda* ]]; then
      continue
    fi
    printf '%s\n' "$candidate"
    return 0
  done
  return 1
}

PYTHON_BIN="$(pick_python)" || {
  echo "Не найден системный python3 вне Anaconda." >&2
  echo "Укажите вручную: PYTHON=/usr/bin/python3 ./scripts/setup_venv.sh" >&2
  exit 1
}

echo "[setup_venv] Python: $PYTHON_BIN ($("$PYTHON_BIN" --version))"
echo "[setup_venv] Удаление старого .venv…"
rm -rf "${ROOT}/.venv"

echo "[setup_venv] Создание виртуального окружения…"
if ! "$PYTHON_BIN" -m venv "${ROOT}/.venv" 2>/dev/null; then
  echo "[setup_venv] ensurepip недоступен — venv без pip + bootstrap…"
  "$PYTHON_BIN" -m venv --without-pip "${ROOT}/.venv"
  curl -fsSL https://bootstrap.pypa.io/get-pip.py | "${ROOT}/.venv/bin/python" -
fi

# shellcheck disable=SC1091
source "${ROOT}/.venv/bin/activate"
python -m pip install -U pip wheel

EXTRA="dev"
extras=()
if [[ "$WITH_SEARCH" -eq 1 ]]; then
  extras+=("search")
fi
if [[ "$WITH_MULTIMODAL" -eq 1 ]]; then
  extras+=("multimodal")
fi
if [[ ${#extras[@]} -gt 0 ]]; then
  EXTRA="dev,$(IFS=,; echo "${extras[*]}")"
fi

pip install -e ".[${EXTRA}]"
echo "[setup_venv] Готово. Активация: source .venv/bin/activate"
