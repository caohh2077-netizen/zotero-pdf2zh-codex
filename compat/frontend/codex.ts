import {getPref, setPref} from "../utils/prefs";

type Model = {id:string; name:string; efforts:string[]; default:string};
type Catalog = {protocol:number; models:Model[]; source:string; error?:string};
export const codexSuffix = /__([a-zA-Z0-9._-]+?)__(none|minimal|low|medium|high|xhigh|max|ultra)(?=\.pdf$)/i;

export function codexOptions() {
    return {protocol:2, model:String(getPref("codexModel") || "gpt-6.2-sol"),
            effort:String(getPref("codexEffort") || "xhigh")};
}

export async function catalog(server:string, refresh=false):Promise<Catalog> {
    const url = new URL(server);
    if (url.protocol !== "http:" || !["localhost","127.0.0.1","[::1]"].includes(url.hostname))
        throw new Error("Codex 需要本机回环服务器地址。");
    const res = await fetch(url.origin + "/api/codex/capabilities" + (refresh ? "?refresh=1" : ""), {cache:"no-store"});
    if (!res.ok) throw new Error(((await res.json().catch(()=>({}))) as {error?:string}).error || "请检查配套的本机 Codex 后端。");
    const data = await res.json() as unknown as Catalog;
    if (data.protocol !== 2 || !Array.isArray(data.models)) throw new Error("Codex 前后端版本不匹配。");
    return data;
}

export function setupCodex(doc:Document) {
    const el = (id:string) => doc.getElementById(id)!;
    const model = el("pdf2zh-codex-model") as HTMLSelectElement;
    const effort = el("pdf2zh-codex-effort") as HTMLSelectElement;
    const box = el("pdf2zh-codex-options");
    const status = el("pdf2zh-codex-status");
    const field = (name:string) => el("zotero-prefpane-pdf2zh-"+name) as HTMLInputElement;
    let models:Model[] = [], generation = 0;
    function list(control:HTMLSelectElement, values:Array<[string,string]>, selected:string) {
        control.replaceChildren();
        if (!values.some(([id])=>id === selected)) values.unshift([selected, selected+"（待确认）"]);
        for (const [id,label] of values) {
            const option = doc.createElementNS("http://www.w3.org/1999/xhtml","option") as HTMLOptionElement;
            option.value = id;
            option.textContent = label;
            control.appendChild(option);
        }
        control.value = selected;
    }
    function setEfforts(changed=false) {
        const current = models.find(m=>m.id === model.value);
        let chosen = codexOptions().effort;
        if (changed && current && !current.efforts.includes(chosen)) {
            chosen = current.default;
            setPref("codexEffort", chosen);
        }
        list(effort,(current?.efforts || []).map(e=>[e,e]), chosen);
        return !!current?.efforts.includes(chosen);
    }
    async function update(refresh=false) {
        const n = ++generation;
        const visible = String(getPref("engine")) === "pdf2zh_next" && String(getPref("next_service")) === "clitranslator";
        box.style.display = visible ? "" : "none";
        const workers = field("poolSize");
        if (visible) {workers.min="0";workers.max="20";} else {workers.removeAttribute("max");}
        if (!visible) return;
        list(model, [], codexOptions().model);
        setEfforts();
        status.textContent = "正在读取账户模型…";
        try {
            const data = await catalog(String(getPref("new_serverip")),refresh);
            if (n !== generation) return;
            models = data.models;
            list(model, models.map(m=>[m.id,m.name]), codexOptions().model);
            status.textContent = setEfforts() ? "" : "上次选择在当前目录中不可用，请重新选择。";
        } catch(error) {
            if (n === generation) status.textContent = String(error);
        }
    }
    for (const name of ["engine","engineSelect","next_service","next_serviceSelect","new_serverip"]) {
        field(name)?.addEventListener("change",()=>setTimeout(()=>void update(),0));
    }
    model.addEventListener("change",()=>{setPref("codexModel",model.value);setEfforts(true);status.textContent="";});
    effort.addEventListener("change",()=>{setPref("codexEffort",effort.value);status.textContent="";});
    el("pdf2zh-codex-refresh").addEventListener("click",()=>void update(true));
    void update();
}

export function fragmentText(task:Record<string,unknown>):string {
    const f = task.fragments as {current:number; total:number|null; part:number; parts:number; partCurrent:number;
                                 partTotal:number|null; stage:string; failed:number} | undefined;
    if (!f || f.stage === "ocr") return String(task.message || task.status || "");
    if (f.stage === "analysis") return "正在分析版面，正在统计片段…";
    const text = f.total == null ? "第 "+f.part+" / "+f.parts+" 部分 · 本部分 "+f.partCurrent+" / "+f.partTotal+" · 全篇已处理 "+f.current :
                 "已处理 "+f.current+" / "+f.total+" 个片段";
    return text + (f.failed ? " · "+f.failed+" 个片段失败" : "") + (f.stage === "typeset" ? " · 正在生成 PDF" : "");
}

const importing = new Map<string,Promise<void>>();
function receipts():string[] {
    try {
        const data:unknown = JSON.parse(String(getPref("codexImportReceipts") || "[]"));
        return Array.isArray(data) ? data.filter(k=>typeof k === "string") : [];
    } catch { return []; }
}

export async function importOnce(task:unknown, item:Zotero.Item, name:string, attach:()=>Promise<unknown>) {
    if (typeof task !== "string" || !task) { await attach(); return; }
    const key = JSON.stringify([task,item.libraryID,item.key,name]);
    if (receipts().includes(key)) return;
    const active = importing.get(key);
    if (active) return active;
    const work = (async()=>{
        await attach();
        setPref("codexImportReceipts",JSON.stringify([...receipts(),key].slice(-1500)));
    })();
    importing.set(key,work);
    try { await work; } finally { importing.delete(key); }
}
