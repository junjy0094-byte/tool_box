import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(config: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def get_tool_config(tool_name: str) -> dict:
    config = load_config()
    return config.get(tool_name, {})


def set_tool_config(tool_name: str, tool_config: dict) -> None:
    config = load_config()
    config[tool_name] = tool_config
    save_config(config)
