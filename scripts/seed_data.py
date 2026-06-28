#!/usr/bin/env python3
"""Загрузка seed-данных в граф."""

from scinikel.config import GRAPH_PATH, SEED_DIR
from scinikel.graph.networkx_store import NetworkXGraphStore
from scinikel.ingest.loader import ingest_seed_data


def main() -> None:
    store = NetworkXGraphStore()
    stats = ingest_seed_data(store, SEED_DIR)
    store.save(GRAPH_PATH)
    print("Ingested:", stats)
    print("Graph stats:", store.stats())
    print("Saved to:", GRAPH_PATH)


if __name__ == "__main__":
    main()
