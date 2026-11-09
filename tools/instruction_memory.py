"""Prepare a complete deployed runbook for the master sheet; load it offline.

Preparation reads the versioned package ONLY at install/explicit upgrade. The
startup loader consumes read-back memory records only, without repository I/O.
Live Sheets writes/activation belong to the account's single coordinator.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    'skill': '.agents/skills/drive-book-library/SKILL.md',
    'workflow': '.agents/skills/drive-book-library/references/WORKFLOW-FA.md',
    'coordinator': 'prompts/RUN-FA.txt',
    'review': 'prompts/REVIEW-FA.txt',
    'qa': 'prompts/QA-FA.txt',
    'reading_tools': 'docs/CONTENT-MODEL-FA.md',
    'memory_protocol': 'docs/STATE-AND-DESTINATIONS-FA.md',
}


def digest(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def manifest_hash(manifest: dict) -> str:
    return digest(json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(',', ':')))


def validate_config(config: dict) -> None:
    if not isinstance(config, dict) or not config or config.get('template_only') is True:
        raise ValueError('actual nonempty operational config required')
    for key in ('inbox_url', 'output_url'):
        if not config.get(key):
            raise ValueError('operational config target missing')
    for key in ('files', 'catalog', 'shared_memory', 'checkpoints'):
        if not config.get('locations', {}).get(key, {}).get('reference'):
            raise ValueError('operational config location missing')
    if any(not isinstance(config.get(key), dict) for key in ('runtime', 'coordination', 'schedule')):
        raise ValueError('operational runtime/coordination/schedule config required')


def prepare_instructions(package_revision: str, memory_revision: str, config: dict, root: Path = ROOT,
                         chunk_chars: int = 4000) -> dict:
    if not package_revision.strip() or not memory_revision.strip() or chunk_chars < 100:
        raise ValueError('explicit source/memory revision and usable chunk size required')
    validate_config(config)
    config_record = {'record_id': f'{memory_revision}:config', 'record_type': 'operational_config',
                     'memory_revision': memory_revision, 'record_content_json': deepcopy(config)}
    rows, components = [], []
    for key, source in SOURCES.items():
        content = (root / source).read_text(encoding='utf-8')
        if not content.strip():
            raise ValueError('empty required instruction component')
        chunks = [content[i:i + chunk_chars] for i in range(0, len(content), chunk_chars)]
        components.append({'component_id': key, 'sha256': digest(content), 'chunks': len(chunks)})
        for index, text in enumerate(chunks):
            rows.append({'record_id': f'{memory_revision}:{key}:{index}',
                         'record_type': 'instruction_chunk',
                         'memory_revision': memory_revision, 'component_id': key,
                         'chunk_index': index, 'instruction_text': text})
    manifest = {'package_version': '2.0.0', 'package_revision': package_revision,
                'memory_revision': memory_revision, 'components': components,
                'config_record_id': config_record['record_id'],
                'config_sha256': manifest_hash(config_record['record_content_json'])}
    pointer = {'record_id': 'active_method', 'memory_revision': memory_revision,
               'package_version': '2.0.0', 'bundle_sha256': manifest_hash(manifest),
               'activation_status': 'staged'}
    return {'pointer': pointer, 'manifest': manifest, 'rows': rows, 'config': config_record}


def load_active_instructions(pointer_before: dict, manifest: dict, rows: list[dict],
                             pointer_after: dict, config_record: dict) -> dict[str, str]:
    """All arguments are actual sheet readbacks, including a final pointer read.

    No link fetch, file read or GitHub dependency is used by this function.
    Missing/corrupt/mixed revisions block startup, preserving the previous state.
    """
    if pointer_before != pointer_after:
        raise ValueError('active memory changed during read; retry before starting work')
    if pointer_before.get('activation_status') != 'active':
        raise ValueError('instruction memory is not active')
    if (pointer_before.get('bundle_sha256') != manifest_hash(manifest)
            or pointer_before.get('memory_revision') != manifest.get('memory_revision')
            or pointer_before.get('package_version') != manifest.get('package_version')):
        raise ValueError('active memory manifest mismatch')
    if (not isinstance(config_record, dict)
            or config_record.get('record_id') != manifest['config_record_id']
            or config_record.get('memory_revision') != manifest['memory_revision']
            or manifest_hash(config_record.get('record_content_json', {})) != manifest['config_sha256']):
        raise ValueError('active operational config missing or version/hash mismatch')
    validate_config(config_record['record_content_json'])
    components = manifest['components']
    if len(components) != len(SOURCES) or {c['component_id'] for c in components} != set(SOURCES):
        raise ValueError('required instruction components missing or duplicated')
    active_rows = [r for r in rows if r.get('memory_revision') == manifest['memory_revision']]
    if any(r.get('component_id') not in SOURCES for r in active_rows):
        raise ValueError('unexpected instruction component')
    texts = {}
    for component in components:
        if not isinstance(component['chunks'], int) or component['chunks'] < 1:
            raise ValueError('required instruction component must have positive chunks')
        parts = sorted((r for r in active_rows if r['component_id'] == component['component_id']),
                       key=lambda r: r['chunk_index'])
        if [r['chunk_index'] for r in parts] != list(range(component['chunks'])):
            raise ValueError('missing or duplicate instruction chunk; read all result pages')
        text = ''.join(r['instruction_text'] for r in parts)
        if not text.strip() or digest(text) != component['sha256']:
            raise ValueError('instruction text corrupted or incomplete')
        texts[component['component_id']] = text
    return texts


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--package-revision', required=True)
    ap.add_argument('--memory-revision', required=True)
    ap.add_argument('--config', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    if args.out.exists():
        raise SystemExit('use a fresh private staging path')
    prepared = prepare_instructions(args.package_revision, args.memory_revision,
                                    json.loads(args.config.read_text(encoding='utf-8')))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(prepared, ensure_ascii=False, indent=2), encoding='utf-8', newline='\n')
    print(json.dumps({'status': 'staged_not_written_or_activated', 'rows': len(prepared['rows'])}))
