"""Real legacy Office conversion, independent PDF fallback, safe retry authorization."""
from io import BytesIO
from pathlib import Path
import shutil,subprocess
import pytest
import app.documents.extract as ex
from app.documents.extract import extract,extract_sections,DocumentError
from app.db import SessionLocal
from app.models import Resource,ResourceBlob,Chunk
from sqlalchemy import select

SAMPLE=Path(__file__).parents[1]/'sample_data'/'universal'/'CN_Lecture_01.pdf'


def test_pdf_fallback_keeps_real_pages(monkeypatch):
    if not shutil.which('pdftotext') or not shutil.which('pdfinfo'):pytest.skip('Poppler unavailable')
    import pypdf
    data=SAMPLE.read_bytes()
    original,_=extract_sections('lecture.pdf',data)
    def broken(*args,**kwargs):raise RuntimeError('Synthetic primary parser failure')
    monkeypatch.setattr(pypdf,'PdfReader',broken)
    fallback,_=extract_sections('lecture.pdf',data)
    assert fallback and [p for p,_ in fallback]==[p for p,_ in original]
    assert 'Chapter 1' in ' '.join(t for _,t in fallback)


def test_short_text_pdf_and_encryption(monkeypatch):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject,DictionaryObject,NameObject
    w=PdfWriter();page=w.add_blank_page(width=300,height=300)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
    stream=DecodedStreamObject();stream.set_data(b'BT /F1 18 Tf 20 200 Td (Counting Sort) Tj ET')
    page[NameObject('/Contents')]=w._add_object(stream)
    out=BytesIO();w.write(out)
    monkeypatch.setattr(ex,'OCR_SCANNED_PDF',False)
    assert extract('short.pdf',out.getvalue())==[('Page 1','Counting Sort')]
    w.encrypt('private-password');locked=BytesIO();w.write(locked)
    with pytest.raises(DocumentError,match='password-protected'):extract('locked.pdf',locked.getvalue())
    with pytest.raises(DocumentError,match='not a valid PDF'):extract('renamed.pdf',b'not a PDF')


@pytest.mark.parametrize('source,target,text',[('pptx','ppt','Counting Sort'),('docx','doc','Radix sort processes digits'),('pptx','odp','Counting Sort'),('docx','odt','Radix sort processes digits'),('docx','rtf','Radix sort processes digits')])
def test_real_office_conversion(tmp_path,source,target,text):
    exe=ex._converter()
    if not exe:pytest.skip('LibreOffice unavailable')
    original=tmp_path/('lecture.'+source)
    if source=='pptx':
        from pptx import Presentation
        p=Presentation();slide=p.slides.add_slide(p.slide_layouts[1]);slide.shapes.title.text=text;slide.placeholders[1].text='Integer keys and count arrays.';p.save(original)
    else:
        from docx import Document
        d=Document();d.add_paragraph(text);d.save(original)
    subprocess.run([exe,'-env:UserInstallation='+(tmp_path/'generator').as_uri(),'--headless','--convert-to',target,'--outdir',str(tmp_path),str(original)],check=True,capture_output=True,timeout=60)
    converted=tmp_path/('lecture.'+target)
    parts=extract(converted.name,converted.read_bytes())
    assert text in ' '.join(t for _,t in parts)
    assert parts[0][0]==('Slide 1' if source=='pptx' else 'Paragraph 1')


def test_retry_existing_failed_upload_is_private_and_preserves_id(clients,monkeypatch):
    teacher,_=clients('teacher@campuspath.demo');student,_=clients('saim@campuspath.demo');other,_=clients('other@campuspath.demo')
    from app.services import indexing
    with SessionLocal() as db:
        r=Resource(course_id=1,owner_id=None,filename='retry.pdf',kind='COURSE MATERIAL',status='failed',status_detail='Old parser failed');db.add(r);db.flush();rid=r.id
        db.add(ResourceBlob(resource_id=rid,data=SAMPLE.read_bytes(),content_type='application/pdf'));db.commit()
    url=f'/api/courses/1/resources/{rid}/retry'
    monkeypatch.setattr(indexing,'start_background',lambda r:indexing._background(r))
    assert student.post(url,json={}).status_code==404
    assert other.post(url,json={}).status_code==404
    assert teacher.post(url,json={}).status_code==202
    assert teacher.post(url,json={}).status_code==409
    payload=teacher.get(f'/api/courses/1/resources/{rid}').json()
    assert payload['status']=='ready' and payload['chunks']
    assert student.get(f'/api/courses/1/resources/{rid}').json()['chunks']==payload['chunks']
    with SessionLocal() as db:
        assert db.get(Resource,rid).status=='ready'
        assert db.get(ResourceBlob,rid).data==SAMPLE.read_bytes()
        assert len(db.scalars(select(Chunk).where(Chunk.resource_id==rid)).all())==len(payload['chunks'])


def test_clean_invalid_pdf_characters_and_unsupported_extension():
    assert ex._clean('A\x00B\ud800')=='AB?'
    with pytest.raises(DocumentError,match='Unsupported format'):extract('program.exe',b'not allowed')


def test_scanned_pdf_real_ocr():
    if not shutil.which('tesseract') or not shutil.which('pdftoppm'):pytest.skip('OCR tools unavailable')
    from PIL import Image,ImageDraw,ImageFont
    image=Image.new('RGB',(1200,600),'white');draw=ImageDraw.Draw(image)
    try:font=ImageFont.truetype('DejaVuSans.ttf',48)
    except OSError:pytest.skip('Test font unavailable')
    draw.text((55,100),'Counting sort uses integer keys.',font=font,fill='black')
    output=BytesIO();image.save(output,format='PDF',resolution=150)
    parts=extract('scanned.pdf',output.getvalue())
    assert parts[0][0]=='Page 1 (OCR, verify)' and 'counting sort' in parts[0][1].lower()


@pytest.mark.parametrize('target',['xlsx','xls','ods'])
def test_spreadsheet_rows_and_formula_text(tmp_path,target):
    from openpyxl import Workbook
    w=Workbook();ws=w.active;ws.title='Algorithms';ws.append(['Algorithm','Complexity']);ws.append(['Counting sort','O(n+k)']);ws.append(['Formula','=1+2']);p=tmp_path/'sheet.xlsx';w.save(p)
    if target!='xlsx':
        exe=ex._converter()
        if not exe:pytest.skip('LibreOffice unavailable')
        subprocess.run([exe,'-env:UserInstallation='+(tmp_path/'generator').as_uri(),'--headless','--convert-to',target,'--outdir',str(tmp_path),str(p)],check=True,capture_output=True,timeout=60)
        p=tmp_path/('sheet.'+target)
    parts=extract(p.name,p.read_bytes())
    assert parts[1]==('Sheet Algorithms · Row 2','Counting sort | O(n+k)')
    assert '=1+2' in parts[2][1]
