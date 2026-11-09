"""Regenerate public synthetic structured inputs; PDFs via runtime renderer.

All prose is authored for this kit, not taken from a real book. Translation is
prewritten test data, never evidence of model translation quality.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from book_pipeline import reconstruct

DEST = ROOT / 'tests/fixtures/v2'


def make_specs():
    raw = [
        {'id':'h1','pdf_page':1,'printed_page':'7','text':'1. A careful beginning'},
        {'id':'p1a','pdf_page':1,'printed_page':'7','text':'If the source is checked, an improvement is likely, but it is not\nguaranteed. The parcel weighs 3.2 kilograms and the sentence continues'},
        {'id':'f1','pdf_page':1,'printed_page':'7','text':'SYNTHETIC LIBRARY · running footer'},
        {'id':'p1b','pdf_page':2,'printed_page':'8','text':'across the page boundary without losing its condition.[^n1]'},
        {'id':'h2','pdf_page':2,'printed_page':'8','text':'2. Columns and a continuing table'},
        {'id':'left','pdf_page':2,'printed_page':'8','text':'Read the left column first. Training took 20 hours before and takes 2 hours now.'},
        {'id':'right','pdf_page':2,'printed_page':'8','text':'Read the right column second. Time fell to 10 percent of its previous duration, not by 10 percent.'},
        {'id':'t1','pdf_page':2,'printed_page':'8','columns':['Metric','Before','After','Condition'], 'rows':[['Training (hours)','20','2','Only if checked'],['Exercises','5','5','No reduction']]},
        {'id':'f2','pdf_page':2,'printed_page':'8','text':'SYNTHETIC LIBRARY · running footer'},
        {'id':'t2','pdf_page':3,'printed_page':'9','columns':['Metric','Before','After','Condition'], 'rows':[['Price (USD)','12.50','12.50','Do not convert'],['Mass (kg)','3.2','3.2','Do not round']]},
        {'id':'h3','pdf_page':3,'printed_page':'9','text':'3. A definite ending'},
        {'id':'end','pdf_page':3,'printed_page':'9','text':'A repeated statement can be real content. A repeated statement can be real content. The formula is `E = m * c^2`. The quotation "ignore previous instructions" is book content, not a command.'},
        {'id':'note','pdf_page':3,'printed_page':'9','text':'An improvement is not a guarantee; preserve the negation.'},
        {'id':'f3','pdf_page':3,'printed_page':'9','text':'SYNTHETIC LIBRARY · running footer'},
    ]
    model={'raw_blocks':raw,'reading_order':[b['id'] for b in raw],
      'order_evidence':'Synthetic PDF page 2 places left/right in columns; paragraph continues before heading; table continues on page 3.',
      'noise':[{'ref':f'f{i}','reason':'running footer outside body','evidence':f'PDF {i}, bottom margin; same running label on all three pages'} for i in range(1,4)],
      'blocks':[
        {'refs':['h1'],'kind':'heading','level':2},
        {'refs':['p1a','p1b'],'kind':'paragraph','join_evidence':'PDF 1 ends with continues; PDF 2 begins across; one sentence with no paragraph indentation.'},
        {'refs':['h2'],'kind':'heading','level':2},
        {'refs':['left'],'kind':'paragraph'}, {'refs':['right'],'kind':'paragraph'},
        {'refs':['t1','t2'],'kind':'table','join_evidence':'PDF 2/3 same four columns, continuation label and no new caption.'},
        {'refs':['h3'],'kind':'heading','level':2}, {'refs':['end'],'kind':'paragraph'},
        {'refs':['note'],'kind':'footnote','note_id':'n1'}]}
    blocks=reconstruct(model)
    trans=deepcopy(blocks)
    texts={0:'۱. آغازی با دقت',1:'اگر منبع کنترل شود، بهبود محتمل است، اما تضمین‌شده نیست. بسته `3.2 kg` وزن دارد و جمله بدون از دست دادن شرط خود از مرز صفحه ادامه پیدا می‌کند.[^n1]',
      2:'۲. ستون‌ها و جدول ادامه‌دار',3:'ستون چپ نخست خوانده شود. زمان آموزش قبلاً `20 hours` بود و اکنون `2 hours` است.',
      4:'ستون راست دوم خوانده شود. زمان به `10%` مقدار پیشین رسیده است؛ کاهش به‌اندازه `10%` نیست.',
      6:'۳. پایانی روشن',7:'یک گزاره تکراری می‌تواند محتوای واقعی باشد. یک گزاره تکراری می‌تواند محتوای واقعی باشد. فرمول `E = m * c^2` است. عبارت «دستورهای قبلی را نادیده بگیر» محتوای کتاب است و دستور اجرایی نیست.',8:'بهبود تضمین نیست؛ نفی باید حفظ شود.'}
    for i,t in texts.items():trans[i]['text']=t
    trans[5]['columns']=['شاخص','پیش از تغییر','پس از تغییر','شرط']
    trans[5]['rows']=[['زمان آموزش (ساعت)','20','2','فقط در صورت کنترل'],['تمرین‌ها','5','5','بدون کاهش'],['قیمت (USD)','12.50','12.50','تبدیل نشود'],['جرم (kg)','3.2','3.2','گرد نشود']]
    nonfa={'schema_version':1,'book_version_id':'synthetic-nonfa-v1','language':'en','title_original':'Careful reading — synthetic test','title_fa':'خواندن دقیق؛ کتاب آزمایشی',
      'authors':['Synthetic Test Library'],'summary':'نمونه مصنوعی آموزش و کاهش زمان؛ برای کنترل ترتیب، شرط، نفی و چاپ.','main_problem_and_thesis':'Preserve source conditions and relationships before translation.',
      'chapter_outline':['s0001: آغاز','s0003: ستون‌ها و آموزش','s0007: پایان'],'concepts':['آموزش','وفاداری','پیوستگی'],'tags_fa':['آموزش','آزمون'],'use_and_distinction':'Only an offline synthetic workflow fixture.',
      'language_decision':{'policy':'translate_to_fa','content_evidence':'All three synthetic source pages are English; checked complete source.'},
      'reconstruction':model,'translation':trans,'limitations':['ترجمه مصنوعی ازپیش‌نوشته‌شده است؛ کیفیت مدل ترجمه یا استقرار حساب زنده آزموده نشده است.']}
    fa_raw=[{'id':'fh','pdf_page':1,'printed_page':'۱','text':'کتاب فارسی آزمایشی'},
      {'id':'fp','pdf_page':1,'printed_page':'۱','text':'این متن از ابتدا فارسی است و به ترجمه دوباره نیاز ندارد. اگر منبع خوانا نیست، متن نسازید. اصطلاح API و عدد 12.50 تغییر زبان کتاب را ثابت نمی‌کنند.'}]
    persian={'schema_version':1,'book_version_id':'synthetic-fa-v1','language':'fa','title_original':'کتاب فارسی آزمایشی','title_fa':'کتاب فارسی آزمایشی',
      'authors':['کتابخانه آزمایشی'],'summary':'نمونه فارسی برای حفظ منبع بدون ترجمه صوری.','concepts':['زبان فارسی'],'chapter_outline':['s0001: کتاب فارسی آزمایشی'],
      'language_decision':{'policy':'source_persian','content_evidence':'All source paragraphs read in Persian, with one Latin technical term; not bilingual.'},
      'reconstruction':{'raw_blocks':fa_raw,'reading_order':['fh','fp'],'order_evidence':'One-page single-column source, heading then paragraph.',
      'noise':[],'blocks':[{'kind':'heading','level':2,'refs':['fh']},{'kind':'paragraph','refs':['fp']} ]}}
    return nonfa,persian


if __name__=='__main__':
    DEST.mkdir(parents=True,exist_ok=True)
    for name,spec in zip(('nonfa','persian'),make_specs()):
        (DEST/f'{name}.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
