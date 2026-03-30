import requests
import yaml
from pathlib import Path

def _load_config():
    cfg_path = Path(__file__).parents[2] / "configs" / "services.yaml"
    return yaml.safe_load(cfg_path.read_text())

def get_embeddings(texts: list[str], env: str = "prod") -> list[list[float]]:
    cfg = _load_config()
    ip = cfg["server"]["ip"]
    port = cfg["embedding"]["prod_port"] if env == "prod" else cfg["embedding"]["dev_port"]
    endpoint = cfg["embedding"]["endpoint"]

    resp = requests.post(
        f"http://{ip}:{port}{endpoint}",
        json={"texts": texts},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["embeddings"]
