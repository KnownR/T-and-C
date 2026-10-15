"""Live curl verification script to confirm the Phase 1 'Done when' criterion:

Uploading a ToS PDF via curl returns a document with ordered, positioned spans.
"""

import json
import subprocess
import sys
import time

def main():
    print("Starting uvicorn server on port 8765...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.app.main:app", "--port", "8765", "--log-level", "warning"]
    )
    try:
        # Wait for server to be up
        time.sleep(2.5)

        print("Executing curl upload of sample ToS PDF...")
        curl_cmd = [
            "curl.exe",
            "-s",
            "-F",
            "file=@backend/tests/fixtures/cloud_service_tos.pdf",
            "http://127.0.0.1:8765/api/documents",
        ]
        result = subprocess.run(curl_cmd, capture_output=True, text=True, check=True)
        response_text = result.stdout
        
        data = json.loads(response_text)
        print(f"HTTP response received successfully!")
        print(f"Document ID: {data.get('id')}")
        print(f"Filename: {data.get('filename')}")
        print(f"Source Type: {data.get('source_type')}")
        print(f"Page Count: {data.get('page_count')}")
        print(f"Total extracted spans: {len(data.get('spans', []))}")

        # Show first 3 spans with their bounding boxes
        print("\nSample positioned spans:")
        for span in data.get("spans", [])[:3]:
            print(f"  - Page {span['page']} [bbox={span['bbox']}]: {repr(span['text'])}")

        assert data["source_type"] == "pdf"
        assert data["page_count"] == 2
        assert len(data["spans"]) > 0
        first_span = data["spans"][0]
        assert first_span["page"] == 1
        assert len(first_span["bbox"]) == 4
        print("\nSUCCESS: 'Done when' acceptance criterion verified via live curl!")
    finally:
        proc.terminate()
        proc.wait(timeout=5)

if __name__ == "__main__":
    main()
