"""Validate and sum human/agent judgments. Does not score heroes or simulate combat."""
import argparse
import json
import math
from pathlib import Path
import sys

DEFAULT_WEIGHTS = {"damage": 20, "survival": 20, "growth": 15, "access": 15,
                   "economy": 10, "matchup": 10, "flexibility": 5, "finish": 5}
DIMENSIONS = set(DEFAULT_WEIGHTS)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def number(value, label, minimum=0, maximum=100):
    require(isinstance(value, (int, float)) and not isinstance(value, bool), f"{label} 必须是数字")
    require(math.isfinite(value) and minimum <= value <= maximum, f"{label} 超出范围或非有限数")


def weights(value, label):
    require(isinstance(value, dict) and set(value) == DIMENSIONS, f"{label} 必须包含全部8个维度")
    for key, val in value.items():
        number(val, f"{label}.{key}")
    require(math.isclose(sum(value.values()), 100, abs_tol=1e-8), f"{label} 合计必须为100")
    return value


def validate(data):
    require(isinstance(data, dict), "账本必须为对象")
    require(data.get("rubric") == "wxq-rubric-1", "rubric 必须为 wxq-rubric-1")
    scenario = data.get("scenario")
    require(isinstance(scenario, dict), "缺 scenario")
    for field in ("id", "stage", "budget", "opponents", "calibration"):
        require(nonempty(scenario.get(field)), f"缺 scenario.{field}")
    assumptions = scenario.get("assumptions")
    require(isinstance(assumptions, list) and all(nonempty(a) for a in assumptions), "assumptions 必须为文字列表")
    evidence = data.get("evidence")
    require(isinstance(evidence, dict) and evidence, "缺证据字典")
    for key, item in evidence.items():
        require(nonempty(key) and isinstance(item, dict), "证据条目格式错误")
        require(nonempty(item.get("source")) and nonempty(item.get("claim")), f"证据{key}缺source/claim")
    main_weights = weights(data.get("weights", DEFAULT_WEIGHTS), "weights")
    variants = data.get("sensitivity_weights", {})
    require(isinstance(variants, dict), "sensitivity_weights 必须为对象")
    for label, value in variants.items():
        require(nonempty(label), "权重方案名称不能为空")
        weights(value, label)
    lineups = data.get("lineups")
    require(isinstance(lineups, list) and lineups, "缺方案列表")
    seen = set()
    for row in lineups:
        require(isinstance(row, dict), "方案必须为对象")
        rid = row.get("id")
        require(nonempty(rid), "方案缺id")
        require(rid not in seen, f"方案ID重复：{rid}")
        seen.add(rid)
        require(nonempty(row.get("label")), f"{rid}缺label")
        require(row.get("legality") in {"pass", "conditional", "fail"}, f"{rid}合法性状态错误")
        constraints = row.get("constraints")
        require(isinstance(constraints, list) and constraints and all(nonempty(x) for x in constraints),
                f"{rid}缺约束说明")
        if row["legality"] == "fail":
            continue
        dims = row.get("dimensions")
        require(isinstance(dims, dict) and set(dims) == DIMENSIONS, f"{rid}必须人工填写全部8维度")
        for key, dim in dims.items():
            require(isinstance(dim, dict), f"{rid}.{key}必须为对象")
            for level in ("low", "base", "high"):
                number(dim.get(level), f"{rid}.{key}.{level}", 0, 5)
            require(dim["low"] <= dim["base"] <= dim["high"], f"{rid}.{key}区间顺序错误")
            refs = dim.get("evidence")
            require(isinstance(refs, list) and refs and all(nonempty(r) and r in evidence for r in refs),
                    f"{rid}.{key}存在缺失证据引用")
            require(nonempty(dim.get("reason")), f"{rid}.{key}缺评分解释")
    baseline = data.get("baseline")
    require(nonempty(baseline) and baseline in seen, "baseline 必须引用现有方案")
    require(next(row for row in lineups if row["id"] == baseline)["legality"] != "fail", "基线不可非法")
    return main_weights, variants


def totals(row, weight):
    return {level: sum(weight[key] * row["dimensions"][key][level] / 5 for key in weight)
            for level in ("low", "base", "high")}


def summarize(data, weight):
    baseline = next(row for row in data["lineups"] if row["id"] == data["baseline"])
    b = totals(baseline, weight)
    result = []
    for row in data["lineups"]:
        item = {key: row[key] for key in ("id", "label", "legality")}
        if row["legality"] == "fail":
            item.update({"excluded": True, "constraints": row["constraints"]})
        else:
            t = totals(row, weight)
            item["score"] = {k: round(v, 2) for k, v in t.items()}
            if row["id"] != data["baseline"]:
                item["delta_base"] = round(t["base"] - b["base"], 2)
                item["delta_envelope"] = [round(t["low"] - b["high"], 2), round(t["high"] - b["low"], 2)]
        result.append(item)
    return result


def evaluate(data):
    weight, variants = validate(data)
    historical = data.get("assessment_status") == "historical_requires_reassessment"
    return {
        "assessment_status": data.get("assessment_status", "unversioned"),
        "revision_note": data.get("revision_note", ""),
        "rubric": data["rubric"], "scenario": data["scenario"], "baseline": data["baseline"],
        "notice": ("历史试评：资料已更新，分值尚未重评，不可作为当前推荐。" if historical else "") +
                  "理论判断的算术汇总；合法性与证据语义由填写者判断。区间为情景包络，不是胜率或置信区间。未排序。",
        "weights": weight, "lineups": summarize(data, weight),
        "sensitivity": {name: {"weights": w, "lineups": summarize(data, w)} for name, w in variants.items()}
    }


def reject_constant(value):
    raise ValueError(f"不接受非有限JSON数值：{value}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path)
    args = parser.parse_args()
    try:
        data = json.loads(args.ledger.read_text(encoding="utf-8-sig"), parse_constant=reject_constant)
        print(json.dumps(evaluate(data), ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (OSError, ValueError, TypeError) as exc:
        print(f"评分账本无效：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
