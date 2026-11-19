"""End-to-end candidate checks using only original synthetic PDFs and a loopback endpoint."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from urllib.request import ProxyHandler, Request, build_opener

import pymupdf

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"fixtures"))
from sample import make


def fixture(path, kind):
    if kind=="text":
        make(path)
        return
    with pymupdf.open() as doc:
        if kind=="mixed":
            doc.new_page().insert_text((60,90),"The native page reports 12 samples.",fontsize=16)
        with pymupdf.open() as paper:
            page=paper.new_page(width=595,height=842)
            page.insert_text((60,95),"The experiment measured 23.5 degrees Celsius.",fontsize=16)
            page.insert_text((60,148),"The sample temperature remained stable.",fontsize=16)
            page.insert_text((60,199),"Scientists repeated the measurement.",fontsize=16)
            pix=page.get_pixmap(dpi=160)
            if kind=="ocr-layer":
                with pymupdf.open("pdf",pix.pdfocr_tobytes(language="eng",tessdata=str(TESSDATA))) as layer:
                    doc.insert_pdf(layer)
            else:
                out=doc.new_page(width=595,height=842)
                out.insert_image(out.rect,pixmap=pix)
        doc.save(path)


class Server:
    def __init__(self,port):
        self.base=f"http://127.0.0.1:{port}"
        self.op=build_opener(ProxyHandler({}))

    def call(self,path,data=None):
        payload=json.dumps(data).encode() if data is not None else None
        req=Request(self.base+path,data=payload,headers={"Content-Type":"application/json"})
        with self.op.open(req,timeout=25) as res:
            return json.load(res)

    def run(self,path,model,effort,label):
        data=path.read_bytes()
        digest=hashlib.sha256(data).digest()
        task=self.call("/translate",dict(fileName="并行测试论文.pdf",fileContent=base64.b64encode(data).decode(),
            engine="pdf2zh_next",next_service="clitranslator",sourceLang="en",targetLang="zh-CN",qps=10,poolSize=10,
            codex={"protocol":2,"model":model,"effort":effort},asyncJob=True,autoOcr=True,disableGlossary=True,
            noMono=True,noDual=False,mono=False,dual=True,dualMode="LR",noWatermark=True))
        ident=task["taskId"]
        timeline=[]
        end=time.monotonic()+1000
        while time.monotonic()<end:
            rows=self.call("/api/tasks")["tasks"]
            row=next((r for r in rows if r["taskId"]==ident),None)
            if not row:
                row=next((r for r in self.call("/api/history")["history"] if r["taskId"]==ident),None)
            if row:
                f=row.get("fragments",{})
                point=[f.get("stage"),f.get("current"),f.get("total"),f.get("failed"),f.get("calls")]
                if not timeline or timeline[-1]!=point:
                    timeline.append(point)
                if row.get("finished"):
                    if row.get("error"):
                        raise RuntimeError(label+" "+str(row["error"])+" "+str(timeline))
                    result=row["result"]
                    file=Path(result["filePaths"][0])
                    assert file.name.endswith(".LR_dual__"+model+"__"+effort+".pdf"),file.name
                    assert result["products"][0]["kind"]=="dual"
                    with pymupdf.open(file) as doc:
                        text=[p.get_text() for p in doc]
                        pages=len(doc)
                        if label in ("scan","mixed","ocr-layer"):
                            # Compare ink masks: untranslated bitmap letters remaining
                            # underneath Chinese glyphs cause high overlap.
                            import numpy as np
                            pix=doc[-1].get_pixmap(colorspace=pymupdf.csGRAY)
                            bitmap=np.frombuffer(pix.samples,dtype="uint8").reshape(pix.height,pix.width)
                            half=pix.width//2
                            original=bitmap[:,:half]<160
                            translated=bitmap[:,half:half*2]<160
                            overlap=(original & translated).sum()/max(1,original.sum())
                            assert overlap<.55,(label,"source ink remains under translation",float(overlap))
                    assert all(re.search(r"[\u3400-\u9fff]",p) for p in text),(label,"missing translated page",file)
                    assert "23.5" in "".join(text),(label,"missing number")
                    assert hashlib.sha256(path.read_bytes()).digest()==digest
                    assert f["total"] is not None and f["current"]==f["total"] and f["failed"]==0,(label,f)
                    result={"case":label,"model":model,"effort":effort,"pages":pages,"fragments":f,
                            "timeline":timeline,"filename":file.name}
                    print(json.dumps(result,ensure_ascii=False),flush=True)
                    return result
            time.sleep(.35)
        raise TimeoutError(label)


if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("--port",type=int,default=18890)
    a.add_argument("--work",type=Path,required=True)
    a.add_argument("--tessdata",type=Path,required=True)
    a.add_argument("--cases",nargs="+",choices=["text","hot","scan","mixed","ocr-layer","models"],
                   default=["text","hot","scan","mixed","ocr-layer","models"])
    args=a.parse_args()
    args.work.mkdir(parents=True,exist_ok=True)
    TESSDATA=args.tessdata
    server=Server(args.port)
    assert server.call("/health")["codexProtocol"]==2
    cases=[]
    for case in args.cases:
        if case=="models":
            path=args.work/"text.pdf"
            if not path.exists():fixture(path,"text")
            with ThreadPoolExecutor(2) as ex:
                futures=[ex.submit(server.run,path,m,e,"same-name-"+m) for m,e in
                         [("gpt-6.2-sol","low"),("gpt-6.2-astra","low")]]
                cases.extend(f.result() for f in futures)
            continue
        kind="text" if case=="hot" else case
        path=args.work/(kind+".pdf")
        if not path.exists():
            fixture(path,kind)
        r=server.run(path,"gpt-6.2-sol","xhigh",case)
        cases.append(r)
        if case=="hot":
            assert r["fragments"]["calls"]==0,r
    (args.work/"report.json").write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding="utf-8")
