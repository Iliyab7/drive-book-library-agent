"""Behavioral, offline fixtures. Not a live translation quality benchmark."""
from copy import deepcopy
import base64
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from book_pipeline import build_book, reconstruct, language_policy, reading_html, markdown

FIX=ROOT/'tests/fixtures/v2'


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)
        self.spec=json.loads((FIX/'nonfa.json').read_text(encoding='utf-8'))
    def tearDown(self):self.tmp.cleanup()
    def test_nonfa_four_outputs_same_translation_and_pdf(self):
        out=self.path/'out'
        record=build_book(self.spec,FIX/'nonfa.pdf',out,self.path/'private')
        self.assertEqual(set(record['hashes']),{'original.pdf','original.md','translation.fa.md','translation.fa.html'})
        self.assertEqual((out/'original.pdf').read_bytes(),(FIX/'nonfa.pdf').read_bytes())
        md=(out/'translation.fa.md').read_bytes();ht=(out/'translation.fa.html').read_text(encoding='utf-8')
        self.assertIn(hashlib.sha256(md).hexdigest(),ht)
        self.assertIn('بهبود محتمل است، اما تضمین‌شده نیست',ht)
        self.assertIn('footnote-backref',ht)
        self.assertIn('data:font/ttf;base64,',ht)
        self.assertNotRegex(ht,r'(?:src|href)=["\']https?://')
        self.assertEqual(record['quality_status'],'needs_independent_review')
    def test_persian_two_outputs_no_fake_translation(self):
        spec=json.loads((FIX/'persian.json').read_text(encoding='utf-8'))
        out=self.path/'out';record=build_book(spec,FIX/'persian.pdf',out,self.path/'private')
        self.assertEqual(set(record['hashes']),{'original.pdf','original.md'})
        self.assertEqual(record['translation_status'],'not_required_source_persian')
        self.assertIsNone(record['translation_md_url']);self.assertIsNone(record['translation_html_url'])
        self.assertIn('نیاز ندارد',record['translation_not_required_reason'])
    def test_reconstruction_exact_order_join_table_and_footnote(self):
        blocks=reconstruct(self.spec['reconstruction']);md=markdown(blocks)
        self.assertIn('continues across the page boundary',md)
        self.assertNotIn('running footer',md)
        self.assertEqual(md.count('A repeated statement can be real content.'),2)
        self.assertLess(md.index('left column first'),md.index('right column second'))
        self.assertEqual(blocks[1]['pdf_pages'],[1,2]);self.assertEqual(blocks[1]['printed_pages'],['7','8'])
        self.assertEqual(blocks[5]['pdf_pages'],[2,3])
        self.assertEqual(blocks[5]['rows'],[['Training (hours)','20','2','Only if checked'],['Exercises','5','5','No reduction'],['Price (USD)','12.50','12.50','Do not convert'],['Mass (kg)','3.2','3.2','Do not round']])
        self.assertIn('not guaranteed',md);self.assertIn('[^n1]: An improvement is not a guarantee',md)
        # The actual PDF also contains the split parts, columns and all values.
        reader=PdfReader(FIX/'nonfa.pdf');self.assertEqual(len(reader.pages),3)
        self.assertIn('sentence continues',reader.pages[0].extract_text())
        self.assertIn('across the page boundary',reader.pages[1].extract_text())
        self.assertIn('12.50',reader.pages[2].extract_text())
    def test_drop_duplicate_reorder_and_unwitnessed_decision_rejected(self):
        for mode in ('drop','duplicate','order','join','noise','table'):
            model=deepcopy(self.spec['reconstruction'])
            if mode=='drop':model['blocks'].pop()
            if mode=='duplicate':model['blocks'].append(model['blocks'][0])
            if mode=='order':model['blocks'][3],model['blocks'][4]=model['blocks'][4],model['blocks'][3]
            if mode=='join':model['blocks'][1].pop('join_evidence')
            if mode=='noise':model['noise'][0].pop('evidence')
            if mode=='table':model['raw_blocks'][9]['columns']=['Changed']
            with self.subTest(mode=mode),self.assertRaises(ValueError):reconstruct(model)
    def test_mixed_source_preserves_existing_persian(self):
        self.spec['reconstruction']['raw_blocks'][5]['text']='این بند فارسی باید بدون بازنویسی حفظ شود.'
        blocks=reconstruct(self.spec['reconstruction']);self.spec['translation'][3]=deepcopy(blocks[3])
        self.spec['language_decision']={'policy':'mixed_selective','content_evidence':'One Persian paragraph among English sections; all read.','translate_ids':[b['id'] for b in blocks if b['id']!='s0004']}
        build_book(self.spec,FIX/'nonfa.pdf',self.path/'ok',self.path/'ok-private')
        self.spec['translation'][3]['text']='بازنویسی غیرمجاز'
        with self.assertRaisesRegex(ValueError,'Persian'):build_book(self.spec,FIX/'nonfa.pdf',self.path/'bad',self.path/'bad-private')
    def test_wrong_language_and_broken_alignment_rejected(self):
        with self.assertRaises(ValueError):language_policy(reconstruct(self.spec['reconstruction']),{'policy':'source_persian','content_evidence':'filename only'})
        self.spec['translation'].pop()
        with self.assertRaises(ValueError):build_book(self.spec,FIX/'nonfa.pdf',self.path/'out',self.path/'private')
    def test_existing_version_never_overwritten(self):
        (self.path/'out').mkdir();(self.path/'out'/'old.txt').write_text('keep')
        with self.assertRaises(ValueError):build_book(self.spec,FIX/'nonfa.pdf',self.path/'out',self.path/'private')
        self.assertEqual((self.path/'out'/'old.txt').read_text(),'keep')
    def test_untrusted_html_links_and_images_are_inert(self):
        with self.assertRaises(ValueError):reading_html('![bad](https://example.invalid/a.png)','test',FIX,[])
        with self.assertRaises(ValueError):reading_html('![bad](../outside.png)','test',FIX,[])
        ht=reading_html('<script>alert(1)</script>\n\n[bad](javascript:alert(1))','<img onerror=bad>',FIX,[])
        self.assertNotIn('<script>',ht);self.assertNotIn('href="javascript:',ht);self.assertIn('&lt;script&gt;',ht)
    def test_missing_or_duplicate_footnote_never_silently_disappears(self):
        for md in ('Body.\n\n[^n1]: A critical caveat.',
                   'Body.[^n1]\n\n[^n1]: A caveat.\n\n[^n1]: Another caveat.',
                   'Body `[^n1]`.\n\n[^n1]: A critical caveat.',
                   'Body \\[^n1].\n\n   [^n1]: A critical caveat.',
                   'Body.[^missing]'):
            with self.subTest(md=md),self.assertRaisesRegex(ValueError,'footnotes'):
                reading_html(md,'test',FIX,[])
    def test_page_beyond_actual_pdf_rejected_before_writing(self):
        self.spec['reconstruction']['raw_blocks'][0]['pdf_page']=999
        with self.assertRaisesRegex(ValueError,'actual PDF'):
            build_book(self.spec,FIX/'nonfa.pdf',self.path/'out',self.path/'private')
        self.assertFalse((self.path/'out').exists())
    def test_local_image_embedded_in_both_md_and_offline_html(self):
        png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jq1sAAAAASUVORK5CYII=')
        (self.path/'figure.png').write_bytes(png)
        blocks=[{'id':'s0001','kind':'image','asset':'figure.png','alt':'Extracted test figure','pdf_pages':[1]}]
        md=markdown(blocks,self.path);ht=reading_html(md,'test',self.path,[])
        self.assertIn('data:image/png;base64,',md);self.assertIn('data:image/png;base64,',ht)
        self.assertIn('Extracted test figure',ht)


if __name__=='__main__':unittest.main()
