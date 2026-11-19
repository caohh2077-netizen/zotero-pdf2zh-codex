"""One document in an owned process tree. Only structured status is sent to the server."""
import asyncio
import json
import os
from pathlib import Path
import sys


def emit(event):
    path = Path(os.environ["ZPC_JOB_DIR"]) / "progress.jsonl"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False)+"\n")


def searchable(path, language, tessdata):
    import pymupdf
    with pymupdf.open(path) as doc:
        candidates = []
        existing_layer = False
        for i, page in enumerate(doc):
            images = page.get_image_info()
            if not images:
                continue
            if not page.get_text().strip():
                candidates.append(i)
            elif any((pymupdf.Rect(img["bbox"]) & page.rect).get_area() > page.rect.get_area()*.45 for img in images):
                spans = page.get_texttrace()
                hidden = sum(len(span["chars"]) for span in spans if span["type"] == 3)
                existing_layer |= hidden > sum(len(span["chars"]) for span in spans if span["type"] != 3)
        if not candidates:
            return path, existing_layer
        iso = {"en":"eng","de":"deu","fr":"fra","es":"spa","zh":"chi_sim",
               "ja":"jpn","it":"ita","pt":"por","ru":"rus"}.get(language.split("-")[0], language)
        if not (tessdata / (iso+".traineddata")).is_file():
            raise ValueError("扫描件缺少 OCR 语言资源 " + iso)
        for index, page_num in enumerate(candidates, 1):
            emit({"type":"ocr","current":index,"total":len(candidates)})
            page = doc[page_num]
            pix = page.get_pixmap(dpi=216, alpha=False)
            with pymupdf.open("pdf", pix.pdfocr_tobytes(language=iso, tessdata=str(tessdata))) as layer:
                if not layer[0].get_text().strip():
                    continue
                # Replace only the scan page in this disposable copy. Preserve the
                # existing geometry and page order. Native text pages stay native.
                rect = page.rect
                replacement = doc.new_page(pno=page_num+1, width=rect.width, height=rect.height)
                replacement.show_pdf_page(replacement.rect, layer, 0)
                doc.delete_page(page_num)
        directory = path.parent / "ocr"
        directory.mkdir(exist_ok=True)
        output = directory / path.name
        doc.save(output, garbage=3, deflate=True)
        return output, True


async def main():
    from pdf2zh_next.config import ConfigManager
    from pdf2zh_next.high_level import do_translate_async_stream
    settings = ConfigManager().initialize_config()
    source = Path(next(iter(settings.basic.input_files)))
    if settings.pdf.auto_enable_ocr_workaround or settings.pdf.ocr_workaround:
        source, scanned = searchable(source, settings.translation.lang_in, Path(os.environ["ZPC_TESSDATA"]))
        if scanned:
            # BabelDOC needs its actual OCR rendering mode to clear the scan
            # underneath translated glyphs. Detection alone can miss a new layer.
            settings.pdf.auto_enable_ocr_workaround = False
            settings.pdf.ocr_workaround = True
    complete = False
    async for event in do_translate_async_stream(settings, source):
        kind = event.get("type")
        if kind == "error":
            raise RuntimeError("引擎未完成翻译。")
        if kind == "finish":
            result = event["translate_result"]
            paths = [str(p) for p in (result.mono_pdf_path, result.dual_pdf_path) if p]
            emit({"type":"output","paths":paths})
            complete = True
        elif kind in ("progress_start", "progress_update", "progress_end"):
            emit({k:event[k] for k in ("type","stage","stage_current","stage_total","part_index",
                                        "total_parts","overall_progress") if k in event})
    if not complete:
        raise RuntimeError("引擎未返回成品。")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        # Never include the translator input, account credentials, or raw model output.
        message = str(error)
        emit({"type":"failure","message":message if message.startswith("扫描件缺少 OCR") else
              "PDF 引擎失败 (" + type(error).__name__ + ")"})
        sys.exit(1)
