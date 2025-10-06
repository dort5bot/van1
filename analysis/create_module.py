#✅ create_module.py – Modül Şablonu Oluşturucu - AÇIKLAMA SONDA
import argparse
import os
import yaml
from pathlib import Path

SCHEMA_PATH = Path("analysis/metrics_schema.yaml")
MODULE_DIR = Path("analysis")
TESTS_DIR = Path("tests")

def load_existing_schema():
    if not SCHEMA_PATH.exists():
        return {"modules": []}
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def module_exists(schema_data, file_name):
    return any(mod.get("file") == file_name for mod in schema_data.get("modules", []))

def add_module_to_schema(schema_data, module_data):
    schema_data["modules"].append(module_data)
    with open(SCHEMA_PATH, "w", encoding="utf-8") as f:
        yaml.dump(schema_data, f, sort_keys=False, allow_unicode=True)

def create_module_file(file_name, display_name, command, output_type, priority):
    content = f'''# analysis/{file_name}
# {display_name} analiz modülü

from typing import Optional

async def run(symbol: str, priority: Optional[str] = None) -> dict:
    return {{
        "symbol": symbol,
        "priority": priority or "*",
        "output_type": "{output_type}",
        "description": "Automated module: {display_name}"
    }}
'''
    path = MODULE_DIR / file_name
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path

def create_test_file(file_name):
    content = f"""# tests/test_{file_name}
import pytest
import asyncio
from analysis import {file_name.replace('.py', '')}

@pytest.mark.asyncio
async def test_run():
    result = await {file_name.replace('.py', '')}.run("BTCUSDT")
    assert "symbol" in result
    assert "output_type" in result
"""
    path = TESTS_DIR / f"test_{file_name}"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path

def build_schema_block(display_name, file_name, command, api_type, endpoints, methods, metrics, priority, output_type):
    return {
        "name": display_name,
        "file": file_name,
        "command": command,
        "api_type": api_type,
        "endpoints": endpoints,
        "methods": methods,
        "classical_metrics": metrics,
        "professional_metrics": [
            {"name": "AutoMetric", "priority": priority}
        ],
        "composite_metrics": [],
        "development_notes": "",
        "objective": "",
        "output_type": output_type
    }

def interactive_prompt():
    print("🛠️  Etkileşimli modül oluşturma:")
    name = input("Modül kısa adı (örn: tremo): ").strip()
    display = input("Tam adı (örn: Trend & Momentum): ").strip()
    command = input("Komut (/trend): ").strip()
    api_type = input("API tipi (Spot/Futures): ").strip()
    endpoints = input("Endpoint(ler) (virgülle): ").strip().split(",")
    methods = input("HTTP Method(lar) (örn: GET,POST): ").strip().split(",")
    metrics = input("Klasik metrikler (virgülle): ").strip().split(",")
    priority = input("Öncelik seviyesi (*, **, ***): ").strip()
    return {
        "name": name,
        "display": display,
        "command": command,
        "api_type": api_type,
        "endpoints": [e.strip() for e in endpoints],
        "methods": [m.strip().upper() for m in methods],
        "metrics": [m.strip() for m in metrics],
        "priority": priority
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name")
    parser.add_argument("--display-name")
    parser.add_argument("--command")
    parser.add_argument("--api-type", choices=["Spot", "Futures", "External"], default="Spot")
    parser.add_argument("--endpoint", action="append", default=[])
    parser.add_argument("--methods", default="GET")
    parser.add_argument("--metrics", default="")
    parser.add_argument("--priority", choices=["*", "**", "***"], default="*")
    parser.add_argument("--output-type", default="Score (0–1)")
    parser.add_argument("--with-tests", action="store_true")
    parser.add_argument("--interactive", action="store_true")
    args = parser.parse_args()

    if args.interactive:
        inputs = interactive_prompt()
        name = inputs["name"]
        display_name = inputs["display"]
        command = inputs["command"]
        api_type = inputs["api_type"]
        endpoints = inputs["endpoints"]
        methods = inputs["methods"]
        metrics = inputs["metrics"]
        priority = inputs["priority"]
    else:
        name = args.name
        display_name = args.display_name
        command = args.command
        api_type = args.api_type
        endpoints = args.endpoint
        methods = [m.strip().upper() for m in args.methods.split(",")]
        metrics = [m.strip() for m in args.metrics.split(",")]
        priority = args.priority

    file_name = f"{name}.py"
    output_type = args.output_type

    schema = load_existing_schema()

    if module_exists(schema, file_name):
        print(f"❌ {file_name} zaten mevcut.")
        return

    MODULE_DIR.mkdir(parents=True, exist_ok=True)
    module_path = create_module_file(file_name, display_name, command, output_type, priority)
    print(f"✅ Modül dosyası: {module_path}")

    if args.with_tests:
        TESTS_DIR.mkdir(parents=True, exist_ok=True)
        test_path = create_test_file(file_name)
        print(f"🧪 Test dosyası: {test_path}")

    block = build_schema_block(display_name, file_name, command, api_type, endpoints, methods, metrics, priority, output_type)
    add_module_to_schema(schema, block)
    print(f"📄 Schema güncellendi: {file_name} eklendi.")

if __name__ == "__main__":
    main()



"""
python create_module.py --interactive --with-tests

python create_module.py --name risk --display-name "Risk Yönetimi" --command /risk \
--api-type Futures --endpoint /fapi/v1/liquidationOrders --endpoint /api/v3/klines \
--methods GET --metrics "ATR Stop,VaR" --priority *** --with-tests


+
Hazır olduğunda bunu CLI aracı olarak daha da genişletebiliriz (örneğin modül silme, şema kontrolü, test runner vs.).


"""