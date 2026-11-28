"""Subject-independent scope resolution and source metadata. No subject-specific templates."""
import re
from sqlalchemy import select
from fastapi import HTTPException
from app.models import Chunk,Resource,Topic
from app.schemas import Input
from pydantic import Field,model_validator
class MaterialScope(Input):
    resource_ids:list[int]=Field(default_factory=list,max_length=100)
    chunk_ids:list[int]=Field(default_factory=list,max_length=300)
    topic_ids:list[int]=Field(default_factory=list,max_length=100)
    topic_names:list[str]=Field(default_factory=list,max_length=100)
    chapters:list[str]=Field(default_factory=list,max_length=100)
    units:list[str]=Field(default_factory=list,max_length=100)
    sections:list[str]=Field(default_factory=list,max_length=100)
    clos:list[str]=Field(default_factory=list,max_length=40)
    page_from:int|None=Field(default=None,ge=1)
    page_to:int|None=Field(default=None,ge=1)
    heading:str=Field(default='',max_length=200)
    @model_validator(mode='after')
    def valid_range(self):
        if self.page_from and self.page_to and self.page_from>self.page_to:raise ValueError('Start page/slide must not exceed end.')
        return self

def source_metadata(location,text,structure=None):
    """Normalize older and new chunks; page/slide numbers come from actual file locations."""
    meta=dict(structure or {})
    match=re.match(r'(Page|Slide)\s+(\d+)\b',location,re.I)
    if match:
        key=match[1].lower()
        meta.setdefault(key,int(match[2]))
        if meta.get(key) is None:meta[key]=int(match[2])
        meta['position']=meta[key]
    elif isinstance(meta.get('page'),int) and meta['page']>0:
        meta['position']=meta['page']
    if not meta.get('heading'):
        lines=[line.strip().lstrip('#').strip() for line in text.splitlines() if line.strip()]
        if lines and len(lines[0])<=140 and len(lines[0].split())<=16 and not lines[0].endswith(('.', '?', '!')):
            meta['heading']=lines[0].rstrip(':')
        else:
            meta['heading']=meta.get('section_title') or meta.get('chapter_title') or ''
    return meta

def spread(rows,count):
    """Pick evenly across selected evidence, preserving source order."""
    if len(rows)<=count:return rows
    if count<=1:return rows[:1]
    return [rows[round(i*(len(rows)-1)/(count-1))] for i in range(count)]

# Heading patterns that work for any subject. Labels always come from the file itself.
CLASSIC=re.compile(r'^(chapter|unit|section)\s+([\w.\-]+)(?:\s*[:—\-]?\s*)(.*)$',re.I)
KEYWORD=re.compile(r'^(lesson|module|lecture|week|part|topic)\s+(\d+(?:\.\d+)*|[IVXLC]+)\b\s*[:—–\-.]?\s*(.*)$',re.I)
NAMED=re.compile(r'^(chapter|unit|section):\s+(.{2,100})$',re.I)          # Word "Heading 1/2" styles
NUMBERED=re.compile(r'^(\d{1,2})\.(\d{1,2})(?:\.\d{1,2})*\.?\s+([A-Z][^\n]{2,90})$')  # "4.2 Binary Trees"
KIND={'chapter':'chapter','lesson':'chapter','lecture':'chapter','week':'chapter','unit':'unit','module':'unit','part':'unit','section':'section','topic':'section'}

def heading(line):
    """Return (kind, label, title) when a line is a structural heading, else None."""
    title=line.strip().lstrip('#').strip()
    if not title or len(title)>120:return None
    m=CLASSIC.match(title)
    if m:return m[1].lower(),m[2].rstrip('.:'),title
    m=KEYWORD.match(title)
    if m:return KIND[m[1].lower()],m[2].rstrip('.'),title
    m=NAMED.match(title)
    if m:return m[1].lower(),m[2].strip()[:60],title
    m=NUMBERED.match(title)
    # Skip table-of-contents lines ("4.2 Binary Trees ........ 87") and full sentences.
    if m and not re.search(r'(\.{3,}|\s\d+)$',title) and not title.endswith('.') and len(title.split())<=12:
        return 'numbered',m[1]+'.'+m[2],title
    return None

