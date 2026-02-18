import requests
import json
import logging
import os
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

OPENCLAW_URL = os.environ.get("OPENCLAW_URL", "http://openclaw:18789")
OPENCLAW_TOKEN = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "83fb8d8074f3ea57fd1cf3ac8300013af3404d43da42a9f865ca3e0126d5c824")

def get_headers() -> Dict[str, str]:
    """Obtiene los headers con el token de autorización"""
    return {
        "Authorization": f"Bearer {OPENCLAW_TOKEN}",
        "Content-Type": "application/json"
    }


# Contexto de seguridad residencial para el agente
SECURITY_CONTEXT = """
Eres un asistente de seguridad residencial experto. Tienes conocimiento sobre:
- Sistemas de seguridad para casas
- Cámaras de vigilancia (Domo, Bullet, PTZ, WiFi)
- Alarmas y sensores (movimiento, humo, gas, temperatura)
- Cercos eléctricos
- Control de acceso (huellas, tarjetas, reconocimiento facial)
- Iluminación automatizada
- Recomendaciones de seguridad

Ayudas a los usuarios con información sobre sistemas de seguridad, cámaras, alarmas, sensores, 
cercos eléctricos, control de acceso y consejos de seguridad para el hogar.

Responde de manera clara, útil y concisa. Si no sabes algo, admítelo honestamente.
"""

def process_message_through_openclaw(user_id: str, message: str, context: str = "") -> Optional[str]:
    """
    Procesa un mensaje a través de OpenClaw Agent.
    Returns la respuesta del agente o None si falla.
    """
    try:
        # Construir el prompt con contexto de seguridad
        full_context = f"{SECURITY_CONTEXT}\n\nContexto adicional: {context}"
        
        # Consultar al agente de OpenClaw
        response = requests.post(
            f"{OPENCLAW_URL}/api/agent",
            json={
                "message": f"Usuario dice: {message}",
                "thinking": "high",
                "context": full_context,
                "user_id": user_id
            },
            headers=get_headers(),
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            return result.get("response", None)
        else:
            logger.error(f"Error de OpenClaw: {response.status_code} - {response.text}")
            return None
            
    except requests.exceptions.ConnectionError:
        logger.error("No se pudo conectar con OpenClaw")
        return None
    except Exception as e:
        logger.error(f"Error al procesar mensaje: {e}")
        return None

def send_via_openclaw(to: str, message: str, channel: str = "telegram") -> bool:
    """Envía un mensaje usando OpenClaw"""
    try:
        response = requests.post(
            f"{OPENCLAW_URL}/api/message/send",
            json={
                "to": to,
                "message": message,
                "channel": channel
            },
            headers=get_headers(),
            timeout=30
        )
        if response.status_code == 200:
            logger.info(f"Mensaje enviado vía OpenClaw a {to}")
            return True
        else:
            logger.error(f"Error de OpenClaw: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"Error al conectar con OpenClaw: {e}")
        return False

def query_agent(message: str, thinking: str = "high") -> str:
    """Consulta al agente de OpenClaw"""
    try:
        response = requests.post(
            f"{OPENCLAW_URL}/api/agent",
            json={
                "message": message,
                "thinking": thinking,
                "context": SECURITY_CONTEXT
            },
            headers=get_headers(),
            timeout=60
        )
        if response.status_code == 200:
            result = response.json()
            return result.get("response", "No hay respuesta")
        else:
            logger.error(f"Error de OpenClaw: {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Error al conectar con OpenClaw: {e}")
        return None

def is_openclaw_available() -> bool:
    """Verifica si OpenClaw está disponible"""
    try:
        response = requests.get(f"{OPENCLAW_URL}/health", timeout=5)
        return response.status_code == 200
    except:
        return False

def get_openclaw_status() -> Dict[str, Any]:
    """Obtiene el estado de OpenClaw"""
    try:
        response = requests.get(f"{OPENCLAW_URL}/api/status", timeout=10)
        if response.status_code == 200:
            return response.json()
        return {"available": False, "error": "No disponible"}
    except Exception as e:
        return {"available": False, "error": str(e)}
