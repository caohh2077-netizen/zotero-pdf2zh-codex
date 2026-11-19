"""Run 24 paired, synthetic terminology samples and export a shuffled grading sheet."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import random
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from adapter.codex_translate import translate
from common import read
from options import SUBJECT_PRESETS, subject_prefix

# Source, target concept, acceptable Chinese renderings. Freeze before collecting responses.
CASES = {
    "ai-ml": [
        ("The Transformer shares weights across 4 layers [1].", "Transformer", "Transformer / Transformer 模型 / Transformer 架构"),
        ("Policy rollouts provide 8 trajectories per batch.", "policy rollouts", "策略展开 / 策略滚动 / 策略采样 / 用策略生成或采样轨迹"),
        ("Embodied intelligence emerges from perception and action in the physical world.", "embodied intelligence", "具身智能"),
        ("The embodied agent uses touch to correct its grasp [2].", "embodied agent", "具身智能体 / 具身代理（体）"),
        ("A single attention head assigns high weight to the final token.", "attention head", "注意力头"),
        ("The ablation isolates the effect of the visual encoder.", "ablation", "消融 / 消融实验"),
    ],
    "electrical-power": [
        ("The transformer has two windings and is rated at 50 Hz.", "transformer", "变压器"),
        ("The relay tripped the breaker within 20 ms [3].", "tripped the breaker", "使断路器跳闸 / 跳开、断开或分闸断路器"),
        ("The feeder supplies three rural substations.", "feeder", "馈线 / 馈电线路"),
        ("The bus voltage remained at 10 kV under load.", "bus", "母线 / 汇流排"),
        ("The protection zone ends at the current transformer.", "current transformer", "电流互感器"),
        ("The line has a lagging power factor of 0.85.", "lagging power factor", "滞后功率因数 / 功率因数滞后"),
    ],
    "bioinformatics": [
        ("The alignment contains gaps near the end of the sequence.", "alignment", "比对 / 序列比对 / 序列对齐"),
        ("Reads shorter than 75 bases were excluded [4].", "reads", "读段 / 测序读长或序列 / 短读序列"),
        ("The assembly contains 12 contigs.", "contigs", "重叠群 / 连续序列 / contig"),
        ("The reference genome has an average coverage of 30×.", "coverage", "覆盖度 / 覆盖深度 / 测序深度 / 覆盖倍数"),
        ("This motif occurs twice in the reference sequence.", "motif", "基序 / 模体"),
        ("Each locus received a unique identifier in the table.", "locus", "位点 / 基因座 / 座位"),
    ],
    "materials": [
        ("Residual stress increased after the coating cooled.", "residual stress", "残余应力 / 残留应力"),
        ("The yield strength of the alloy was 350 MPa [5].", "yield strength", "屈服强度"),
        ("Grain boundaries impede the motion of dislocations.", "dislocations", "位错"),
        ("The interface showed creep under a constant load.", "creep", "蠕变"),
        ("The strain was measured at 25 °C using optical markers.", "strain", "应变"),
        ("The specimen exhibited necking before fracture.", "necking", "颈缩 / 缩颈"),
    ],
}


def collect(settings_path, out, model, effort, workers):
    out.mkdir(parents=True, exist_ok=False)
    jobs = [(field, case, arm) for field, cases in CASES.items() for case in cases for arm in ("general", "field")]
    random.SystemRandom().shuffle(jobs)
    key = {}
    with tempfile.TemporaryDirectory(prefix="zpc-study-") as work:
        settings = dict(read(settings_path), root=work)
        (Path(work) / "managed/state").mkdir(parents=True)
        with ThreadPoolExecutor(max_workers=workers) as executor, (out / "blind.jsonl").open("x", encoding="utf-8") as sheet:
            futures = {}
            for index, (field, case, arm) in enumerate(jobs, 1):
                ident = f"S{index:02}"
                key[ident] = {"field": field, "arm": arm}
                prefix = subject_prefix(SUBJECT_PRESETS[field][1]) if arm == "field" else ""
                future = executor.submit(translate, settings, "en", "zh-CN", case[0], model, effort, prefix=prefix)
                futures[future] = (ident, case)
            (out / "key.json").write_text(json.dumps(key, indent=2), encoding="utf-8")
            for completed, future in enumerate(as_completed(futures), 1):
                ident, (source, term, accepted) = futures[future]
                row = dict(id=ident, source=source, term=term, accepted=accepted)
                try:
                    row["translation"] = future.result()
                except Exception as exc:
                    row["error"] = str(exc)
                sheet.write(json.dumps(row, ensure_ascii=False) + "\n")
                sheet.flush()
                print(f"{completed}/{len(jobs)}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--settings", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--model", default="gpt-6.2-sol")
    parser.add_argument("--effort", default="xhigh")
    parser.add_argument("--workers", type=int, choices=range(1, 21), default=10)
    args = parser.parse_args()
    collect(args.settings, args.out, args.model, args.effort, args.workers)