def annotated(parts,filename,outline=None):
    """Yield (location, excerpt, structure) with book/unit/chapter/section/page labels.

    outline: optional {page: bookmark title} from the PDF, used as chapter labels when
    the page text itself has no recognisable chapter heading."""
    from app.documents.extract import split_text
    state={'book':filename};outline=outline or {}
    for location,text in parts:
        page=re.match(r'Page (\d+)',location);state['page']=int(page[1]) if page else None
        slide=re.match(r'Slide (\d+)',location);state['slide']=int(slide[1]) if slide else None
        state.pop('heading',None)
        state['heading']=source_metadata(location,text,{}).get('heading','')
        if state['page'] in outline:
            title=outline[state['page']];number=re.search(r'\b(\d+)\b',title)
            state['chapter']=number[1] if number else title[:60];state['chapter_title']=title
            state.pop('section',None);state.pop('section_title',None)
        segments=[];current=[]
        for line in text.splitlines():
            found=heading(line)
            if found:
                if current:segments.append((dict(state),'\n'.join(current)));current=[]
                kind,label,title=found
                if kind=='numbered':
                    chapter=label.split('.')[0]
                    if str(state.get('chapter','')).isdigit() or 'chapter' not in state:
                        if state.get('chapter')!=chapter:state['chapter']=chapter;state.pop('chapter_title',None)
                    kind='section'
                state[kind]=label;state[kind+'_title']=title
                if kind in ('unit','chapter'):
                    state.pop('section',None);state.pop('section_title',None)
                if kind=='unit':state.pop('chapter',None);state.pop('chapter_title',None)
            current.append(line)
        if current:segments.append((dict(state),'\n'.join(current)))
        for meta,body in segments:
            for piece in split_text(body):
                if piece.strip():yield location,piece.strip(),source_metadata(location,piece,meta)

def _filter_text(value):
    return ' '.join(re.sub(r'[^\w]+',' ',str(value or '').casefold()).split())

def _label_matches(value,meta,key):
    query=_filter_text(value)
    if not query:return False
    labels=[_filter_text(meta.get(key)),_filter_text(meta.get(key+'_title'))]
    if query in labels:return True
    # Accept a real chapter number even when PDF headings lack a separating space.
    bare=re.sub(r'^(chapter|unit|section|lecture|lesson|module)\s+','',query)
    if bare.isdigit():
        for label in labels:
            candidate=re.sub(r'^(chapter|unit|section|lecture|lesson|module)\s+','',label)
            if re.match(r'^'+re.escape(bare)+r'(?![0-9])',candidate):return True
    return any(query in label.split(' | ') or (' '+query+' ') in (' '+label+' ') for label in labels if label)

def _phrase_matches(query,*values):
    needle=_filter_text(query)
    return bool(needle) and any((' '+needle+' ') in (' '+_filter_text(v)+' ') for v in values)

