"""Rebuild the paired XPI from a hash-pinned upstream checkout and its dependency lock."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from common import LOCK
from manage import download, unpack

def edit(root, file, replacements):
    p = root/file
    s = p.read_text("utf-8")
    for old, new in replacements:
        if s.count(old) != 1:
            raise ValueError(f"Upstream change in {file}: {old[:50]}")
        s = s.replace(old,new)
    p.write_text(s,encoding="utf-8",newline="\n")


def patch(p):
    shutil.copyfile(ROOT/"compat/frontend/codex.ts", p/"src/modules/codex.ts")
    edit(p,"addon/content/preferences.xhtml", [
        ('<html:option value="siliconflowfree"\n', '<html:option value="clitranslator">Codex（本机订阅）</html:option>\n                    <html:option value="siliconflowfree"\n'),
        ('        <!-- 设置翻译线程数、跳过最后几页、重命名 -->', '''        <vbox id="pdf2zh-codex-options" style="display:none">
            <hbox align="center"><html:label for="pdf2zh-codex-model">Codex 模型</html:label>
                <html:select id="pdf2zh-codex-model"/>
                <html:label for="pdf2zh-codex-effort">思考强度</html:label>
                <html:select id="pdf2zh-codex-effort"/>
                <html:button id="pdf2zh-codex-refresh">刷新模型</html:button>
            </hbox>
            <html:span id="pdf2zh-codex-status" role="status"/>
            <hbox align="center"><html:label for="pdf2zh-codex-subject">学科领域</html:label>
                <html:select id="pdf2zh-codex-subject"/>
            </hbox>
            <hbox id="pdf2zh-codex-subject-row" align="center" style="display:none">
                <html:label for="pdf2zh-codex-subject-custom">自定义领域</html:label>
                <html:input id="pdf2zh-codex-subject-custom" type="text" size="30"
                    aria-describedby="pdf2zh-codex-subject-preview"/>
            </hbox>
            <html:span id="pdf2zh-codex-subject-preview" role="status" aria-live="polite"
                style="display:none;max-width:38em;white-space:normal;overflow-wrap:anywhere"/>
        </vbox>
        <!-- 设置翻译线程数、跳过最后几页、重命名 -->''')])
    edit(p,"addon/prefs.js", [('pref("__prefsPrefix__.poolSize", 0);','pref("__prefsPrefix__.poolSize", 0);\npref("__prefsPrefix__.codexModel", "gpt-6.2-sol");\npref("__prefsPrefix__.codexEffort", "xhigh");\npref("__prefsPrefix__.codexSubjectChoice", "general");\npref("__prefsPrefix__.codexSubjectCustom", "");')])
    edit(p,"src/modules/preferenceScript.ts",[('export async function registerPrefsScripts','import {setupCodex} from "./codex";\n\nexport async function registerPrefsScripts'),('    bindPrefEvents();','    bindPrefEvents();\n    setupCodex(_window.document);')])
    edit(p,"src/modules/pdf2zhTypes.ts",[('    next_service: string;','    next_service: string;\n    codex?: ReturnType<typeof import("./codex").codexOptions>;')])
    edit(p,"src/modules/pdf2zhHelper.ts",[
        ('        for (const item of selectedItems) {','''        let batchConfig: ServerConfig;
        try {
            batchConfig = this.getServerConfig(endpoint === "translate");
        } catch (error) {
            ztoolkit.getGlobal("alert")(error instanceof Error ? error.message : String(error));
            return;
        }
        for (const item of selectedItems) {'''),
        ('                const config = this.getServerConfig();','                const config = { ...batchConfig };'),
        ('static getServerConfig(): ServerConfig','static getServerConfig(includeSubject=false): ServerConfig'),
        ('            serverUrl: getPref("new_serverip")','            ...(getPref("engine") === "pdf2zh_next" && getPref("next_service") === "clitranslator" ? {codex:codexOptions(includeSubject)} : {}),\n            serverUrl: getPref("new_serverip")'),
        ('            // 获取激活的 LLM API 配置','''            if (config.codex) {
                const capabilities = await catalog(config.serverUrl);
                const selection = config.codex;
                if (selection.subject) subjectPreview(selection.subject, capabilities.subjectContext);
                if (!capabilities.models.some(m=>m.id===selection.model && m.efforts.includes(selection.effort))) {
                    throw new Error("所选 Codex 模型或强度不可用，请在首选项刷新模型。");
                }
                if (!Number.isInteger(Number(config.poolSize)) || +config.poolSize < 0 || +config.poolSize > 20 ||
                    !Number.isInteger(Number(config.qps)) || +config.qps < 1 || +config.qps > 1000) {
                    throw new Error("Codex Worker 须在 0–20 之间，QPS 须在 1–1000 之间。");
                }
            }
            // 获取激活的 LLM API 配置'''),
        ('            if (llmApiConfig) {','            if (llmApiConfig && !config.codex) {'),
        ('            return result;\n        });\n    }\n\n    static parseServerPayload','            return result;\n        }, config.codex ? 1 : this.MAX_RETRIES);\n    }\n\n    static parseServerPayload'),
        ('    static getFileType(fileName: string): string {','    static getFileType(fileName: string): string {\n        fileName = fileName.replace(codexSuffix, "");'),
        ('                await this.fetchAndAttachPDF({','                await importOnce(response.taskId, item, fileName, () => this.fetchAndAttachPDF({'),
        ('                    attachKeys,\n                });\n                attached++;','                    attachKeys,\n                }));\n                attached++;'),
        ('            const fileType = this.getFileType(fileName);','            const product = response.products?.find((p:{name:string}) => p.name === fileName);\n            const fileType = product?.kind || this.getFileType(fileName);'),
        ('        const attachKey =','        const suffix = leafName.match(codexSuffix);\n        if (suffix) newTitle += " · "+suffix[1]+" / "+suffix[2];\n        const attachKey ='),
        ('        attachKeys.add(attachKey);','''        if (suffix && attachment.attachmentFilename !== leafName) {
            const renamed = await attachment.renameAttachmentFile(leafName);
            if (renamed !== true || attachment.attachmentFilename !== leafName) throw new Error("附件文件名校验失败");
        }
        attachKeys.add(attachKey);'''),
        ('message: String(task.message || task.status || ""),','message: fragmentText(task),'),
        ('            await Zotero.Promise.delay(1000);','            if (!task) onRunning?.({percent:0,message:"正在重新连接…"});\n            await Zotero.Promise.delay(1000);'),
        ('            onProgress?.({ phase: "file-done", fileName, endpoint });','''            const partial = (response as {partial?:boolean;message?:string});
            onProgress?.({ phase: "file-done", fileName, endpoint, detail: partial.partial ? partial.message : undefined });'''),
        ('        return text;\n    }','        return update.phase === "file-done" && update.detail ? text+" · "+update.detail : text;\n    }'),
    ])
    helper = p/"src/modules/pdf2zhHelper.ts"
    helper.write_text('import {catalog,codexOptions,codexSuffix,fragmentText,importOnce,subjectPreview} from "./codex";\n'+helper.read_text("utf-8"),encoding="utf-8",newline="\n")
    edit(p,"zotero-plugin.config.ts",[('buildVersion: pkg.version,','buildVersion: "'+LOCK["xpi_version"]+'",'),('buildTime: "{{buildTime}}"','buildTime: "2026-11-19"')])
    # Paired upgrades use Update.ps1. Independent Zotero updates never select the upstream XPI.
    edit(p,"addon/manifest.json",[('"__buildVersion__"',json.dumps(LOCK["xpi_version"])), ('"__updateURL__"', '"https://raw.githubusercontent.com/'+LOCK["repository"]+'/main/compat/xpi-updates.json"')])
    edit(p,"package.json",[('"addonName": "Zotero PDF2zh"','"addonName": "Zotero PDF2zh + Codex"')])


def build(p, out):
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    subprocess.run([npm,"run","build"],cwd=p,check=True)
    return pack(p/"build/addon",out)


def pack(addon, out):
    manifest = json.loads((addon/"manifest.json").read_bytes())
    app = manifest["applications"]["zotero"]
    if app["id"] != "pdf2zh@guaguastandup.com" or manifest["version"] != LOCK["server_version"]:
        raise ValueError("Unexpected upstream manifest")
    manifest["version"] = LOCK["xpi_version"]
    app["update_url"] = "https://raw.githubusercontent.com/"+LOCK["repository"]+"/main/compat/xpi-updates.json"
    manifest["homepage_url"] = "https://github.com/"+LOCK["repository"]
    out.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(out,"w") as z:
        for f in sorted(addon.rglob("*")):
            if f.is_file():
                info = zipfile.ZipInfo(f.relative_to(addon).as_posix(),(2026,1,1,0,0,0))
                data = json.dumps(manifest,ensure_ascii=False,indent=2).encode() if info.filename == "manifest.json" else f.read_bytes()
                z.writestr(info,data,compress_type=zipfile.ZIP_DEFLATED)
    print(out,hashlib.sha256(out.read_bytes()).hexdigest())


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--source",type=Path,help="Pristine extracted pinned plugin directory with npm ci complete")
    a.add_argument("--out",type=Path,default=ROOT/"compat/pdf2zh-codex.xpi")
    args = a.parse_args()
    if args.source:
        patch(args.source)
        build(args.source,args.out)
    else:
        with tempfile.TemporaryDirectory(prefix="zpc-build-") as temp:
            base=Path(temp)
            archive=base/"source.zip"
            download("https://codeload.github.com/"+LOCK["upstream"]+"/zip/"+LOCK["commit"],archive,LOCK["source_zip_sha256"])
            unpack(archive,base)
            source=next(base.glob("*/plugin"))
            subprocess.run([shutil.which("npm.cmd") or "npm","ci","--no-audit","--no-fund"],cwd=source,check=True)
            patch(source)
            build(source,args.out)
