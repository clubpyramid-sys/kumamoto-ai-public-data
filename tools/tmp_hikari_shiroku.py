from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen

import fitz  # PyMuPDF
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject

MM_TO_PT = 72.0 / 25.4
TARGET_WIDTH_MM = 127.0
TARGET_HEIGHT_MM = 188.0
TARGET_WIDTH_PT = TARGET_WIDTH_MM * MM_TO_PT
TARGET_HEIGHT_PT = TARGET_HEIGHT_MM * MM_TO_PT
EXPECTED_PAGES = 100

OUT_DIR = Path("dist/hikari_shiroku")
SOURCE_PDF = OUT_DIR / "source_bunko.pdf"
INTERMEDIATE_PDF = OUT_DIR / "hikari_shiroku_intermediate.pdf"
FINAL_PDF = OUT_DIR / "光への道標_Amazon_KDP本文_四六判_127x188mm_100頁.pdf"
REPORT_JSON = OUT_DIR / "validation_report.json"
REPORT_TXT = OUT_DIR / "README_入稿仕様.txt"


def download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; KDP-PDF-Builder/1.0)",
            "Accept": "application/pdf,application/octet-stream,*/*",
        },
    )
    with urlopen(req, timeout=120) as response:
        data = response.read()
        content_type = response.headers.get("Content-Type", "")
    if not data.startswith(b"%PDF"):
        raise RuntimeError(
            f"Downloaded data is not a PDF. content_type={content_type!r}, "
            f"size={len(data)}, prefix={data[:80]!r}"
        )
    destination.write_bytes(data)


def convert_to_shiroku(source_path: Path, intermediate_path: Path) -> dict:
    src = fitz.open(source_path)
    if src.page_count != EXPECTED_PAGES:
        raise RuntimeError(f"Expected {EXPECTED_PAGES} pages, got {src.page_count}")

    out = fitz.open()
    page_records = []

    for index in range(src.page_count):
        src_page = src[index]
        src_rect = src_page.rect
        scale = min(TARGET_WIDTH_PT / src_rect.width, TARGET_HEIGHT_PT / src_rect.height)
        placed_width = src_rect.width * scale
        placed_height = src_rect.height * scale
        x0 = (TARGET_WIDTH_PT - placed_width) / 2.0
        y0 = (TARGET_HEIGHT_PT - placed_height) / 2.0
        destination_rect = fitz.Rect(x0, y0, x0 + placed_width, y0 + placed_height)

        new_page = out.new_page(width=TARGET_WIDTH_PT, height=TARGET_HEIGHT_PT)
        new_page.show_pdf_page(destination_rect, src, index, keep_proportion=True, overlay=True)

        page_records.append(
            {
                "page": index + 1,
                "source_width_pt": round(src_rect.width, 4),
                "source_height_pt": round(src_rect.height, 4),
                "target_width_pt": round(TARGET_WIDTH_PT, 4),
                "target_height_pt": round(TARGET_HEIGHT_PT, 4),
                "scale": round(scale, 8),
                "placed_width_pt": round(placed_width, 4),
                "placed_height_pt": round(placed_height, 4),
                "top_bottom_margin_pt_each": round(y0, 4),
                "left_right_margin_pt_each": round(x0, 4),
            }
        )

    metadata = src.metadata or {}
    metadata.update(
        {
            "title": "光への道標（みちしるべ）――見えない世界とつながり、魂を輝かせて生きる",
            "author": "久原 弘美",
            "subject": "Amazon KDP ペーパーバック本文／四六判 127×188mm／縦書き・右綴じ",
            "creator": "OpenAI / PyMuPDF",
            "producer": "PyMuPDF and pypdf",
        }
    )
    out.set_metadata(metadata)
    out.save(intermediate_path, garbage=4, deflate=True, clean=True)
    out.close()
    src.close()

    return {
        "page_count": len(page_records),
        "target_width_mm": TARGET_WIDTH_MM,
        "target_height_mm": TARGET_HEIGHT_MM,
        "page_records": page_records,
    }


