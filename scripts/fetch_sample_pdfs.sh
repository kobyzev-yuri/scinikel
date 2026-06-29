#!/usr/bin/env bash
# Скачать открытые PDF по металлургии Ni-Cu для теста ingest.
# Использование: ./scripts/fetch_sample_pdfs.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${ROOT}/data/samples"
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

mkdir -p "$OUT"
cd "$OUT"

fetch() {
  local name="$1"
  local url="$2"
  local referer="${3:-}"
  printf '[fetch] %s\n' "$name"
  local curl_args=(-fsSL -A "$UA" -L -o "$name")
  if [[ -n "$referer" ]]; then
    curl_args+=(-H "Referer: ${referer}/")
  fi
  if curl "${curl_args[@]}" "$url"; then
    if file -b "$name" | grep -qi pdf; then
      printf '  OK  %s (%s bytes)\n' "$name" "$(wc -c <"$name")"
      return 0
    fi
    printf '  WARN: not a PDF, removing %s\n' "$name" >&2
    rm -f "$name"
    return 1
  fi
  printf '  FAIL %s\n' "$url" >&2
  rm -f "$name"
  return 1
}

ok=0
fail=0

try_fetch() {
  if fetch "$@"; then ok=$((ok + 1)); else fail=$((fail + 1)); fi
}
try_fetch "giab-ni-cu-flotation-water.pdf" \
  "https://www.giab-online.ru/files/Data/2022/6/6-1_2022_263-278.pdf"

# Мончегорск — КиберЛенинка
try_fetch "cyberleninka-monchegorsk-flotation.pdf" \
  "https://cyberleninka.ru/article/n/obosnovanie-reagentnyh-rezhimov-flotatsii-soderzhaschey-epg-medno-nikelevoy-rudy-monchegorskogo-rayona/pdf"

try_fetch "mdpi-ni-cu-hydrodynamic-flotation.pdf" \
  "https://www.mdpi.com/2075-163X/11/3/328/pdf" \
  "https://www.mdpi.com/2075-163X/11/3/328"

# Springer Open — обзор
try_fetch "springer-ni-cu-processing-review.pdf" \
  "https://jeas.springeropen.com/counter/pdf/10.1186/s44147-025-00596-x.pdf"

echo ""
echo "Готово: ${ok} PDF в ${OUT}, ошибок: ${fail}"
if [[ "$ok" -eq 0 ]]; then
  echo "Если curl вернул 403 — скачайте PDF вручную из data/samples/README.md" >&2
  exit 1
fi
echo "Тест: python scripts/test_multimodal_ingest.py --pdf ${OUT}/<файл>.pdf"
