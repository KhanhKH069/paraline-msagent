#!/usr/bin/env python3
"""
scripts/health_check.py
Kiểm tra toàn bộ Meeting AI Assistant stack.
python scripts/health_check.py [--server 192.168.1.100]
"""
import argparse
import sys
import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SERVICES = [
    ("api-gateway",            8056),
    ("admin-api",              8057),
    ("whisperlive",            8001),
    ("translation-service",    8002),
    ("tts-service",            8003),
    ("agent-service",          8005),
    ("transcription-collector",8006),
]

def check(server: str):
    print(f"\n🟠 Meeting AI Assistant — Health Check ({server})")
    print("─" * 50)
    all_ok = True
    for name, port in SERVICES:
        url = f"http://{server}:{port}/health"
        try:
            r = requests.get(url, timeout=3)
            if r.ok:
                data = r.json()
                extra = ""
                if "model" in data:
                    extra = f" | model={data['model']}"
                if "voice" in data:
                    extra = f" | voice={data['voice']}"
                if "device" in data:
                    extra += f" | device={data['device']}"
                print(f"  ✅ {name:<30} port={port}{extra}")
            else:
                print(f"  ❌ {name:<30} port={port} HTTP {r.status_code}")
                all_ok = False
        except requests.exceptions.ConnectionError:
            print(f"  ❌ {name:<30} port={port} UNREACHABLE")
            all_ok = False
        except Exception as e:
            print(f"  ⚠️  {name:<30} port={port} {e}")
            all_ok = False

    print("─" * 50)
    if all_ok:
        print("✅ All services healthy — Meeting AI Assistant ready!\n")
    else:
        print("❌ Some services are down. Run: make logs\n")
    return all_ok


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default="localhost")
    args = parser.parse_args()
    ok = check(args.server)
    sys.exit(0 if ok else 1)