def apply_pdf_viewer_preferences(intermediate_path: Path, final_path: Path) -> None:
    reader = PdfReader(str(intermediate_path))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)

    if reader.metadata:
        writer.add_metadata({
            "/Title": "光への道標（みちしるべ）――見えない世界とつながり、魂を輝かせて生きる",
            "/Author": "久原 弘美",
            "/Subject": "Amazon KDP ペーパーバック本文／四六判 127×188mm／縦書き・右綴じ",
        })

    writer._root_object[NameObject("/PageLayout")] = NameObject("/SinglePage")
    writer._root_object[NameObject("/ViewerPreferences")] = DictionaryObject(
        {NameObject("/Direction"): NameObject("/R2L")}
    )

    with final_path.open("wb") as fh:
        writer.write(fh)


def validate(final_path: Path, conversion: dict) -> dict:
    doc = fitz.open(final_path)
    errors = []
    page_sizes = []

    if doc.page_count != EXPECTED_PAGES:
        errors.append(f"Page count mismatch: {doc.page_count}")

    for index in range(doc.page_count):
        rect = doc[index].rect
        width_mm = rect.width / MM_TO_PT
        height_mm = rect.height / MM_TO_PT
        page_sizes.append(
            {
                "page": index + 1,
                "width_pt": round(rect.width, 4),
                "height_pt": round(rect.height, 4),
                "width_mm": round(width_mm, 4),
                "height_mm": round(height_mm, 4),
            }
        )
        if abs(width_mm - TARGET_WIDTH_MM) > 0.05 or abs(height_mm - TARGET_HEIGHT_MM) > 0.05:
            errors.append(
                f"Page {index + 1} size mismatch: {width_mm:.4f} x {height_mm:.4f} mm"
            )

    for page_number in (1, 6, 50, 100):
        page = doc[page_number - 1]
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
        pix.save(OUT_DIR / f"preview_page_{page_number:03d}.png")

    doc.close()

    file_bytes = final_path.read_bytes()
    report = {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "file": final_path.name,
        "file_size_bytes": len(file_bytes),
        "sha256": hashlib.sha256(file_bytes).hexdigest(),
        "page_count": EXPECTED_PAGES,
        "target_size_mm": [TARGET_WIDTH_MM, TARGET_HEIGHT_MM],
        "binding_direction": "right-to-left viewer preference (R2L)",
        "content_method": "Each original 105×148mm page is proportionally enlarged to fit the 127mm width and vertically centered on a 127×188mm page; no content is cropped.",
        "page_sizes": page_sizes,
        "conversion_summary": {
            "scale": conversion["page_records"][0]["scale"],
            "placed_width_pt": conversion["page_records"][0]["placed_width_pt"],
            "placed_height_pt": conversion["page_records"][0]["placed_height_pt"],
            "top_bottom_margin_pt_each": conversion["page_records"][0]["top_bottom_margin_pt_each"],
        },
    }
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    REPORT_TXT.write_text(
        """『光への道標』Amazon KDP本文PDF\n"
        "\n"
        "判型：四六判 127×188mm\n"
        "ページ数：100ページ\n"
        "本文：縦書き（原稿レイアウトを保持）\n"
        "綴じ方向：右綴じ想定／PDF閲覧方向R2L\n"
        "ページ番号：半角数字・横組み（元PDFを保持）\n"
        "裁ち落とし：なし\n"
        "変換方法：元の105×148mmページを縦横比を維持して127mm幅まで拡大し、127×188mmページの天地中央へ配置。文字・図版の欠落や裁ち落としはありません。\n"
        "\n"
        "注意：本PDFは出版権利者検討用第一ゲラを判型変換したものです。公開前に著者監修、校正、権利確認、KDPプレビューアー確認、校正刷り確認を行ってください。\n"
        """,
        encoding="utf-8",
    )

    if errors:
        raise RuntimeError("Validation failed: " + "; ".join(errors))
    return report


def main() -> None:
    source_url = os.environ.get("SOURCE_PDF_URL")
    if not source_url:
        raise RuntimeError("SOURCE_PDF_URL is required")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    download(source_url, SOURCE_PDF)
    conversion = convert_to_shiroku(SOURCE_PDF, INTERMEDIATE_PDF)
    apply_pdf_viewer_preferences(INTERMEDIATE_PDF, FINAL_PDF)
    report = validate(FINAL_PDF, conversion)
    INTERMEDIATE_PDF.unlink(missing_ok=True)
    SOURCE_PDF.unlink(missing_ok=True)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
