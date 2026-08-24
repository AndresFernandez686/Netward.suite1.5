import ast
import json
import pathlib
import re

files = [pathlib.Path("app.py"), *pathlib.Path("core").rglob("*.py")]
routes = []
for path in files:
    try:
        text = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(text)
    except Exception:
        continue
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                continue
            if decorator.func.attr not in ("route", "get", "post", "put", "patch", "delete"):
                continue
            if not decorator.args or not isinstance(decorator.args[0], ast.Constant):
                continue
            route_path = decorator.args[0].value
            methods = [decorator.func.attr.upper()] if decorator.func.attr != "route" else ["GET"]
            for keyword in decorator.keywords:
                if keyword.arg == "methods" and isinstance(keyword.value, (ast.List, ast.Tuple)):
                    methods = [item.value for item in keyword.value.elts if isinstance(item, ast.Constant)]
            source = ast.get_source_segment(text, node) or ""
            forms = sorted(set(re.findall(r"request\.form\.get(?:list)?\(['\"]([^'\"]+)", source)))
            args = sorted(set(re.findall(r"request\.args\.get\(['\"]([^'\"]+)", source)))
            uploads = sorted(set(re.findall(r"request\.files\.get\(['\"]([^'\"]+)", source)))
            routes.append({
                "file": str(path), "line": node.lineno, "path": route_path,
                "methods": methods, "name": node.name, "forms": forms,
                "args": args, "files": uploads, "json": "request.get_json" in source,
            })
pathlib.Path("tmp/routes.json").write_text(json.dumps(routes, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"ROUTES {len(routes)} OPERATIONS {sum(len(route['methods']) for route in routes)}")
