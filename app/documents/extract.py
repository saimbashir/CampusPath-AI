"""Read teacher/student files into text with real source locations.

Never executes file content. Page/slide/paragraph labels come from the file itself;
nothing is invented. Works for any subject: there are no course-specific rules here.
"""
from app.config import MAX_PDF_PAGES,MAX_EXTRACTED_CHARS,OCR_SCANNED_PDF,MAX_OCR_PAGES
from io import BytesIO
from pathlib import Path
import re,shutil,subprocess,tempfile,zipfile

TEXT_EXT={'.txt','.md','.csv','.py','.cpp','.c','.java','.js','.html','.css','.json'}
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
    result={}
    with tempfile.TemporaryDirectory() as folder:
        source=Path(folder)/'input.pdf';source.write_bytes(data)
        for page in pages:
            prefix=Path(folder)/f'p{page}'
            try:
                subprocess.run(['pdftoppm','-f',str(page),'-l',str(page),'-r','200','-gray','-png',str(source),str(prefix)],capture_output=True,timeout=60,check=True)
                images=sorted(Path(folder).glob(f'p{page}*.png'))
                if not images:continue
                out=subprocess.run(['tesseract',str(images[0]),'stdout','-l',os.getenv('OCR_LANGUAGE','eng')],capture_output=True,timeout=60,check=True)
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


def extract_sections(filename,data):
    """Return (parts, outline). parts = [(location, full text of that page/slide/...)]."""
    suffix=Path(filename).suffix.lower();outline={}
    if suffix in {'.docx','.pptx'}:
        try:
            with zipfile.ZipFile(BytesIO(data)) as archive:
                entries=archive.infolist()
                if len(entries)>5000 or sum(i.file_size for i in entries)>40*1024*1024:
                    raise ValueError('Document expands beyond the safety limit.')
        except zipfile.BadZipFile: raise ValueError('Invalid Office document.')
    if suffix in TEXT_EXT:
        try:text=data.decode('utf-8-sig')
        except UnicodeDecodeError:raise ValueError('Text files must use UTF-8 encoding.')
        if '\x00' in text:raise ValueError('Binary data is not a text resource.')
        lines=text.splitlines();parts=[(f'Lines {i+1}–{min(i+35,len(lines))}','\n'.join(lines[i:i+35])) for i in range(0,len(lines),35)]
    elif suffix=='.pdf':
        from pypdf import PdfReader
        pdf=PdfReader(BytesIO(data))
        if pdf.is_encrypted:
            try:pdf.decrypt('')
            except Exception:raise ValueError('This PDF is password-protected. Remove the password and upload again.')
        if len(pdf.pages)>MAX_PDF_PAGES:raise ValueError(f'PDF page limit is {MAX_PDF_PAGES}. Split the book into chapter files.')
        texts=[]
        for page in pdf.pages:
            try:texts.append(page.extract_text() or '')
            except Exception:texts.append('')
        outline=_pdf_outline(pdf)
        # Scanned pages have (almost) no text layer: read them with free OCR when available.
        empty=[i+1 for i,t in enumerate(texts) if len(t.strip())<25]
        ocr={}
        if OCR_SCANNED_PDF and empty:ocr=_ocr_pdf_pages(data,empty[:MAX_OCR_PAGES])
        parts=[]
        for i,t in enumerate(texts):
            if i+1 in ocr:parts.append((f'Page {i+1} (OCR, verify)',ocr[i+1]))
            else:parts.append((f'Page {i+1}',t))
        if empty and not ocr and all(len(t.strip())<25 for t in texts):
            raise ValueError('This PDF is scanned (no text layer). Install Tesseract and Poppler on the server, or upload a text PDF.')
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
    elif suffix in {'.png','.jpg','.jpeg','.webp'}:
        from app.documents.multimodal import image_ocr
        parts=image_ocr(data)
    elif suffix in {'.mp3','.wav','.m4a','.ogg','.webm'}:
        from app.documents.multimodal import transcribe
        parts=transcribe(data,filename)
    elif suffix=='.mp4':
        from app.documents.multimodal import video_transcript
        parts=video_transcript(data,suffix)
    else:
        raise ValueError('Unsupported format. Use documents, images, supported audio/video, text or code.')
    parts=[(location,text.strip()) for location,text in parts if text and text.strip()]
    if not parts:raise ValueError('No readable text found. Scanned documents need OCR first.')
    if sum(len(t) for _,t in parts)>MAX_EXTRACTED_CHARS:raise ValueError('Extracted text exceeds the indexing limit.')
    return parts,outline


def extract(filename,data):
    """Compatibility API: excerpts of at most CHUNK_MAX characters with their locations."""
    parts,_=extract_sections(filename,data)
    output=[(location,segment) for location,text in parts for segment in split_text(text)]
    if not output:raise ValueError('No readable text found. Scanned documents need OCR first.')
    return output
