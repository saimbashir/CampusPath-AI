"""Read teacher/student files into text with real source locations.

Never executes file content. Page/slide/paragraph labels come from the file itself;
nothing is invented. Works for any subject: there are no course-specific rules here.
"""
from app.config import MAX_PDF_PAGES,MAX_EXTRACTED_CHARS,OCR_SCANNED_PDF,MAX_OCR_PAGES
from io import BytesIO
from pathlib import Path
import re,shutil,subprocess,tempfile,zipfile,logging,os,time

TEXT_EXT={'.txt','.md','.csv','.tsv','.py','.cpp','.c','.h','.hpp','.java','.js','.ts','.html','.css','.json','.xml','.sql','.yaml','.yml','.r','.cs','.go','.rs','.kt','.swift','.log'}
OFFICE_CONVERT={'.ppt':'.pptx','.doc':'.docx','.odp':'.pptx','.odt':'.docx','.rtf':'.docx','.xls':'.xlsx','.ods':'.xlsx'}
SUPPORTED_EXT=TEXT_EXT|set(OFFICE_CONVERT)|{'.pdf','.docx','.pptx','.xlsx','.png','.jpg','.jpeg','.webp','.bmp','.tiff','.tif','.mp3','.wav','.m4a','.ogg','.webm','.mp4'}
log=logging.getLogger('campuspath.extract')

class DocumentError(ValueError):
    """Safe diagnostic suitable for the uploader; never includes file content."""

def _clean(text):
    # PostgreSQL rejects NUL; malformed PDF fonts can also emit invalid Unicode.
    return text.replace('\x00','').encode('utf-8','replace').decode('utf-8').strip()

def _zip_guard(data):
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            entries=archive.infolist()
            if len(entries)>5000 or sum(i.file_size for i in entries)>40*1024*1024:
                raise DocumentError('Document expands beyond the safety limit.')
            if any(i.flag_bits & 1 for i in entries):raise DocumentError('This Office file is encrypted. Save an unprotected copy.')
    except zipfile.BadZipFile as exc:raise DocumentError('Invalid Office document. Open it in Office and save a new copy.') from exc

def _converter():
    return shutil.which('libreoffice') or shutil.which('soffice') or next((str(p) for p in [Path(os.environ.get('ProgramFiles','C:/Program Files'))/'LibreOffice/program/soffice.exe',Path(os.environ.get('ProgramFiles(x86)','C:/Program Files (x86)'))/'LibreOffice/program/soffice.exe'] if p.is_file()),None)

def _convert_office(suffix,data):
    if suffix in {'.ppt','.doc','.xls'} and not data.startswith(bytes.fromhex('D0CF11E0A1B11AE1')):
        raise DocumentError('The file is not a valid legacy Office document. Save it using the correct format, not by renaming it.')
    if suffix in {'.odp','.odt','.ods'}:_zip_guard(data)
    if suffix=='.rtf' and not data.lstrip().startswith(b'{\\rtf'):raise DocumentError('Invalid RTF document.')
    exe=_converter()
    if not exe:raise DocumentError('Legacy Office conversion is unavailable on this server. Save as PPTX, DOCX or XLSX, or install LibreOffice.')
    target=OFFICE_CONVERT[suffix]
    with tempfile.TemporaryDirectory(prefix='cp-office-') as folder:
        root=Path(folder);src=root/('input'+suffix);src.write_bytes(data)
        profile=root/'profile';(profile/'user').mkdir(parents=True)
        # Fresh profile, highest macro security, never update external links. No inherited API keys.
        (profile/'user'/'registrymodifications.xcu').write_text('''<?xml version="1.0" encoding="UTF-8"?><oor:items xmlns:oor="http://openoffice.org/2001/registry"><item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop><prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop></item><item oor:path="/org.openoffice.Office.Writer/Content/Update"><prop oor:name="Link" oor:op="fuse"><value>0</value></prop></item></oor:items>''',encoding='utf-8')
        env={k:v for k,v in os.environ.items() if k in {'PATH','SystemRoot','WINDIR','COMSPEC','LANG','LC_ALL','LD_LIBRARY_PATH'}}
        env.update(HOME=folder,USERPROFILE=folder,TMPDIR=folder,TEMP=folder,TMP=folder,SAL_USE_VCLPLUGIN='svp')
        try:
            subprocess.run([exe,'-env:UserInstallation='+profile.as_uri(),'--headless','--nologo','--nodefault','--norestore','--convert-to',target[1:],'--outdir',folder,str(src)],env=env,cwd=folder,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=75,check=True)
        except subprocess.TimeoutExpired as exc:raise DocumentError('Office conversion timed out. Try saving a smaller PPTX, DOCX or XLSX copy.') from exc
        except (OSError,subprocess.CalledProcessError) as exc:raise DocumentError('Office conversion failed. The file may be damaged or password protected.') from exc
        converted=root/('input'+target)
        if not converted.is_file():raise DocumentError('Office conversion produced no document. Check for damage or password protection.')
        if converted.stat().st_size>40*1024*1024:raise DocumentError('Converted document exceeds the safety limit.')
        return target,converted.read_bytes()
