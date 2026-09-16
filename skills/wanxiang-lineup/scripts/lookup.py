"""Read-only source lookup. No card interpretation or lineup ranking."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

SKILL = Path(__file__).resolve().parents[1]
FILES = {
    "hero": ["documents/王者万象棋_英雄牌.json"],
    "effect": ["documents/王者万象棋_效果牌.json"],
    "talent": ["documents/王者万象棋_天赋牌.json"],
    "equipment": ["documents/王者万象棋_装备牌.json"],
    "player": ["documents/王者万象棋棋手详情.json"],
    "build": ["references/官方推荐阵容_5套.json",
              "references/热门推荐阵容_20套.json",
              "references/综合推荐_瑶妹日落海艾琳.json"],
}
TEXT_FILES = ["documents/王者万象棋规则说明.md", "documents/补充说明.md",
              "documents/王者万象棋_英雄成长与属性值关系.md",
              "documents/王者万象棋_英雄技能强化一览.md",
              "documents/王者万象棋_召唤物基础数值与成长.md",
              "documents/王者万象棋_攻击数值与抗性计算关系.md"]


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def resolve_root(explicit=None):
    if explicit:
        root = Path(explicit).expanduser().resolve()
    else:
        config = read_json(SKILL / "source_config.json")
        configured = Path(config["data_root"]).expanduser()
        root = (configured if configured.is_absolute() else SKILL / configured).resolve()
    if not root.is_dir():
        raise ValueError(f"资料目录不存在：{root}；请传 --root")
    return root


def rows(data):
    if isinstance(data, list):
        pairs = [(f"/{i}", row) for i, row in enumerate(data)]
    elif isinstance(data, dict) and "name" in data:
        pairs = [("", data)]
    elif isinstance(data, dict):
        pairs = [("/" + str(k).replace("~", "~0").replace("/", "~1"), row)
                 for k, row in data.items()]
    else:
        raise ValueError("不支持的顶层资料结构")
    if any(not isinstance(row, dict) for _, row in pairs):
        raise ValueError("记录必须是对象")
    return pairs


def names(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"名称", "棋手名称", "name"} and isinstance(item, str):
                yield item
            yield from names(item)
    elif isinstance(value, list):
        for item in value:
            yield from names(item)


def identity(row):
    return str(row.get("卡牌ID", row.get("棋手ID", row.get("key", ""))))


def inventory(root):
    result = []
    for kind, paths in {**FILES, "rules": TEXT_FILES}.items():
        for rel in paths:
            path = root / rel
            if not path.is_file():
                result.append({"kind": kind, "source": rel, "missing": True})
                continue
            raw = path.read_bytes()
            item = {"kind": kind, "source": rel, "sha256": hashlib.sha256(raw).hexdigest(),
                    "bytes": len(raw)}
            if path.suffix == ".json":
                item["records"] = len(rows(read_json(path)))
            result.append(item)
    return {"root": str(root), "files": result}


def query(root, args):
    matches, missing = [], []
    for kind, paths in FILES.items():
        if args.kind not in {"all", kind}:
            continue
        for rel in paths:
            path = root / rel
            if not path.is_file():
                missing.append(rel)
                continue
            for pointer, row in rows(read_json(path)):
                if args.id is not None and identity(row) != args.id:
                    continue
                if args.name is not None and args.name not in set(names(row)):
                    continue
                if args.contains is not None and args.contains not in json.dumps(row, ensure_ascii=False):
                    continue
                matches.append({"kind": kind, "source": str(path), "pointer": pointer,
                                "id": identity(row), "record": row})
    return {"root": str(root), "count": len(matches), "missing_sources": missing, "matches": matches}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="可选外部资料根目录，须含 documents/references；默认使用skill内data")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inventory", help="数量与指纹")
    q = sub.add_parser("query", help="完整父记录；名称可匹配预览/关联子卡")
    q.add_argument("--kind", choices=["all", *FILES], default="all")
    q.add_argument("--name", help="精确名称，不猜别名")
    q.add_argument("--id", help="顶层记录ID/key；不会静默选择同ID的其他类型")
    q.add_argument("--contains", help="全文包含；与其他过滤条件取交集")
    args = parser.parse_args()
    if args.command == "query" and not any(v is not None for v in (args.name, args.id, args.contains)):
        parser.error("query 需要 --name / --id / --contains 中至少一个")
    try:
        root = resolve_root(args.root)
        result = inventory(root) if args.command == "inventory" else query(root, args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.command == "query" and not result["count"]:
            return 1
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"资料读取失败：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