def resolve(db,cid,scope,limit=300):
    """All selectors combine by intersection; omitted selectors mean all teacher material."""
    if isinstance(scope,dict):scope=MaterialScope.model_validate(scope)
    rows=db.execute(select(Chunk,Resource).join(Resource,Resource.id==Chunk.resource_id).where(Resource.course_id==cid,Resource.owner_id.is_(None),Resource.status=='ready').order_by(Resource.id,Chunk.id)).all()
    valid_resources={r.id for c,r in rows};valid_chunks={c.id for c,r in rows}
    if not set(scope.resource_ids)<=valid_resources:
        files=list(db.scalars(select(Resource).where(Resource.course_id==cid,Resource.owner_id.is_(None),Resource.id.in_(scope.resource_ids))))
        if {r.id for r in files}!=set(scope.resource_ids):raise HTTPException(422,'Scope contains inaccessible teacher material.')
        if any(r.status=='processing' for r in files):raise HTTPException(409,'Selected file is already uploaded and being indexed. Check Materials for its status.')
        raise HTTPException(409,'Selected file exists but has no ready indexed text. Check Materials for the processing error.')
    if not set(scope.chunk_ids)<=valid_chunks:raise HTTPException(422,'Scope contains inaccessible or unindexed teacher material.')
    topics=db.scalars(select(Topic).where(Topic.course_id==cid)).all()
    if not set(scope.topic_ids)<={t.id for t in topics}:raise HTTPException(422,'Topics must belong to this course.')
    selected=[t for t in topics if (not scope.topic_ids or t.id in scope.topic_ids) and (not scope.clos or t.clo in scope.clos)]
    if scope.topic_ids or scope.clos:
        source_ids=set(i for t in selected for i in (t.structure or {}).get('source_ids',[]))
        for t in selected:
            if (t.structure or {}).get('source_ids'):continue
            name=t.name.casefold().strip()
            if name:
                source_ids.update(c.id for c,r in rows if name in c.text.casefold() or name in str(source_metadata(c.location,c.text,c.structure).get('heading','')).casefold())
        if not source_ids:raise HTTPException(409,'No indexed teacher excerpts match the selected topic. Choose a document, page/slide range or heading instead.')
    else:source_ids=None
    manual_labels={key:{c.id for c,r in rows if any(c.id in (t.structure or {}).get('source_ids',[]) and any(_label_matches(value,t.structure or {},key) for value in values) for t in topics if not (t.structure or {}).get('automatic_material_topic'))} for key,values in [('chapter',scope.chapters),('unit',scope.units),('section',scope.sections)] if values}
    typed_topics=[name.strip() for name in scope.topic_names if name.strip()]
    typed_ids={i for t in topics if any(_filter_text(t.name)==_filter_text(name) for name in typed_topics) for i in (t.structure or {}).get('source_ids',[])}
    heading_pages=set();topic_pages=set()
    for c,r in rows:
        m=source_metadata(c.location,c.text,c.structure)
        position=m.get('position')
        if not position:continue
        key=(r.id,c.location.split(' · ')[0],position)
        if scope.heading and _phrase_matches(scope.heading,m.get('heading'),m.get('chapter_title'),m.get('section_title'),c.text):heading_pages.add(key)
        if typed_topics and (c.id in typed_ids or any(_phrase_matches(name,m.get('heading'),m.get('chapter_title'),m.get('section_title'),c.text) for name in typed_topics)):topic_pages.add(key)
    result=[]
    for c,r in rows:
        m=source_metadata(c.location,c.text,c.structure)
        if scope.resource_ids and r.id not in scope.resource_ids:continue
        if scope.chunk_ids and c.id not in scope.chunk_ids:continue
        if source_ids is not None and c.id not in source_ids:continue
        if any(values and c.id not in manual_labels.get(key,set()) and not any(_label_matches(value,m,key) for value in values) for key,values in [('chapter',scope.chapters),('unit',scope.units),('section',scope.sections)]):continue
        position=m.get('position')
        if scope.page_from and (not position or position<scope.page_from):continue
        if scope.page_to and (not position or position>scope.page_to):continue
        key=(r.id,c.location.split(' · ')[0],position)
        if scope.heading and key not in heading_pages and not _phrase_matches(scope.heading,m.get('heading'),m.get('chapter_title'),m.get('section_title'),c.text):continue
        if typed_topics and key not in topic_pages and c.id not in typed_ids and not any(_phrase_matches(name,m.get('heading'),m.get('chapter_title'),m.get('section_title'),c.text) for name in typed_topics):continue
        result.append({'id':c.id,'resource_id':r.id,'filename':r.filename,'location':c.location,'text':c.text,'structure':m})
    if not result:
        states=list(db.execute(select(Resource.filename,Resource.status,Resource.status_detail).where(Resource.course_id==cid,Resource.owner_id.is_(None))).all())
        if not rows and states:
            if any(status=='processing' for _,status,_ in states):raise HTTPException(409,'Course files are uploaded and being indexed. Open Materials to check their processing status.')
            raise HTTPException(409,'Course files exist but contain no ready indexed text. Check the file status in Materials; a scanned/image-only file may need readable text.')
        raise HTTPException(409,'The provided course material does not contain enough information to answer this confidently. No indexed excerpts match the selected scope.')
    if limit is not None and len(result)>limit:raise HTTPException(422,f'Scope contains {len(result)} excerpts; select a chapter or documents with at most {limit} excerpts for this operation.')
    return result