CHUNK_TARGET=1300   # preferred excerpt size (characters)
CHUNK_MAX=1600      # hard ceiling (also the longest allowed citation quote)
SENTENCE=re.compile(r'(?<=[.!?؟۔])\s+(?=[\"“(\[]?[A-Z0-9؀-ۿ])')


def split_text(text,target=CHUNK_TARGET,maximum=CHUNK_MAX):
    """Split text into excerpts on paragraph/sentence boundaries, never mid-word.

    When a long paragraph has to be divided, the last sentence of one excerpt is repeated
    at the start of the next so an idea that crosses the boundary stays readable."""
    text=text.strip()
    if len(text)<=maximum:return [text] if text else []
    units=[]
    for block in re.split(r'\n\s*\n',text):
        block=block.strip()
        if not block:continue
        if len(block)<=maximum:units.append((block,False));continue
        for sentence in SENTENCE.split(block):
            sentence=sentence.strip()
            while len(sentence)>maximum:          # one enormous "sentence" (tables, code)
                cut=sentence.rfind(' ',0,target)
                cut=cut if cut>target//2 else target
                units.append((sentence[:cut].strip(),True));sentence=sentence[cut:].strip()
            if sentence:units.append((sentence,True))
    chunks=[];current=[];size=0
    for unit,inside_paragraph in units:
        if current and size+len(unit)+1>target:
            chunks.append('\n'.join(current))
            last=current[-1]
            current=[last] if inside_paragraph and len(last)<=300 else []
            size=sum(len(x)+1 for x in current)
        current.append(unit);size+=len(unit)+1
    if current:
        tail='\n'.join(current)
        if not chunks or tail!=chunks[-1]:chunks.append(tail)
    return [c for c in chunks if c.strip()]


def _ocr_pdf_pages(data,pages):
    """OCR selected 1-based pages of a scanned PDF. Needs pdftoppm + tesseract (free)."""
    import os
    if not pages or not shutil.which('pdftoppm') or not shutil.which('tesseract'):return {}
    result={};deadline=time.monotonic()+120
    with tempfile.TemporaryDirectory() as folder:
        source=Path(folder)/'input.pdf';source.write_bytes(data)
        for page in pages:
            if time.monotonic()>=deadline:break
            prefix=Path(folder)/f'p{page}'
            try:
                subprocess.run(['pdftoppm','-f',str(page),'-l',str(page),'-r','200','-gray','-png',str(source),str(prefix)],capture_output=True,timeout=max(1,min(30,deadline-time.monotonic())),check=True)
                images=sorted(Path(folder).glob(f'p{page}*.png'))
                if not images:continue
                out=subprocess.run(['tesseract',str(images[0]),'stdout','-l',os.getenv('OCR_LANGUAGE','eng')],capture_output=True,timeout=max(1,min(30,deadline-time.monotonic())),check=True)
                text=out.stdout.decode('utf-8','ignore').strip()
                if text:result[page]=text
                for image in images:image.unlink(missing_ok=True)
            except (subprocess.SubprocessError,OSError):continue
    return result


def _pdf_outline(pdf):
    """Map start page (1-based) -> top-level bookmark title, if the PDF has bookmarks."""
    starts={}
    try:
        for item in pdf.outline:
            if isinstance(item,list):continue          # nested children: sub-sections
            try:page=pdf.get_destination_page_number(item)+1
            except Exception:continue
            title=' '.join(str(getattr(item,'title','') or '').split())[:120]
            if title and page not in starts:starts[page]=title
    except Exception:
        return {}
    return starts


