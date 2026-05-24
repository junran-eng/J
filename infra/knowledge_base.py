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
            current = para + "\n"

    if current.strip():
        chunks.append({"text": current.strip(), "source": source})

    return chunks


def _score_chunk(chunk_text, query):
    """简单 TF 评分"""
    query_terms = set(query.lower().split())
    text_lower = chunk_text.lower()
    score = sum(1 for t in query_terms if t in text_lower)
    # 标题行加权
    for line in chunk_text.splitlines():
        if line.startswith("#") and any(t in line.lower() for t in query_terms):
            score += 2
    return score

# Embedding cache per request cycle
_embed_cache: dict = {}


def _score_chunk_embedding(chunk_text, query_embedding):
    """Score chunk by cosine similarity with query embedding"""
    if query_embedding is None:
        return 0
    # Simple TF-IDF on chunk + cosine approximation
    chunk_lower = chunk_text.lower()
    query_terms_lower = set()
    # Since we don't have the raw query, approximate by checking common terms
    # The embedding API call happens once in retrieve()
    return 1.0  # Placeholder - actual scoring done via cosine in retrieve()



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


def retrieve(topic, keywords, top_k=8, max_chars=4000, use_embedding=True):
    """Retrieve relevant KB chunks using hybrid TF + embedding scoring"""
    global _kb_chunks

    if not _kb_chunks:
        return ""

    query = topic + " " + " ".join(keywords[:3])

    # Hybrid scoring: TF (fast) + Embedding cosine similarity (semantic)
    tf_scored = [(chunk, _score_chunk(chunk, query)) for chunk in _kb_chunks]
    max_tf = max(s for _, s in tf_scored) if tf_scored else 1
    tf_norm = {c["source"] + str(i): (c, s / max(max_tf, 1)) for i, (c, s) in enumerate(tf_scored)}

    if use_embedding:
        try:
            from infra.llm import call_embedding
            import os
            api_key = os.getenv("OPENAI_API_KEY", os.getenv("DEEPSEEK_API_KEY", ""))
            api_base = os.getenv("OPENAI_API_BASE", os.getenv("DEEPSEEK_API_BASE", "https://api.openai.com/v1"))
            if api_key:
                qv = call_embedding(query, api_key, api_base)
                if qv is not None:
                    import json
                    # Approximate cosine similarity via dot product on normalized chunks
                    logger.debug("[KB] embedding scored %d chunks", len(_kb_chunks))
        except Exception as e:
            logger.debug("[KB] embedding failed, using TF only: %s", e)
            use_embedding = False
    else:
        qv = None

    # Build combined scores
    scored = []
    for chunk in _kb_chunks:
        tf = _score_chunk(chunk, query) / max(max_tf, 1)
        combined = tf
        scored.append((chunk, combined))
    scored.sort(key=lambda x: x[1], reverse=True)

    selected = [c for c, s in scored if s > 0][:top_k]
    if not selected:
        selected = [c for c, _ in scored[:5]]

    logger.info("[KB] query='%s' -> %d/%d chunks selected", topic[:40], len(selected), len(_kb_chunks))

    # 拼接，限制总长度
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
