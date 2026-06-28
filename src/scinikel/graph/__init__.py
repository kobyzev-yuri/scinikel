"""Graph store factory and backends."""

from scinikel.config import GRAPH_PATH, settings
from scinikel.graph.base import GraphStore
from scinikel.graph.networkx_store import NetworkXGraphStore


def get_graph_store(*, reload: bool = False) -> GraphStore:
    backend = settings.graph_backend.lower()
    if backend == "neo4j":
        from scinikel.graph.neo4j_store import Neo4jGraphStore

        return Neo4jGraphStore()

    store = NetworkXGraphStore()
    if GRAPH_PATH.exists() or not reload:
        store.load(GRAPH_PATH)
    return store


__all__ = ["GraphStore", "NetworkXGraphStore", "get_graph_store"]
