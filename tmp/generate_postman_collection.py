import ast
import json
import pathlib
import re

root = pathlib.Path('.')
out = root / 'postman/collections/Netward HTTP API'
out.mkdir(parents=True, exist_ok=True)
for old in out.rglob('*.request.yaml'):
    old.unlink()

folders = {
    'authentication-session': 'Authentication and session',
    'employee-inventory': 'Employee inventory',
    'admin-management': 'Admin management',
    'periods-auditing': 'Periods and auditing',
    'exports': 'Exports',
    'document-excel-pdf-workflows': 'Document, Excel and PDF workflows',
}
for dirname, name in folders.items():
    folder = out / dirname
    (folder / '.resources').mkdir(parents=True, exist_ok=True)
    (folder / '.resources/definition.yaml').write_text(
        f'$kind: collection\nname: {name}\n', encoding='utf-8'
    )

(out / '.resources').mkdir(exist_ok=True)
(out / '.resources/definition.yaml').write_text(
    "$kind: collection\nname: Netward HTTP API\nvariables:\n"
    "  - key: baseUrl\n    value: 'http://localhost:5000'\n",
    encoding='utf-8',
)

operations = []
for source_name in ['app.py', 'core/inventario.py']:
    source = pathlib.Path(source_name).read_text(encoding='utf-8-sig')
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == 'route'
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
            ):
                continue
            route = decorator.args[0].value
            methods = ['GET']
            for keyword in decorator.keywords:
                if keyword.arg == 'methods' and isinstance(keyword.value, (ast.List, ast.Tuple)):
                    methods = [item.value for item in keyword.value.elts if isinstance(item, ast.Constant)]
            body = ast.get_source_segment(source, node) or ''
            form = sorted(set(re.findall(r'request\.form(?:\.get)?\(\s*["\']([^"\']+)', body)))
            files = sorted(set(re.findall(r'request\.files(?:\.get)?\(\s*["\']([^"\']+)', body)))
            args = sorted(set(re.findall(r'request\.args(?:\.get)?\(\s*["\']([^"\']+)', body)))
            json_keys = []
            if 'request.get_json' in body or 'request.json' in body:
                json_keys = sorted(set(re.findall(r'(?:data|payload|body)\.get\(\s*["\']([^"\']+)', body)))
            for method in methods:
                operations.append((route, method, form, files, args, json_keys))

def choose_folder(route):
    if route in ['/', '/login', '/logout']:
        return 'authentication-session'
    if route.startswith('/empleado/'):
        return 'employee-inventory'
    if any(token in route for token in ['/export', '/reporte']):
        return 'exports'
    if any(token in route for token in ['/desc', '/documentacion/', '/excel', '/pdf']):
        return 'document-excel-pdf-workflows'
    if any(token in route for token in ['/periodos', '/auditoria', '/justificar/', '/revisar/']):
        return 'periods-auditing'
    return 'admin-management'

def safe_stem(route):
    value = re.sub(r'<(?:int:)?([^>]+)>', r'by-\1', route.strip('/')) or 'root'
    return re.sub(r'[^A-Za-z0-9._ -]+', '-', value).replace('/', ' - ')

for index, (route, method, form, files, args, json_keys) in enumerate(operations, 1):
    folder = out / choose_folder(route)
    path = folder / f'{index:03d} {method} {safe_stem(route)}.request.yaml'
    url_route = re.sub(r'<(?:int:)?([^>]+)>', r'{{\1}}', route)
    lines = [
        '$kind: http-request',
        f"name: '{method} {route}'",
        f'method: {method}',
        f"url: '{{{{baseUrl}}}}{url_route}'",
        f'order: {index * 1000}',
    ]
    path_vars = re.findall(r'<(?:int:)?([^>]+)>', route)
    if path_vars:
        lines.append('pathVariables:')
        for key in path_vars:
            lines.extend([f'  - key: {key}', "    value: '1'"])
    if args:
        lines.append('queryParams:')
        for key in args:
            lines.extend([f'  - key: {key}', "    value: ''"])
    if method in ('POST', 'PUT', 'PATCH'):
        if files:
            lines.extend(['body:', '  type: formdata', '  content:'])
            for key in form:
                lines.extend([f'    - key: {key}', '      type: text', "      value: ''"])
            for key in files:
                lines.extend([f'    - key: {key}', '      type: file', "      src: ''"])
        elif json_keys:
            payload = {key: '' for key in json_keys}
            content = json.dumps(payload, ensure_ascii=False, indent=2)
            lines.extend([
                'headers:', '  - key: Content-Type', '    value: application/json',
                'body:', '  type: json', '  content: |-'
            ])
            lines.extend('    ' + line for line in content.splitlines())
        elif form:
            lines.extend(['body:', '  type: urlencoded', '  content:'])
            for key in form:
                lines.extend([f'    - key: {key}', "      value: ''"])
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')

print(json.dumps({
    'operations': len(operations),
    'request_files': len(list(out.rglob('*.request.yaml'))),
    'collection': str(out.resolve()),
}))
