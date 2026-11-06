"""Capture policy source web pages as official source PDFs and log to manifest."""

import csv
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pypdf

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output" / "pdf" / "policy_sources"
EXCLUDED_DIR = OUTPUT_DIR / "excluded"

CHROME_BIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def capture_url_to_pdf(url: str, output_path: Path) -> dict:
    cmd = [
        CHROME_BIN,
        "--headless",
        "--disable-gpu",
        "--no-pdf-header-footer",
        "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        f"--print-to-pdf={output_path}",
        url,
    ]
    try:
        proc = subprocess.run(
            cmd,
            check=False, capture_output=True,
            text=True,
            timeout=45,
        )
        if not output_path.exists() or output_path.stat().st_size == 0:
            return {
                "status": "failed",
                "code": proc.returncode,
                "pages": 0,
                "chars": 0,
                "notes": f"File empty or not created. Stderr: {proc.stderr[:200]}",
            }
        
        # Verify with pypdf
        reader = pypdf.PdfReader(str(output_path))
        num_pages = len(reader.pages)
        total_text = ""
        for page in reader.pages:
            total_text += page.extract_text() or ""
        
        return {
            "status": "success",
            "code": proc.returncode,
            "pages": num_pages,
            "chars": len(total_text.strip()),
            "notes": "Captured and verified readable text",
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "failed",
            "code": -1,
            "pages": 0,
            "chars": 0,
            "notes": "Timed out after 45s",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "failed",
            "code": -1,
            "pages": 0,
            "chars": 0,
            "notes": str(exc),
        }


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    EXCLUDED_DIR.mkdir(parents=True, exist_ok=True)

    sources_csv = DATA_DIR / "policy_sources.csv"
    with sources_csv.open(newline="", encoding="utf-8-sig") as f:
        sources = list(csv.DictReader(f))

    manifest_rows = []
    print(f"Capturing {len(sources)} policy source URLs...")

    for row in sources:
        source_id = row["source_id"]
        marketplace = row["marketplace"]
        url = row["source_url"]
        is_excluded = (marketplace == "Amazon.com" or "EXCLUDED" in source_id)

        target_dir = EXCLUDED_DIR if is_excluded else OUTPUT_DIR
        target_file = target_dir / f"{source_id}.pdf"
        rel_path = target_file.relative_to(ROOT)

        print(f"[{source_id}] Fetching {url} -> {rel_path}...")
        res = capture_url_to_pdf(url, target_file)
        print(f"  Result: {res['status']} | Pages: {res['pages']} | Chars: {res['chars']}")

        manifest_rows.append({
            "source_id": source_id,
            "marketplace": marketplace,
            "source_url": url,
            "target_path": str(rel_path),
            "status": res["status"],
            "exit_code": res["code"],
            "pages": res["pages"],
            "character_count": res["chars"],
            "captured_at": datetime.now(UTC).isoformat(),
            "capture_method": "chrome_headless_print",
            "notes": res["notes"],
        })

    manifest_path = OUTPUT_DIR / "manifest.csv"
    with manifest_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(manifest_rows[0].keys()))
        writer.writeheader()
        writer.writerows(manifest_rows)

    print(f"\nManifest written to {manifest_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

