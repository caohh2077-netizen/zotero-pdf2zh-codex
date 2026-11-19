"""Merge integer paragraph progress from BabelDOC. File counts belong to Zotero."""
class Fragments:
    def __init__(self):
        self.parts = {}
        self.count = self.part = 1
        self.stage = "analysis"
        self.calls = self.failed = 0
        self.dispatched = set()
        self.outcomes = set()
        self.retrying = set()
        self.error = None
        self.ended = set()
        self.terminal = False
        self.ocr = None

    def update(self, e):
        if self.terminal:
            return
        if e.get("type") == "ocr":
            self.ocr = (e["current"], e["total"])
            self.stage = "ocr"
            return
        if e.get("event") == "start":
            if e["id"] in self.dispatched:
                return
            self.dispatched.add(e["id"])
            self.calls += 1
            return
        if e.get("event") == "end":
            fragment = e.get("fragmentId", e["id"])
            if fragment in self.outcomes:
                return
            if not e.get("final", True):
                self.retrying.add(fragment)
                return
            self.retrying.discard(fragment)
            self.outcomes.add(fragment)
            if e.get("result") != "ok":
                self.failed += 1
                self.error = e.get("result")
            return
        if e.get("stage") != "Translate Paragraphs" or e.get("type") not in (
                "progress_start", "progress_update", "progress_end"):
            return
        part = max(1, int(e.get("part_index") or 1))
        if part in self.ended:
            return
        self.count = max(self.count, int(e.get("total_parts") or 1), part)
        self.part = max(self.part, part)
        cur, total = self.parts.get(part, (0, 0))
        total = max(total, int(e["stage_total"]))
        cur = min(total, max(cur, int(e["stage_current"])))
        self.parts[part] = cur, total
        self.stage = "translate"
        if e["type"] == "progress_end":
            self.ended.add(part)
            if len(self.ended) == self.count:
                self.stage = "typeset"

    def snapshot(self):
        current = sum(n for n, _ in self.parts.values())
        total = sum(n for _, n in self.parts.values()) if len(self.parts) == self.count else None
        cur, size = self.parts.get(self.part, (0, None))
        return {"current":current, "total":total, "part":self.part, "parts":self.count,
                "partCurrent":cur, "partTotal":size, "failed":self.failed, "calls":self.calls,
                "stage":self.stage, "error":self.error, "ocr":self.ocr, "retrying":len(self.retrying)}

    def message(self):
        f = self.snapshot()
        if self.stage == "ocr":
            return f"正在识别扫描页 {self.ocr[0]} / {self.ocr[1]}"
        if not self.parts:
            return "正在分析版面，正在统计片段…"
        if f["total"] is None:
            text = f"第 {self.part} / {self.count} 部分 · 本部分 {f['partCurrent']} / {f['partTotal']} · 全篇已处理 {f['current']}"
        else:
            text = f"已处理 {f['current']} / {f['total']} 个片段"
        if self.retrying:
            text += f" · {len(self.retrying)} 段正在重试"
        if self.failed:
            text += f" · {self.failed} 个片段失败"
        if self.stage == "typeset":
            text += " · 正在生成 PDF"
        return text
