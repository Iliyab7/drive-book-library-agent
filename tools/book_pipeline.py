"""Small, offline handoff: witnessed reconstruction -> Markdown -> reading HTML.

Extraction/OCR and translation remain the agent's choice. This tool never calls a
model and does not certify translation quality. See docs/CONTENT-MODEL-FA.md.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import unicodedata
from urllib.parse import urlsplit, quote

from markdown_it import MarkdownIt
from mdit_py_plugins.footnote import footnote_plugin
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]


def filename_part(value: str, fallback: str, max_bytes: int = 70) -> str:
    """Portable Unicode component; preserve Persian, bound bytes, retain identity."""
    text = unicodedata.normalize('NFC', value)
    text = ''.join(c for c in text if not unicodedata.category(c).startswith('C') or c == '\u200c')
    text = re.sub(r'[<>:"/\\|?*]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip(' .') or fallback
    if len(text.encode('utf-8')) > max_bytes:
        tail = '-' + hashlib.sha256(text.encode('utf-8')).hexdigest()[:8]
        text = text.encode('utf-8')[:max_bytes - len(tail)].decode('utf-8', errors='ignore').rstrip(' .') + tail
    if re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', text):
        text = '_' + text
    return text


def output_filenames(spec: dict) -> tuple[dict[str, str], list[str]]:
    title = spec.get('title_original') or spec.get('title_fa') or ''
    authors = spec.get('authors') or []
    if isinstance(authors, str):
        authors = [authors]
    author = '، '.join(a.strip() for a in authors if isinstance(a, str) and a.strip())
    missing = [key for key, value in (('title', title), ('authors', author)) if not value.strip()]
    prefix = ' — '.join((filename_part(title, 'عنوان نامشخص'),
                         filename_part(author, 'نویسنده نامشخص'),
                         filename_part(spec['book_version_id'], 'نسخه نامشخص', 32)))
    return {role: f'{prefix} — {role}' for role in
            ('original.pdf', 'original.md', 'translation.fa.md', 'translation.fa.html')}, missing


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reconstruct(model: dict) -> list[dict]:
    """Require explicit reading order, complete coverage and witnessed edits.

    An extractor/agent supplies blocks and decisions after consulting the PDF.
    No repeated text is deleted by frequency; no page boundary implies a join.
    """
    raw = model['raw_blocks']
    if not raw or not model.get('blocks'):
        raise ValueError('source content must not be empty')
    by_id = {b['id']: b for b in raw}
    if len(by_id) != len(raw):
        raise ValueError('duplicate source block')
    order = model['reading_order']
    if len(order) != len(set(order)) or set(order) != set(by_id):
        raise ValueError('reading order must cover each raw block once')
    if not model.get('order_evidence'):
        raise ValueError('reading order needs PDF evidence')
    omitted = model.get('noise', [])
    for b in omitted:
        if not b.get('reason') or not b.get('evidence'):
            raise ValueError('noise removal needs reason and evidence')
    used = [ref for b in model['blocks'] for ref in b['refs']]
    accounted = used + [b['ref'] for b in omitted]
    if len(accounted) != len(set(accounted)) or set(accounted) != set(by_id):
        raise ValueError('missing or repeated source content')
    if used != [ref for ref in order if ref not in {b['ref'] for b in omitted}]:
        raise ValueError('output differs from approved reading order')
    result = []
    for index, block in enumerate(model['blocks'], 1):
        if not block['refs']:
            raise ValueError('output block needs source references')
        refs = [by_id[ref] for ref in block['refs']]
        kind = block['kind']
        if kind not in {'heading', 'paragraph', 'table', 'footnote', 'caption', 'image'}:
            raise ValueError('unsupported block kind')
        if kind == 'heading' and block.get('level', 2) not in range(1, 7):
            raise ValueError('heading level must be 1..6')
        if kind == 'footnote' and not re.fullmatch(r'[A-Za-z0-9_-]+', block.get('note_id', '')):
            raise ValueError('footnote requires a safe stable note ID')
        if len(refs) > 1 and not block.get('join_evidence'):
            raise ValueError('cross-block join needs evidence')
        if any(not isinstance(r['pdf_page'], int) or r['pdf_page'] < 1 for r in refs):
            raise ValueError('PDF pages are one-based')
        item = dict(block, id=f's{index:04}', pdf_pages=list(dict.fromkeys(r['pdf_page'] for r in refs)),
                    printed_pages=list(dict.fromkeys(r.get('printed_page') for r in refs)))
        if kind == 'table':
            columns = refs[0]['columns']
            if any(r['columns'] != columns for r in refs):
                raise ValueError('table columns differ; inspect continuation')
            item['columns'] = columns
            item['rows'] = [row for r in refs for row in r['rows']]
            if any(len(row) != len(columns) for row in item['rows']):
                raise ValueError('table row width')
        elif kind == 'image':
            if len(refs) != 1 or not refs[0].get('asset') or not refs[0].get('alt'):
                raise ValueError('image requires extracted asset and source-backed alt')
            item.update(asset=refs[0]['asset'], alt=refs[0]['alt'])
        else:
            # Only visual line whitespace is normalized. Hyphens, numbers and
            # punctuation are retained; difficult edits need a separate revision.
            item['text'] = ' '.join(re.sub(r'\s+', ' ', r['text']).strip() for r in refs)
        result.append(item)
    return result


def language_policy(blocks: list[dict], decision: dict) -> dict:
    text = ' '.join(b.get('text', '') for b in blocks)
    fa = len(re.findall(r'[\u0600-\u06ff]', text))
    other = len(re.findall(r'[^\W\d_]', text)) - fa
    suggested = 'fa' if fa / max(fa + other, 1) >= .7 else 'non_fa'
    policy = decision.get('policy')
    if policy not in {'source_persian', 'translate_to_fa', 'mixed_selective'} or not decision.get('content_evidence'):
        raise ValueError('content-based language decision required')
    if (policy == 'source_persian') != (suggested == 'fa') and not decision.get('override_reason'):
        raise ValueError('language heuristic disagrees; inspect content and record override')
    if policy == 'mixed_selective' and not decision.get('translate_ids'):
        raise ValueError('bilingual source needs explicit translation scope')
    return dict(decision, heuristic=suggested, translation_status=(
        'not_required_source_persian' if policy == 'source_persian' else 'required'))


def raster_data(asset: str, asset_root: Path) -> str:
    if urlsplit(asset).scheme or asset.startswith(('//', '\\\\')):
        raise ValueError('image must be local raster within asset root')
    target = (asset_root / asset).resolve()
    if not target.is_relative_to(asset_root.resolve()) or target.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
        raise ValueError('image must be local raster within asset root')
    mime = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'}[target.suffix.lower()]
    try:
        data = target.read_bytes()
    except OSError as exc:
        raise ValueError('image asset unavailable') from exc
    return f'data:{mime};base64,' + base64.b64encode(data).decode()


def markdown(blocks: list[dict], asset_root: Path | None = None, pdf_filename: str = 'original.pdf') -> str:
    chunks = []
    for b in blocks:
        if b['kind'] == 'heading':
            chunks.append('#' * b.get('level', 2) + ' ' + b['text'])
        elif b['kind'] == 'footnote':
            chunks.append(f"[^{b['note_id']}]: {b['text']}")
        elif b['kind'] == 'table':
            def row(values):
                return '| ' + ' | '.join(str(x).replace('|', '\\|').replace('\n', ' ') for x in values) + ' |'
            chunks.append('\n'.join([row(b['columns']), row(['---'] * len(b['columns']))] + [row(r) for r in b['rows']]))
        elif b['kind'] == 'image':
            if asset_root is None:
                raise ValueError('image requires an asset root')
            chunks.append(f"![{b['alt']}]({raster_data(b['asset'], asset_root)})")
        else:
            chunks.append(b['text'])
        # Footnote definitions cannot have a second standalone paragraph without
        # altering semantics: append their source reference inside the definition.
        pages = ', '.join(map(str, b['pdf_pages']))
        source = f"[{b['id']} · PDF {pages}]({quote(pdf_filename, safe='')}#page={b['pdf_pages'][0]})"
        if b['kind'] == 'footnote':
            chunks[-1] += ' ' + source
        else:
            chunks.append(source)
    return '\n\n'.join(chunks) + '\n'


def reading_html(md: str, title: str, asset_root: Path, limitations: list[str]) -> str:
    definitions = re.findall(r'^ {0,3}\[\^([^\]\n]+)\]:', md, re.MULTILINE)
    references = re.findall(r'\[\^([^\]\n]+)\](?!:)', md)
    if len(definitions) != len(set(definitions)) or set(definitions) != set(references):
        raise ValueError('footnotes must have unique definitions and matching references; inspect source')
    parser = MarkdownIt('commonmark', {'html': False, 'linkify': False}).enable('table').use(footnote_plugin)
    env = {}
    tokens = parser.parse(md, env)
    if any(index == -1 for index in env.get('footnotes', {}).get('refs', {}).values()):
        raise ValueError('footnotes have no actual rendered reference; inspect escaped/code markers')
    toc = []
    for i, token in enumerate(tokens):
        if token.type == 'paragraph_open' and i + 1 < len(tokens) and re.fullmatch(r'\[s\d+ · PDF [\d, ]+\]\([^\s()]+\.pdf#page=\d+\)', tokens[i + 1].content):
            token.attrSet('class', 'source-reference')
        if token.type == 'heading_open':
            anchor = f'chapter-{len(toc) + 1}'
            token.attrSet('id', anchor)
            toc.append((anchor, tokens[i + 1].content))
        if token.type == 'inline':
            for child in token.children or []:
                if child.type != 'image':
                    continue
                source = child.attrGet('src')
                if not re.fullmatch(r'data:image/(?:png|jpeg|webp);base64,[A-Za-z0-9+/=]+', source):
                    child.attrSet('src', raster_data(source, asset_root))
    body = parser.renderer.render(tokens, parser.options, env)
    fonts = []
    for weight, name in [(400, 'Regular'), (700, 'Bold')]:
        data = base64.b64encode((ROOT / 'assets/fonts' / f'Vazirmatn-{name}.ttf').read_bytes()).decode()
        fonts.append(f"@font-face{{font-family:Vazirmatn;src:url(data:font/ttf;base64,{data});font-weight:{weight}}}")
    css = (ROOT / 'templates/book.css').read_text(encoding='utf-8')
    nav = ''.join(f'<li><a href="#{a}">{html.escape(t)}</a></li>' for a, t in toc)
    notes = ''.join('<li>' + html.escape(x) + '</li>' for x in limitations)
    warning = f'<aside aria-label="محدودیت‌ها"><h2>محدودیت‌ها</h2><ul>{notes}</ul></aside>' if notes else ''
    # No active content, form, remote font/image or raw HTML from the book.
    csp = "default-src 'none'; style-src 'unsafe-inline'; font-src data:; img-src data:; base-uri 'none'; form-action 'none'"
    digest = hashlib.sha256(md.encode()).hexdigest()
    return f'''<!doctype html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="{csp}">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="translation-md-sha256" content="{digest}">
<title>{html.escape(title)}</title><style>{''.join(fonts)}{css}</style></head>
<body><header><p>نسخه مطالعه و چاپ</p><h1>{html.escape(title)}</h1></header>
<nav aria-label="فهرست فصل‌ها"><h2>فهرست</h2><ol>{nav}</ol></nav>
{warning}<main>{body}</main><footer>ارجاع PDF به صفحه فایل اصلی است؛ صفحه چاپی ممکن است متفاوت باشد.
فونت Vazirmatn با مجوز SIL OFL 1.1؛ متن مجوز همراه بسته و در منبع این فایل است.</footer>
<!-- {html.escape((ROOT / 'assets/fonts/OFL.txt').read_text(encoding='utf-8'))} -->
</body></html>'''


def build_book(spec: dict, pdf: Path, out: Path, private: Path) -> dict:
    if out.exists() or private.exists():
        raise ValueError('use new version directories; never overwrite existing outputs/history')
    blocks = reconstruct(spec['reconstruction'])
    page_count = len(PdfReader(pdf).pages)
    if any(page > page_count for b in blocks for page in b['pdf_pages']):
        raise ValueError('source map points beyond the actual PDF page count')
    policy = language_policy(blocks, spec['language_decision'])
    translated = None
    if policy['policy'] != 'source_persian':
        translated = spec['translation']
        if [(b['id'], b['kind']) for b in translated] != [(b['id'], b['kind']) for b in blocks]:
            raise ValueError('translation structure missing, reordered or duplicated')
        for source, target in zip(blocks, translated):
            if policy['policy'] == 'mixed_selective' and source['id'] not in policy['translate_ids'] and target != source:
                raise ValueError('existing Persian outside translation scope must be preserved')
            if {k: target.get(k) for k in ('pdf_pages', 'printed_pages', 'note_id', 'asset')} != {k: source.get(k) for k in ('pdf_pages', 'printed_pages', 'note_id', 'asset')}:
                raise ValueError('translation source mapping changed')
            if source['kind'] == 'table':
                if len(target['rows']) != len(source['rows']) or len(target['columns']) != len(source['columns']) or any(len(r) != len(source['columns']) for r in target['rows']):
                    raise ValueError('translation table structure changed')
            elif source['kind'] != 'image' and not target.get('text', '').strip():
                raise ValueError('empty translation')
    # Prepare everything before creating the output directory.
    names, missing_metadata = output_filenames(spec)
    original = markdown(blocks, pdf.parent, names['original.pdf'])
    fa_md = markdown(translated, pdf.parent, names['original.pdf']) if translated else None
    fa_html = reading_html(fa_md, spec['title_fa'], pdf.parent, spec.get('limitations', [])) if translated else None
    out.mkdir(parents=True)
    private.mkdir(parents=True)
    shutil.copyfile(pdf, out / names['original.pdf'])
    (out / names['original.md']).write_text(original, encoding='utf-8', newline='\n')
    if translated:
        (out / names['translation.fa.md']).write_text(fa_md, encoding='utf-8', newline='\n')
        (out / names['translation.fa.html']).write_text(fa_html, encoding='utf-8', newline='\n')
    record = dict(book_version_id=spec['book_version_id'], language=spec['language'], pdf_pages=page_count,
                  title_original=spec['title_original'], title_fa=spec['title_fa'],
                  language_decision=policy, translation_status=policy['translation_status'],
                  translation_not_required_reason=('نیاز ندارد، منبع فارسی است' if not translated else None),
                  quality_status='needs_independent_review',
                  hashes={p.name: sha256(p) for p in out.iterdir()},
                  output_filenames={role: name for role, name in names.items() if translated or role.startswith('original.')},
                  filename_metadata_status='needs_review' if missing_metadata else 'complete',
                  filename_missing_metadata=missing_metadata,
                  pdf_url=(out / names['original.pdf']).resolve().as_uri(),
                  original_md_url=(out / names['original.md']).resolve().as_uri(),
                  translation_md_url=(out / names['translation.fa.md']).resolve().as_uri() if translated else None,
                  translation_html_url=(out / names['translation.fa.html']).resolve().as_uri() if translated else None)
    for key in ('authors', 'edition_if_known', 'summary', 'main_problem_and_thesis', 'chapter_outline', 'concepts', 'topic_tree', 'tags_fa', 'tags_original_language', 'use_and_distinction'):
        record[key] = spec.get(key)
    record['limitations'] = spec.get('limitations', [])
    record['quality_axes'] = dict.fromkeys(('coverage','fidelity','structure','reading_print'), 'not_run')
    (private / 'reconstruction.json').write_text(json.dumps(spec['reconstruction'], ensure_ascii=False, indent=2), encoding='utf-8')
    (private / 'source-map.json').write_text(json.dumps(blocks, ensure_ascii=False, indent=2), encoding='utf-8')
    (private / 'catalog.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    return record


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('spec', type=Path)
    ap.add_argument('pdf', type=Path)
    ap.add_argument('output', type=Path)
    ap.add_argument('private', type=Path)
    args = ap.parse_args()
    record = build_book(json.loads(args.spec.read_text(encoding='utf-8')), args.pdf, args.output, args.private)
    print(json.dumps({'book_version_id': record['book_version_id'], 'files': list(record['hashes']), 'status': record['quality_status']}))