def _poppler_text(data):
    """Independent PDF reader with real page separators and a checked page limit."""
    if not shutil.which('pdfinfo') or not shutil.which('pdftotext'):raise DocumentError('PDF fallback unavailable. Install Poppler (included in the Railway Dockerfile).')
    with tempfile.TemporaryDirectory(prefix='cp-pdf-') as folder:
        source=Path(folder)/'input.pdf';source.write_bytes(data)
        try:
            info=subprocess.run(['pdfinfo',str(source)],capture_output=True,timeout=20)
            if info.returncode:
                if b'password' in info.stderr.lower():raise DocumentError('This PDF is password-protected. Save an unlocked copy.')
                raise DocumentError('Both PDF readers could not open the document. Export a new PDF from its original source.')
            match=re.search(rb'^Pages:\s*(\d+)',info.stdout,re.M)
            if not match:raise DocumentError('PDF page count could not be verified.')
            count=int(match[1])
            if not 0<count<=MAX_PDF_PAGES:raise DocumentError(f'PDF page limit is {MAX_PDF_PAGES}. Split into smaller files.')
            target=Path(folder)/'text.txt'
            subprocess.run(['pdftotext','-layout','-enc','UTF-8',str(source),str(target)],capture_output=True,timeout=45,check=True)
            if target.stat().st_size>MAX_EXTRACTED_CHARS*4:raise DocumentError('Extracted text exceeds the indexing limit.')
            texts=target.read_text(encoding='utf-8',errors='replace').split('\f')
            if len(texts)==count+1 and not texts[-1].strip():texts.pop()
            if len(texts)!=count:raise DocumentError('PDF page boundaries could not be verified. Export a fresh PDF.')
            return texts
        except subprocess.TimeoutExpired as exc:raise DocumentError('PDF reading timed out. Split the document into smaller files.') from exc
        except (OSError,subprocess.CalledProcessError) as exc:raise DocumentError('PDF fallback failed. Open the document and export a fresh PDF.') from exc


def _read_pdf(data):
    if b'%PDF-' not in data[:1024]:raise DocumentError('This is not a valid PDF file. Export a real PDF rather than renaming the extension.')
    texts=[];outline={};primary_failed=False
    try:
        from pypdf import PdfReader
        pdf=PdfReader(BytesIO(data),strict=False)
        if pdf.is_encrypted and not pdf.decrypt(''):raise DocumentError('This PDF is password-protected. Save an unlocked copy.')
        if not 0<len(pdf.pages)<=MAX_PDF_PAGES:raise DocumentError(f'PDF page limit is {MAX_PDF_PAGES}. Split the book into chapter files.')
        for page in pdf.pages:
            try:texts.append(_clean(page.extract_text() or ''))
            except Exception:texts.append('')
        outline=_pdf_outline(pdf)
    except DocumentError:raise
    except Exception as exc:
        primary_failed=True;log.warning('Primary PDF parser failed: %s',type(exc).__name__)
    # Poppler also helps when unusual fonts or broken text streams defeat pypdf.
    if primary_failed or not texts or any(len(t.strip())<25 for t in texts):
        try:
            alternate=_poppler_text(data)
            if primary_failed or not texts:texts=alternate;outline={}
            elif len(alternate)==len(texts):texts=[_clean(b) if len(a.strip())<25 and len(b.strip())>len(a.strip()) else a for a,b in zip(texts,alternate)]
        except DocumentError:
            if primary_failed or not texts:raise
    empty=[i+1 for i,t in enumerate(texts) if len(t.strip())<25]
    ocr=_ocr_pdf_pages(data,empty[:MAX_OCR_PAGES]) if OCR_SCANNED_PDF and empty else {}
    parts=[(f'Page {i+1} (OCR, verify)',ocr[i+1]) if i+1 in ocr and len(ocr[i+1].strip())>len(t.strip()) else (f'Page {i+1}',t) for i,t in enumerate(texts)]
    if not any(t.strip() for _,t in parts):raise DocumentError('No readable PDF text found. Scanned pages require Tesseract and Poppler OCR; check image quality or upload a text PDF.')
    return parts,outline


