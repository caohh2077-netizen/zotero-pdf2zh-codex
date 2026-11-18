"""Read-only upstream release detection. Never edit the installed package."""
import json
from pathlib import Path
import sys
import tomllib
from urllib.request import urlopen
config=tomllib.loads((Path(__file__).resolve().parents[1]/"compat/upstream.lock.toml").read_text("utf-8"))
def get(suffix):
    with urlopen("https://api.github.com/repos/"+config["upstream"]+"/"+suffix,timeout=25) as r:
        return json.load(r)
latest=get("releases/latest")
pinned=get("releases/tags/"+config["tag"])
assets={f["name"]:f.get("digest") for f in pinned["assets"]}
if any(assets.get(name)!="sha256:"+value for name,value in config["assets"].items()):
    sys.exit("Pinned upstream asset digest changed; inspect before updating.")
print("Installed baseline:",config["tag"],"| Latest:",latest["tag_name"],"| Candidate:",latest["tag_name"]!=config["tag"])
