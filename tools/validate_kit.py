"""Validate portable files and references, never connections or translation quality."""
from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote

TEXT_SUFFIXES = {'.md', '.txt', '.json', '.csv', '.py', '.yml'}
PRIVATE_TARGET = re.compile(r'https://(?:drive\.google\.com/drive/folders/|drive\.google\.com/file/d/|docs\.google\.com/spreadsheets/d/)[A-Za-z0-9_-]{12,}')
CREDENTIAL = re.compile(r'(?:gh[pousr]_|github_pat_|sk-(?:proj-|or-)?)[A-Za-z0-9_-]{16,}')
HOST_PATH = re.compile(r'(?i)[CD]:[/\\](?:Users|Workspaces)[/\\]')
REFERENCE = re.compile(r'(?<!!)\[[^\]]*\]\(([^\s)]+)\)')


def files_in(root: Path) -> list[Path]:
    """Keep runtime, VCS and Python cache files outside the distributed contract."""
    ignored = {'.git', '__pycache__', '.runtime', 'runtime', '.venv'}
    return sorted(path for path in root.rglob('*') if path.is_file() and not ignored.intersection(path.relative_to(root).parts))


def validate(root: Path) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    paths = files_in(root)
    documents: dict[str, object] = {}
    for path in paths:
        relative = path.relative_to(root).as_posix()
        if path.suffix not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding='utf-8-sig')
        except UnicodeError:
            errors.append(f'UTF-8: {relative}')
            continue
        if '\ufffd' in text:
            errors.append(f'replacement character: {relative}')
        if PRIVATE_TARGET.search(text):
            errors.append(f'private target: {relative}')
        if CREDENTIAL.search(text):
            errors.append(f'credential: {relative}')
        if HOST_PATH.search(text):
            errors.append(f'host path: {relative}')
        if path.suffix == '.json':
            try:
                documents[relative] = json.loads(text)
            except json.JSONDecodeError:
                errors.append(f'JSON: {relative}')
        if path.suffix == '.md':
            for target in REFERENCE.findall(text):
                if target.startswith(('https://', 'http://', '#', 'mailto:')):
                    continue
                resolved = (path.parent / unquote(target.split('#', 1)[0])).resolve()
                if not resolved.is_relative_to(root):
                    errors.append(f'reference escapes bundle: {relative}: {target}')
                elif not resolved.is_file():
                    errors.append(f'missing reference: {relative}: {target}')

    config = documents.get('templates/library.config.example.json')
    if isinstance(config, dict):
        readiness = config.get('readiness', {})
        if config.get('template_only') is not True or not isinstance(readiness, dict) or readiness.get('ready_for_pdf') is not False or readiness.get('automated_cycle_observed') is not False:
            errors.append('readiness template must be unconfigured')
        target_fields = ['root_folder_url', 'inbox_url', 'output_url', 'system_folder_url', 'spreadsheet_url', 'skill_url', 'config_url']
        if any(config.get(field) is not None for field in target_fields):
            errors.append('private target in configuration template')

    schema = documents.get('templates/sheets.schema.json')
    if isinstance(schema, dict):
        tabs = schema.get('tabs', [])
        keys = [tab.get('key') for tab in tabs]
        if len(set(keys)) != len(keys):
            errors.append('duplicate sheet identities')
        for tab in tabs:
            if tab.get('row_identity') not in tab.get('fields', []):
                errors.append(f'sheet identity missing from fields: {tab.get("key")}')

    acceptance = root / 'acceptance' / 'ACCEPTANCE-FA.csv'
    if acceptance.is_file():
        rows = list(csv.reader(io.StringIO(acceptance.read_text(encoding='utf-8-sig'))))
        identities = [row[0] for row in rows[1:] if row]
        expected = {f'AT{number:02}' for number in range(1, 18)}
        if len(identities) != len(set(identities)) or set(identities) != expected:
            errors.append('acceptance identities incomplete or duplicated')
        if not rows or any(len(row) != 8 for row in rows):
            errors.append('acceptance column widths')
    else:
        errors.append('missing acceptance table')

    manifest = documents.get('MANIFEST.json')
    if isinstance(manifest, dict) and isinstance(manifest.get('files'), dict):
        entries = manifest['files']
        actual = {p.relative_to(root).as_posix(): p for p in paths if p.name != 'MANIFEST.json'}
        if set(entries) != set(actual):
            errors.append('manifest file list differs')
        for name in set(entries).intersection(actual):
            digest = hashlib.sha256(actual[name].read_bytes()).hexdigest()
            if entries[name] != digest:
                errors.append(f'manifest hash differs: {name}')
    else:
        errors.append('missing or invalid manifest')
    return errors


if __name__ == '__main__':
    kit_root = Path(__file__).resolve().parents[1]
    failures = validate(kit_root)
    print(json.dumps({'ok': not failures, 'scope': 'offline bundle checks only', 'errors': failures}, ensure_ascii=False, indent=2))
    sys.exit(bool(failures))
