"""Offline migration/reconciliation helpers. No Sheets/Notion client or lock.

The single coordinator reads/writes destination rows with real connected tools.
These pure helpers plan additive changes and reconcile a durable private outbox.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVENT_FIELDS = {'event_id', 'occurred_at', 'timezone', 'actor', 'role', 'event_type',
                'stage', 'result', 'book_version_id', 'run_id', 'artifact_revision', 'evidence_or_checkpoint'}


def migrate_config(old: dict) -> dict:
    version = old.get('schema_version', 1)
    if version not in (1, 2):
        raise ValueError('unsupported configuration schema')
    result = deepcopy(old)
    memory = result.setdefault('memory', {})
    defaults = {'instruction_storage': 'full_text_in_master_sheet',
                'source_repository_read_policy': 'install_or_explicit_upgrade_only',
                'active_method_record_id': 'active_method', 'config_selection': 'version_bound_manifest',
                'active_memory_revision': None}
    memory_changed = any(key not in memory for key in defaults)
    for key, value in defaults.items():
        memory.setdefault(key, value)
    for key in ('instruction_storage', 'source_repository_read_policy', 'config_selection'):
        if memory[key] != defaults[key]:
            memory[key] = defaults[key]
            memory_changed = True
    for field, required in {
        'read_at_every_turn': ['active_method', 'version_bound_config', 'full_active_instruction_text', 'relevant_runs', 'checkpoint', 'recent_events'],
        'instruction_components': ['skill', 'workflow', 'coordinator', 'review', 'qa', 'reading_tools', 'memory_protocol'],
    }.items():
        values = memory.setdefault(field, [])
        for value in required:
            if value not in values:
                values.append(value)
                memory_changed = True
    if memory_changed:
        result['migration_status'] = 'pending_readback_and_sample'
        result['activation_verified'] = False
    if version == 2:
        return result
    result['schema_version'] = 2
    result['package_version'] = '2.0.0'
    result['previous_package_version'] = old.get('package_version')
    result['locations'] = {
        'files': {'provider': 'google_drive', 'reference': old.get('root_folder_url')},
        'catalog': {'provider': 'google_sheets', 'reference': old.get('spreadsheet_url')},
        'shared_memory': {'provider': 'google_sheets', 'reference': old.get('spreadsheet_url')},
        'checkpoints': {'provider': 'google_drive', 'reference': old.get('system_folder_url')},
    }
    # Preserve existing schedule IDs/destinations. A migrated config is a plan,
    # not proof that the new package, links or capabilities have been activated.
    result['migration_status'] = 'pending_readback_and_sample'
    result['activation_verified'] = False
    return result


def schema_plan(existing: dict[str, list[str]]) -> dict[str, list[str]]:
    schema = json.loads((ROOT / 'templates/sheets.schema.json').read_text(encoding='utf-8'))
    return {tab['key']: [f for f in tab['fields'] if f not in existing.get(tab['key'], [])]
            for tab in schema['tabs']}


def validate_event(event: dict) -> None:
    if not EVENT_FIELDS.issubset(event):
        raise ValueError('event missing required fields')
    if not all(event.get(k) for k in ('event_id', 'actor', 'role', 'event_type', 'stage', 'result', 'timezone', 'evidence_or_checkpoint')):
        raise ValueError('event needs identity, actor, result and evidence')
    stamp = datetime.fromisoformat(event['occurred_at'].replace('Z', '+00:00'))
    if stamp.utcoffset() is None:
        raise ValueError('timestamp needs real UTC offset')
    if event['event_type'] == 'correction' and not event.get('corrects_event_id'):
        raise ValueError('correction must reference prior event')


def reconcile_events(remote: list[dict], pending: list[dict]) -> list[dict]:
    """Append by stable event ID; changed retries are conflicts, never overwrites."""
    result, known = [], {}
    for event in remote + pending:
        validate_event(event)
        key = event['event_id']
        if key in known:
            if known[key] != event:
                raise ValueError('event ID collision; append a correction event')
            continue
        if event.get('corrects_event_id') and event['corrects_event_id'] not in known:
            raise ValueError('correction target missing')
        known[key] = deepcopy(event)
        result.append(deepcopy(event))
    return result


def save_outbox(path: Path, events: list[dict]) -> None:
    """Atomic local replacement by the single writer; not a distributed lock."""
    prior = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
    # An offline correction may refer to an ACKed event absent from this outbox.
    # Validate payload and ID conflicts here; verify target existence only after
    # reading the destination history during reconcile_events.
    merged = deepcopy(prior)
    known = {e['event_id']: e for e in prior}
    for event in events:
        validate_event(event)
        if event['event_id'] in known:
            if known[event['event_id']] != event:
                raise ValueError('event ID collision; append a correction event')
        else:
            known[event['event_id']] = deepcopy(event)
            merged.append(deepcopy(event))
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_suffix('.pending')
    staging.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding='utf-8')
    staging.replace(path)


def capability_limits(config: dict, capabilities: dict) -> list[str]:
    limits = []
    for name in ('preserve_original_files', 'readback_files', 'search_all_records',
                 'stable_version_ids', 'append_events', 'recover_checkpoints'):
        if capabilities.get(name) is not True:
            limits.append(f'destination capability unverified: {name}')
    for name in ('scheduler', 'independent_review', 'independent_qa', 'serialization'):
        if capabilities.get(name) is not True:
            limits.append(f'runtime capability unverified: {name}')
    if config.get('locations', {}).get('files', {}).get('provider') != 'google_drive':
        limits.append('alternative destination adapter not bundled; verify actual connected tools')
    return limits


def select_catalog_pages(pages, query: str) -> list[dict]:
    """Offline discovery example; caller must supply ALL paginated result pages."""
    fields = ('title_original', 'title_fa', 'summary', 'concepts', 'tags_fa', 'chapter_outline')
    return [row for page in pages for row in page
            if query.casefold() in ' '.join(str(row.get(f, '')) for f in fields).casefold()]
