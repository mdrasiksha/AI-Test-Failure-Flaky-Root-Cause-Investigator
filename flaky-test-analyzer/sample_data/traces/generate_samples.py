"""Generate safe synthetic Playwright trace ZIP examples locally."""

from __future__ import annotations

import json
from pathlib import Path
import zipfile

OUTPUT_DIRECTORY = Path(__file__).parent
SAMPLES: dict[str, dict[str, list[dict[str, object]]]] = {
    "locator_timeout.zip": {"trace": [
        {"type": "before", "callId": "1", "apiName": "page.goto", "startTime": 100, "params": {"url": "https://example.test/payment"}},
        {"type": "after", "callId": "1", "endTime": 200},
        {"type": "before", "callId": "2", "apiName": "locator.fill", "startTime": 300, "params": {"selector": "#account", "value": "synthetic"}},
        {"type": "after", "callId": "2", "endTime": 350},
        {"type": "before", "callId": "3", "apiName": "locator.click", "startTime": 400, "params": {"selector": "get_by_role('button', name='Pay')"}},
        {"type": "after", "callId": "3", "endTime": 5400, "error": {"message": "Timeout 5000ms exceeded while waiting for locator"}},
    ]},
    "network_503.zip": {
        "trace": [
            {"type": "before", "callId": "1", "apiName": "locator.click", "startTime": 9000, "params": {"selector": "text=Pay"}},
            {"type": "after", "callId": "1", "endTime": 10000, "error": {"message": "Timeout exceeded"}},
        ],
        "network": [{"type": "resource-snapshot", "snapshot": {"request": {"method": "POST", "url": "https://example.test/api/payment?token=synthetic"}, "response": {"status": 503}, "timestamp": 8000, "duration": 1600, "resourceType": "fetch"}}],
    },
    "navigation_timeout.zip": {"trace": [
        {"type": "before", "callId": "1", "apiName": "page.goto", "startTime": 1, "params": {"url": "https://example.test/slow"}},
        {"type": "after", "callId": "1", "endTime": 30001, "error": {"message": "Navigation timeout 30000ms exceeded"}},
    ]},
}


def create_sample_archive(name: str, destination: Path | None = None) -> Path:
    """Create one deterministic sample archive and return its output path."""
    sample = SAMPLES[name]
    target = destination or OUTPUT_DIRECTORY / name
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("trace.trace", "\n".join(json.dumps(item) for item in sample["trace"]))
        if sample.get("network"):
            archive.writestr("trace.network", "\n".join(json.dumps(item) for item in sample["network"]))
        archive.writestr("resources/example.txt", "synthetic fixture only")
    return target


def main() -> None:
    for name in SAMPLES:
        print(f"Created {create_sample_archive(name)}")


if __name__ == "__main__":
    main()
