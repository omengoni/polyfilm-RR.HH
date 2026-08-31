"""Extracción de datos + clasificación de rol + score de un CV, vía API de Claude."""
import json
import ssl

import anthropic
import certifi
import httpx2

from config import load_cfg

# El SDK de anthropic usa httpx2, que por defecto valida certificados con
# 'truststore' (el almacén nativo de Windows). En Windows Server esa
# verificación tiene un bug conocido (RecursionError en el setter de
# verify_mode) que hace fallar la conexión con "Connection error." de forma
# intermitente. Se lo evita pasando un SSLContext armado con el bundle de
# certifi en vez de dejar que httpx2 use el validador nativo.
_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
_HTTP_CLIENT = httpx2.Client(verify=_SSL_CONTEXT)

SCHEMA = {
    "type": "object",
    "properties": {
        "nombre": {"type": "string", "description": "Nombre completo del candidato, o cadena vacía si no se encuentra."},
        "email": {"type": "string", "description": "Email de contacto, o cadena vacía si no se encuentra."},
        "telefono": {"type": "string", "description": "Teléfono de contacto, o cadena vacía si no se encuentra."},
        "localidad": {"type": "string", "description": "Localidad/ciudad de residencia del candidato, o cadena vacía si no se encuentra."},
        "rol_sugerido": {"type": "string", "description": "Nombre exacto del rol del catálogo que mejor corresponde."},
        "score": {"type": "integer", "description": "Puntaje de 0 a 100 de qué tan bien encaja el candidato en ese rol."},
        "justificacion": {"type": "string", "description": "1-3 oraciones explicando el score y la elección de rol."},
        "resumen": {"type": "string", "description": "Resumen breve (3-5 líneas) de experiencia y estudios del candidato."},
    },
    "required": ["nombre", "email", "telefono", "localidad", "rol_sugerido", "score", "justificacion", "resumen"],
    "additionalProperties": False,
}


def classify_cv(texto_cv: str, roles: list[dict]) -> dict:
    """roles: lista de dicts con 'nombre' y 'descripcion' de cada rol activo del catálogo."""
    cfg = load_cfg({"model": "claude-opus-5"})
    api_key = cfg.get("anthropic_api_key") or None
    client = anthropic.Anthropic(api_key=api_key, http_client=_HTTP_CLIENT) if api_key else anthropic.Anthropic(http_client=_HTTP_CLIENT)

    catalogo = "\n".join(f"- {r['nombre']}: {r['descripcion'] or ''}" for r in roles)

    system = (
        "Sos un asistente de RR.HH. de Polyfilm. Analizás el texto de un CV y devolvés "
        "datos de contacto (incluida la localidad/ciudad de residencia), un resumen breve, "
        "el rol del catálogo que mejor corresponde y un score de 0 a 100 de qué tan bien "
        "encaja para ese rol, con justificación. "
        "Si el CV no encaja claramente en ningún rol, usá 'Otros'. "
        "Si un dato de contacto no aparece en el texto, dejá el campo vacío en vez de inventarlo."
    )

    user_content = (
        f"Catálogo de roles disponibles:\n{catalogo}\n\n"
        f"Texto del CV:\n{texto_cv[:15000]}"
    )

    response = client.messages.create(
        model=cfg.get("model", "claude-opus-5"),
        max_tokens=2000,
        system=system,
        messages=[{"role": "user", "content": user_content}],
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
    )

    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)
