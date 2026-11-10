"""Offline, synthetic destination records; no live Sheets/Notion writes."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.parse import urlparse, unquote
from urllib.request import url2pathname
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from library_state import migrate_config,schema_plan,reconcile_events,save_outbox,capability_limits,select_catalog_pages
from book_pipeline import build_book


def event(key,kind='checkpoint'):
    return {'event_id':key,'book_version_id':'synthetic-v1','run_id':'test-run-1',
      'occurred_at':datetime.now(ZoneInfo('Asia/Tehran')).isoformat(),'timezone':'Asia/Tehran',
      'actor':'synthetic-coordinator','role':'coordinator','event_type':kind,'stage':'reconstruction',
      'result':'test_checkpoint','artifact_revision':'r1','evidence_or_checkpoint':'private-test/checkpoint-1'}


class StateTests(unittest.TestCase):
    def test_legacy_v2_memory_migrates_full_startup_additively(self):
        old={'schema_version':2,'package_version':'2.0.0','activation_verified':True,
             'memory':{'instruction_storage':'links_only','read_at_every_turn':['custom_check','config'],'custom_setting':'keep'}}
        updated=migrate_config(old)
        self.assertFalse(updated['activation_verified'])
        self.assertEqual(updated['memory']['custom_setting'],'keep')
        self.assertIn('custom_check',updated['memory']['read_at_every_turn'])
        self.assertIn('full_active_instruction_text',updated['memory']['read_at_every_turn'])
        self.assertIn('version_bound_config',updated['memory']['read_at_every_turn'])
        self.assertEqual(len(updated['memory']['instruction_components']),7)
        self.assertEqual(updated['memory']['instruction_storage'],'full_text_in_master_sheet')
        self.assertEqual(migrate_config(updated),updated)
        self.assertTrue(old['activation_verified'])
    def test_offline_migration_preserves_old_ids_unknown_fields_and_history(self):
        old={'schema_version':1,'package_version':'1.0.0','spreadsheet_url':'synthetic-sheet','root_folder_url':'synthetic-root',
             'system_folder_url':'synthetic-system','custom':{'keep':True},'schedule':{'id':'existing','notification_destination':'existing-destination'},'readiness':{'ready_for_pdf':True}}
        migrated=migrate_config(old)
        for key in ('spreadsheet_url','root_folder_url','custom','schedule'):self.assertEqual(migrated[key],old[key])
        self.assertFalse(migrated['readiness']['ready_for_pdf'])
        self.assertFalse(migrated['activation_verified']);self.assertEqual(migrated['migration_status'],'pending_readback_and_sample')
        self.assertEqual(migrated['locations']['catalog']['reference'],migrated['locations']['shared_memory']['reference'])
        self.assertEqual(migrate_config(migrated),migrated);self.assertEqual(old['schema_version'],1)
        existing={'catalog':['book_version_id','old_custom_field'],'runs':['run_id']};before=deepcopy(existing)
        plan=schema_plan(existing)
        self.assertNotIn('book_version_id',plan['catalog']);self.assertIn('translation_html_url',plan['catalog']);self.assertIn('event_id',plan['events'])
        self.assertEqual(existing,before)
    def test_folder_upgrade_preserves_targets_and_resets_prior_readiness(self):
        template=json.loads((ROOT/'templates/library.config.example.json').read_text(encoding='utf-8'))
        old=deepcopy(template)
        old['package_version']='2.0.0';old.pop('processing_url');old['capabilities'].pop('move_files')
        old['inbox_url']='synthetic-inbox';old['output_url']='synthetic-output'
        old['schedule']['id']='existing-schedule';old['activation_verified']=True
        old['readiness'].update(ready_for_pdf=True,automated_cycle_observed=True)
        migrated=migrate_config(old)
        self.assertEqual(migrated['package_version'],'2.1.0')
        self.assertEqual(migrated['previous_package_version'],'2.0.0')
        self.assertIsNone(migrated['processing_url'])
        self.assertEqual(migrated['capabilities']['move_files'],'unverified')
        self.assertEqual(migrated['inbox_url'],old['inbox_url'])
        self.assertEqual(migrated['output_url'],old['output_url'])
        self.assertEqual(migrated['schedule'],old['schedule'])
        self.assertFalse(migrated['activation_verified'])
        self.assertFalse(migrated['readiness']['ready_for_pdf'])
        self.assertFalse(migrated['readiness']['automated_cycle_observed'])
        self.assertEqual(migrate_config(migrated),migrated)
        self.assertTrue(old['activation_verified'])
    def test_cut_after_append_resume_retry_and_correction_keep_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'outbox.json';first=event('start','stage_start');cp=event('cp')
            save_outbox(p,[first,cp])
            # Destination append succeeded, readback/ack lost; new process reads disk.
            remote=[first,cp];pending=json.loads(p.read_text(encoding='utf-8'))
            merged=reconcile_events(remote,pending);self.assertEqual(merged,remote)
            resumed=event('resume','recovery');resumed['recovered_from']='test-run-1'
            save_outbox(p,[resumed]);merged=reconcile_events(remote,json.loads(p.read_text(encoding='utf-8')))
            correction=event('fix','correction');correction['corrects_event_id']='cp';correction['result']='test_corrected_mapping'
            merged=reconcile_events(merged,[correction,correction]);self.assertEqual(len(merged),4)
            self.assertEqual(merged[1],cp);self.assertEqual(merged[-1]['corrects_event_id'],'cp')
            altered=deepcopy(cp);altered['result']='silently changed'
            with self.assertRaises(ValueError):reconcile_events(merged,[altered])
    def test_timestamp_without_offset_and_missing_correction_target_rejected(self):
        e=event('a');e['occurred_at']='2026-11-09T10:00:00'
        with self.assertRaises(ValueError):reconcile_events([],[e])
    def test_offline_correction_of_acknowledged_event_can_be_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            original=event('acknowledged')
            correction=event('offline-fix','correction');correction['corrects_event_id']='acknowledged'
            path=Path(tmp)/'empty-outbox.json'
            save_outbox(path,[correction])
            pending=json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(reconcile_events([original],pending),[original,correction])
        e=event('b','correction');e['corrects_event_id']='missing'
        with self.assertRaises(ValueError):reconcile_events([],[e])
    def test_missing_capabilities_never_yield_fake_success(self):
        cfg={'locations':{'files':{'provider':'notion'}}}
        limits=capability_limits(cfg,{})
        self.assertTrue(any('scheduler' in x for x in limits));self.assertTrue(any('independent_review' in x for x in limits));self.assertTrue(any('preserve_original_files' in x for x in limits));self.assertTrue(any('adapter' in x for x in limits))
    def test_catalog_all_pages_select_correct_version_and_md_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);fix=ROOT/'tests/fixtures/v2';records=[]
            for name in ('persian','nonfa'):
                spec=json.loads((fix/f'{name}.json').read_text(encoding='utf-8'))
                record=build_book(spec,fix/f'{name}.pdf',base/name/'output',base/name/'system')
                records.append(record)
            pages=[[records[0]],[],[records[1]]]
            rows=select_catalog_pages(pages,'آموزش');self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['book_version_id'],'synthetic-nonfa-v1')
            for key in ('original_md_url','translation_md_url','translation_html_url'):
                path=Path(url2pathname(unquote(urlparse(rows[0][key]).path)))
                self.assertTrue(path.is_file())
            path=Path(url2pathname(unquote(urlparse(rows[0]['translation_md_url']).path)))
            md=path.read_text(encoding='utf-8')
            section=md[md.index('## ۲.'):md.index('## ۳.')]
            self.assertIn('20 hours',section);self.assertIn('2 hours',section);self.assertIn('نیست',section)
            self.assertIn('s0004',section);self.assertEqual(select_catalog_pages(pages,'نامرتبط'),[])


if __name__=='__main__':unittest.main()
