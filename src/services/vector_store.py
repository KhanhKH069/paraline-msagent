from qdrant_client import QdrantClient
import yaml
from pathlib import Path

def _load_config():
    cfg_path = Path(__file__).parents[2] / "configs" / "services.yaml"
    return yaml.safe_load(cfg_path.read_text())

def get_client(env: str = "prod") -> QdrantClient:
    cfg = _load_config()
    ip = cfg["server"]["ip"]
    port = cfg["qdrant"]["prod_port"] if env == "prod" else cfg["qdrant"]["dev_port"]
    return QdrantClient(host=ip, port=port)

def search(query_vector: list[float], limit: int = 5, env: str = "prod"):
    cfg = _load_config()
    client = get_client(env)
    return client.search(
        collection_name=cfg["qdrant"]["collection"],
        query_vector=query_vector,
        limit=limit,
    )