def _extract_sections(filename,data):
    """Return (parts, outline). parts = [(location, full text of that page/slide/...)]."""
    suffix=Path(filename).suffix.lower();outline={}
    if suffix in OFFICE_CONVERT:suffix,data=_convert_office(suffix,data)
    if suffix in {'.docx','.pptx','.xlsx'}:_zip_guard(data)
    if suffix in TEXT_EXT:
        try:
            text=data.decode('utf-16') if data.startswith((b'\xff\xfe',b'\xfe\xff')) else data.decode('utf-8-sig')
        except UnicodeDecodeError:raise DocumentError('Text files must use UTF-8 or UTF-16 with a byte-order mark.')
        if '\x00' in text:raise DocumentError('Binary data is not a text resource.')
        lines=text.splitlines();parts=[(f'Lines {i+1}–{min(i+35,len(lines))}','\n'.join(lines[i:i+35])) for i in range(0,len(lines),35)]
    elif suffix=='.pdf':
        parts,outline=_read_pdf(data)
    elif suffix=='.docx':
        from docx import Document
        doc=Document(BytesIO(data))
        parts=[]
        for i,p in enumerate(doc.paragraphs):
            style=(p.style.name if p.style is not None else '') or ''
            text=p.text
            # Word "Heading 1/2" styles become recognisable headings for chapter detection.
            level=re.match(r'Heading\s*(\d)',style)
            if level and text.strip() and not re.match(r'(chapter|unit|section|lesson|module|lecture|week|part|topic)\b|\d+(\.\d+)*\s',text.strip(),re.I):
                text=('Chapter: ' if level[1]=='1' else 'Section: ')+text.strip()
            parts.append((f'Paragraph {i+1}',text))
        parts += [(f'Table {i+1}','\n'.join(' | '.join(c.text for c in row.cells) for row in table.rows)) for i,table in enumerate(doc.tables)]
    elif suffix=='.pptx':
        from pptx import Presentation
        ppt=Presentation(BytesIO(data))
        parts=[]
        for i,slide in enumerate(ppt.slides):
            title=slide.shapes.title
            texts=([title.text] if title is not None and title.has_text_frame else [])
            texts.extend(shape.text for shape in slide.shapes if shape.has_text_frame and (title is None or shape.shape_id!=title.shape_id))
            # Tables and speaker notes often hold the real teaching content.
            for shape in slide.shapes:
                if getattr(shape,'has_table',False) and shape.has_table:
                    texts.append('\n'.join(' | '.join(c.text for c in row.cells) for row in shape.table.rows))
            try:
                if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
                    notes=slide.notes_slide.notes_text_frame.text.strip()
                    if notes:texts.append('Speaker notes: '+notes)
            except Exception:pass
            parts.append((f'Slide {i+1}','\n'.join(texts)))
    elif suffix=='.xlsx':
        from openpyxl import load_workbook
        # Never calculate formulas or follow workbook links. Bound sparse-sheet expansion.
        book=load_workbook(BytesIO(data),read_only=True,data_only=False,keep_links=False)
        parts=[];chars=0;cells=0;rows_seen=0
        try:
            for sheet in book.worksheets:
                if (sheet.max_column or 0)>256 or (sheet.max_row or 0)>20000:raise DocumentError('Spreadsheet exceeds the 256-column or 20,000-row per-sheet indexing limit.')
                for number,row in enumerate(sheet.iter_rows(values_only=True),1):
                    cells+=len(row);rows_seen+=1
                    if len(row)>256 or number>20000 or cells>250000 or rows_seen>30000:raise DocumentError('Spreadsheet exceeds the indexing limit. Split it into smaller sheets or CSV files.')
                    values=['' if v is None else str(v) for v in row]
                    if not any(values):continue
                    text=' | '.join(values).rstrip(' |');chars+=len(text)
                    if chars>MAX_EXTRACTED_CHARS:raise DocumentError('Extracted text exceeds the indexing limit.')
                    parts.append((f'Sheet {sheet.title[:45]} · Row {number}',text))
        finally:book.close()
    elif suffix in {'.png','.jpg','.jpeg','.webp','.bmp','.tiff','.tif'}:
        from app.documents.multimodal import image_ocr
        parts=image_ocr(data)
    elif suffix in {'.mp3','.wav','.m4a','.ogg','.webm'}:
        from app.documents.multimodal import transcribe
        parts=transcribe(data,filename)
    elif suffix=='.mp4':
        from app.documents.multimodal import video_transcript
        parts=video_transcript(data,suffix)
    else:
        raise DocumentError('Unsupported format. Use PDF, PPT/PPTX, DOC/DOCX, ODP/ODT, RTF, XLS/XLSX/ODS, text/code or supported image/audio/video files.')
    parts=[(location,_clean(text)) for location,text in parts if text and _clean(text)]
    if not parts:raise ValueError('No readable text found. Scanned documents need OCR first.')
    if sum(len(t) for _,t in parts)>MAX_EXTRACTED_CHARS:raise ValueError('Extracted text exceeds the indexing limit.')
    return parts,outline


def extract_sections(filename,data):
    """Public extraction boundary: safe diagnostics, no raw parser details exposed."""
    try:return _extract_sections(filename,data)
    except (DocumentError,ValueError):raise
    except Exception as exc:
        log.warning('Document parser failed (%s): %s',Path(filename).suffix.lower()[:12],type(exc).__name__)
        raise DocumentError('Document parser failed ('+type(exc).__name__+'). Open the original and save a fresh copy. If this persists, check server logs.') from exc


def extract(filename,data):
    """Compatibility API: excerpts of at most CHUNK_MAX characters with their locations."""
    parts,_=extract_sections(filename,data)
    output=[(location,segment) for location,text in parts for segment in split_text(text)]
    if not output:raise ValueError('No readable text found. Scanned documents need OCR first.')
    return output
