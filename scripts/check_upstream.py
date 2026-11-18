"""Report new upstream releases and detect changes to the installed baseline."""
import json
import os
from pathlib import Path
import re
import tomllib
from urllib.parse import quote
from urllib.request import Request, urlopen


def inspect(config, get):
    tag = config["tag"]
    pinned = get("releases/tags/" + quote(tag, safe=""))
    pinned_commit = get("commits/" + quote(tag, safe=""))["sha"]
    if pinned_commit != config["commit"]:
        raise ValueError(f"Upstream moved {tag} from {config['commit']} to {pinned_commit}")
    pinned_assets = {a["name"]: a.get("digest") for a in pinned["assets"]}
    for name, value in config["assets"].items():
        if pinned_assets.get(name) != "sha256:" + value:
            raise ValueError(f"Upstream changed or removed {name} in {tag}")

    latest = get("releases/latest")
    result = [f"Verified upstream {tag} at `{pinned_commit}` and its release assets."]
    if latest["tag_name"] == tag:
        return result + ["The installed baseline matches the latest release."]

    candidate = latest["tag_name"]
    commit = get("commits/" + quote(candidate, safe=""))["sha"]
    result.append(f"Candidate [{candidate}]({latest['html_url']}) at `{commit}`.")
    assets = {a["name"]: a.get("digest") for a in latest["assets"]}
    for name in config["assets"]:
        digest = assets.get(name) or ""
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise ValueError(f"Candidate {candidate} is missing {name} or its SHA-256")
        result.append(f"- `{name}` `{digest}`")
    return result


def main():
    lock = Path(__file__).resolve().parents[1] / "compat/upstream.lock.toml"
    config = tomllib.loads(lock.read_text("utf-8"))
    headers = {"User-Agent": "Zotero-PDF2zh-Codex"}
    if token := os.environ.get("GH_TOKEN"):
        headers["Authorization"] = "Bearer " + token

    def get(suffix):
        url = f"https://api.github.com/repos/{config['upstream']}/{suffix}"
        with urlopen(Request(url, headers=headers), timeout=30) as response:
            return json.load(response)

    report = "\n".join(inspect(config, get))
    print(report)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as output:
            print(report, file=output)


if __name__ == "__main__":
    main()
