"""RAG casero sobre documentos internos: partir en fragmentos, embeber con
Voyage AI (partner de embeddings recomendado por Anthropic — Claude no tiene
API de embeddings propia), guardar los vectores en SQLite como BLOB, y buscar
por similitud coseno en memoria (alcanza de sobra para un corpus de decenas/
pocos cientos de documentos — no hace falta una base vectorial dedicada)."""
import numpy as np

from config import load_cfg
from db import get_db

MODELO_EMBEDDING = "voyage-4-lite"
TAM_CHUNK = 1200
SOLAPAMIENTO = 150
TOP_K = 5


def voyage_configurado() -> bool:
    return bool(load_cfg().get("voyage_api_key"))


def _cliente_voyage():
    import voyageai
    api_key = load_cfg().get("voyage_api_key")
    if not api_key:
        raise RuntimeError("Falta configurar voyage_api_key en rrhh.cfg.")
    return voyageai.Client(api_key=api_key)


def chunk_texto(texto: str, tam_max: int = TAM_CHUNK, solapamiento: int = SOLAPAMIENTO) -> list[str]:
    parrafos = [p.strip() for p in texto.split("\n") if p.strip()]
    chunks = []
    actual = ""
    for p in parrafos:
        if len(actual) + len(p) + 1 <= tam_max:
            actual = (actual + "\n" + p).strip()
            continue
        if actual:
            chunks.append(actual)
            actual = ""
        if len(p) > tam_max:
            paso = max(tam_max - solapamiento, 1)
            for i in range(0, len(p), paso):
                chunks.append(p[i:i + tam_max])
        else:
            actual = p
    if actual:
        chunks.append(actual)
    return chunks


def _serializar(vector) -> bytes:
    return np.asarray(vector, dtype=np.float32).tobytes()


def _deserializar(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def embeber_documento(texto: str) -> list[tuple[str, bytes]]:
    """Parte el texto en chunks y devuelve [(texto_chunk, embedding_blob), ...]."""
    chunks = chunk_texto(texto)
    if not chunks:
        return []
    vo = _cliente_voyage()
    resultado = vo.embed(chunks, model=MODELO_EMBEDDING, input_type="document")
    return list(zip(chunks, [_serializar(e) for e in resultado.embeddings]))


def buscar_relevantes(pregunta: str, categoria: str | None = None, top_k: int = TOP_K) -> list[dict]:
    """Devuelve los top_k chunks más relevantes a la pregunta, con su documento de origen."""
    vo = _cliente_voyage()
    query_embd = np.asarray(
        vo.embed([pregunta], model=MODELO_EMBEDDING, input_type="query").embeddings[0],
        dtype=np.float32,
    )

    conn = get_db()
    sql = """
        SELECT c.texto, c.embedding, d.id AS documento_id, d.titulo, d.categoria
        FROM documento_chunks c
        JOIN documentos d ON d.id = c.documento_id
        WHERE d.activo = 1
    """
    params = []
    if categoria:
        sql += " AND d.categoria = ?"
        params.append(categoria)
    filas = conn.execute(sql, params).fetchall()
    conn.close()

    if not filas:
        return []

    matriz = np.stack([_deserializar(f["embedding"]) for f in filas])
    similitudes = matriz @ query_embd  # embeddings normalizados -> dot product = cos sim
    top_idx = np.argsort(-similitudes)[:top_k]

    return [
        {
            "texto": filas[i]["texto"],
            "documento_id": filas[i]["documento_id"],
            "titulo": filas[i]["titulo"],
            "categoria": filas[i]["categoria"],
            "similitud": float(similitudes[i]),
        }
        for i in top_idx
    ]


def responder_pregunta(pregunta: str, categoria: str | None = None) -> dict:
    """Busca contexto relevante y le pide a Claude que responda basándose en eso."""
    import anthropic

    fragmentos = buscar_relevantes(pregunta, categoria=categoria)
    if not fragmentos:
        return {
            "respuesta": "Todavía no hay documentos cargados (o ninguno coincide con ese filtro) para responder esto.",
            "fuentes": [],
        }

    contexto = "\n\n---\n\n".join(
        f"[Documento: {f['titulo']}]\n{f['texto']}" for f in fragmentos
    )
    cfg = load_cfg({"model": "claude-opus-5"})
    api_key = cfg.get("anthropic_api_key") or None
    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    system = (
        "Sos un asistente interno de RR.HH. de Polyfilm. Respondé la pregunta del usuario "
        "basándote ÚNICAMENTE en los fragmentos de documentos que se te dan a continuación. "
        "Si la respuesta no está en esos fragmentos, decí claramente que no tenés esa información "
        "en los documentos cargados — no inventes ni completes con conocimiento general."
    )
    mensaje = f"Fragmentos de documentos:\n\n{contexto}\n\nPregunta: {pregunta}"

    response = client.messages.create(
        model=cfg.get("model", "claude-opus-5"),
        max_tokens=1500,
        system=system,
        messages=[{"role": "user", "content": mensaje}],
    )
    texto_respuesta = next(b.text for b in response.content if b.type == "text")

    fuentes = list({f["titulo"]: f["documento_id"] for f in fragmentos}.items())
    return {
        "respuesta": texto_respuesta,
        "fuentes": [{"titulo": t, "documento_id": did} for t, did in fuentes],
    }