def source_topic(db,cid,source,topics):
    # The existing mastery schema requires a Topic foreign key. Create only a
    # deterministic, source-linked heading from authorized material when needed.
    for topic in topics:
        if source['id'] in (topic.structure or {}).get('source_ids',[]):return topic
    structure=source.get('structure') or {}
    name=structure.get('heading') or structure.get('section_title') or f"{source['filename']} · {source['location']}"
    topic=Topic(course_id=cid,name=name[:140],description=source['text'][:6000],prerequisites=[],clo='Material practice',difficulty=1,
                structure={**structure,'source_ids':[source['id']],'automatic_material_topic':True})
    db.add(topic);db.flush();topics.append(topic);return topic


_FOLD=str.maketrans({'‘':"'",'’':"'",'“':'"','”':'"','–':'-','—':'-','\u00a0':' ','…':'...'})
def _norm(text):return ' '.join(text.translate(_FOLD).split()).casefold()

def _words(text):
    """[(normalized word, start, end)] for a text; punctuation and quote styles ignored."""
    return [(re.sub(r'[^\w]','',m[0].translate(_FOLD)).casefold(),m.start(),m.end()) for m in re.finditer(r'\S+',text)]

def repair_quote(quote,source):
    """Return the exact source wording for a quote, or None if it is not really there.

    AI models often change quote marks, spacing, dashes or a word or two. Small differences
    are repaired to the teacher's exact source text; invented quotations are still rejected."""
    q=_norm(quote)
    if len(q)<8:return None
    if q in _norm(source):return quote
    from difflib import SequenceMatcher
    qw=[w for w,_,_ in _words(quote) if w];sw=[x for x in _words(source) if x[0]]
    if len(qw)<3 or not sw:return None
    blocks=[b for b in SequenceMatcher(None,qw,[w for w,_,_ in sw],autojunk=False).get_matching_blocks() if b.size]
    if not blocks:return None
    # Use the densest run of matches so scattered common words do not count.
    best=None
    for a in range(len(blocks)):
        for b in range(a,len(blocks)):
            first,last=blocks[a],blocks[b]
            span=last.b+last.size-first.b
            if span>len(qw)*1.4+2:break
            matched=sum(x.size for x in blocks[a:b+1])
            if not best or matched>best[0]:best=(matched,first,last)
    matched,first,last=best
    if matched/len(qw)<0.8:return None
    start=max(0,first.b-first.a);end=min(len(sw)-1,last.b+last.size-1+(len(qw)-last.a-last.size))
    return source[sw[start][1]:sw[end][2]].strip()

def validate_citations(citations,evidence):
    mapping={s['id']:s for s in evidence}
    if not citations:raise ValueError('At least one source citation is required.')
    for c in citations:
        data=c.model_dump() if hasattr(c,'model_dump') else c
        if data['chunk_id'] not in mapping:raise ValueError('Citation falls outside selected material.')
        fixed=repair_quote(data['quote'].strip(),mapping[data['chunk_id']]['text'])
        if fixed is None:raise ValueError('Evidence quotation is not present in the cited source.')
        if fixed!=data['quote']:
            if hasattr(c,'model_dump'):c.quote=fixed
            else:c['quote']=fixed
    return [mapping[c.chunk_id if hasattr(c,'chunk_id') else c['chunk_id']] for c in citations]
