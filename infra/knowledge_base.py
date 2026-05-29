# ============================================================
# infra/knowledge_base.py — 知识库分块 + 关键词检索
# ============================================================
import logging, os, re

logger = logging.getLogger("infra.kb")

CHUNK_SIZE = 500
CHUNK_OVERLAP = 100

_kb_chunks: list[dict] = []
_kb_loaded = False


def _split_chunks(text, source):
    """将文本按段落分块，保持语义边界"""
    paragraphs = re.split(r'\n\s*\n', text)
    chunks = []
    current = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(current) + len(para) < CHUNK_SIZE:
            current += para + "\n"
        else:
            if current:
                chunks.append({"text": current.strip(), "source": source})
            # 单段超长：按句子切分强制写入
            if len(para) >= CHUNK_SIZE:
                sentences = re.split(r'(?<=[。！？；\n])', para)
                for sent in sentences:
                    sent = sent.strip()
                    if not sent:
                        continue
                    if len(current) + len(sent) < CHUNK_SIZE:
                        current += sent
                    else:
                        if current.strip():
                            chunks.append({"text": current.strip(), "source": source})
                        current = sent
            else:
                current = para + "\n"

    if current.strip():
        chunks.append({"text": current.strip(), "source": source})

    return chunks


def _tokenize(text):
    """中文用字符 bigram + 单字，英文/数字用空格分词，混合场景两套都跑"""
    tokens = []
    # CJK character bigrams
    cjk = re.findall(r'[一-鿿㐀-䶿]{2,}', text)
    for seg in cjk:
        for i in range(len(seg) - 1):
            tokens.append(seg[i:i + 2])
        tokens.append(seg[-1])  # 最后一个单字也加进去
    # Space-delimited tokens (English, numbers, mixed)
    non_cjk = re.sub(r'[一-鿿㐀-䶿]', ' ', text)
    tokens.extend(t.lower() for t in non_cjk.split() if len(t) >= 2)
    return set(tokens)


def _score_chunk(chunk_text, query):
    """混合 TF 评分：中文 bigram + 空格分词"""
    query_tokens = _tokenize(query)
    if not query_tokens:
        return 0
    text_lower = chunk_text.lower()
    score = sum(1 for t in query_tokens if t in text_lower)
    # 标题行加权
    for line in chunk_text.splitlines():
        if line.startswith("#") and any(t in line.lower() for t in query_tokens):
            score += 2
    return score

def load_knowledge_base(kb_dir=None):
    """加载知识库，分块存储"""
    global _kb_chunks, _kb_loaded

    if kb_dir is None:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        kb_dir = os.path.join(base, "knowledge_base")

    _kb_chunks = []

    if not os.path.isdir(kb_dir):
        logger.warning("[KB] directory not found: %s", kb_dir)
        _kb_loaded = True
        return

    for root, _, files in os.walk(kb_dir):
        for fn in files:
            if fn.endswith(".md"):
                try:
                    with open(os.path.join(root, fn), "r", encoding="utf-8") as f:
                        text = f.read()
                    rel_path = os.path.relpath(os.path.join(root, fn), kb_dir)
                    chunks = _split_chunks(text, rel_path)
                    _kb_chunks.extend(chunks)
                    logger.debug("[KB] %s -> %d chunks", rel_path, len(chunks))
                except Exception as e:
                    logger.warning("[KB] failed to read %s: %s", fn, e)

    _kb_loaded = True
    logger.info("[KB] loaded %d chunks from knowledge_base", len(_kb_chunks))


def retrieve(topic, keywords, api_key="", api_base="", top_k=8, max_chars=4000):
    """关键词检索知识库片段（中文 bigram TF 评分）"""
    global _kb_chunks

    if not _kb_chunks:
        return ""

    query = topic + " " + " ".join(keywords[:3])

    # TF 评分
    scored = []
    max_tf = 1
    for chunk in _kb_chunks:
        s = _score_chunk(chunk["text"], query)
        scored.append((chunk, s))
        if s > max_tf:
            max_tf = s

    # 归一化并排序
    scored = [(c, s / max(max_tf, 1)) for c, s in scored]
    scored.sort(key=lambda x: x[1], reverse=True)

    selected = [c for c, s in scored if s > 0][:top_k]
    if not selected:
        selected = [c for c, _ in scored[:5]]

    logger.info("[KB] query='%s' -> %d/%d chunks selected", topic[:40], len(selected), len(_kb_chunks))

    result = ""
    for chunk in selected:
        if len(result) + len(chunk["text"]) > max_chars:
            break
        result += f"<!-- {chunk['source']} -->\n{chunk['text']}\n\n"

    return result


def reload():
    """热重载知识库"""
    load_knowledge_base()
    return len(_kb_chunks)
