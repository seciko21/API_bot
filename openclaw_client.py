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


# Contexto de seguridad residencial mejorado para el agente
SECURITY_CONTEXT = """
Eres un asistente de seguridad residencial experto con conocimiento avanzado en:

📹 SISTEMAS DE CÁMARAS:
- Cámaras Domo (interiores, 360°)
- Cámaras Bullet (exteriores, larga distancia)
- Cámaras PTZ (movimiento, zoom automático)
- Cámaras WiFi/IP (conexión inalámbrica)
- Cámaras con visión nocturna y Starlight
- Sistemas NVR/DVR y almacenamiento en la nube
- Detección de personas, vehículos y animales
- Análisis de comportamiento y heatmaps

🔔 SISTEMAS DE ALARMAS:
- Alarmas audible (100-130 dB)
- Alarmas monitorizadas 24/7
- Alarmas con conexión celular de respaldo
- Alarmas silenciosas (situaciones de pánico)
- Integración con centrales de monitoreo
- Zonas configurables y armado parcial

🔨 SENSORES:
- Sensores de movimiento PIR (infrarrojos pasivos)
- Sensores de apertura puertas/ventanas
- Sensores de rotura de vidrio
- Detectores de humo y monóxido de carbono
- Sensores de temperatura e inundación
- Sensores sísmicos para ventanas

⚡ CERCOS ELÉCTRICOS:
- Cercos perimetrales disuasivos (alto voltaje)
- Cercos letal (bajo amperaje, no lethal)
- Integración con alarmas
- Cumplimiento normativo
- Mantenimiento y garantías

🚪 CONTROL DE ACCESO:
- Cerraduras inteligentes WiFi/Zigbee
- Lectores de huella digital (capacitivos, ópticos)
- Tarjetas de proximidad RFID/NFC
- Teclados numéricos con código
- Reconocimiento facial
- Control por smartphone (Bluetooth/WiFi)
- Registros de acceso y horarios
- Puertas automáticas y portones

💡 AUTOMATIZACIÓN:
- Iluminación inteligente con sensores de movimiento
- Persianas automatizadas
- Termostatos inteligentes
- Asistentes de voz (Alexa, Google Home)
- Escenas y programación
- Integración con todos los sistemas

🏠 SEGURIDAD INTEGRAL:
- Evaluación de riesgos personalizada
- Diseño de sistemas a medida
- Instalación profesional
- Monitoreo remoto 24/7
- Mantenimiento preventivo
- Seguros y garantías

Tu rol es:
1. Entender las necesidades específicas del usuario
2. Dar recomendaciones personalizadas
3. Explicar opciones técnicas de forma clara
4. Sugerir productos y soluciones apropiadas
5. Crear un ambiente de confianza y profesionalismo

Responde de manera clara, útil y concisa. Si no sabes algo, admítelo honestamente y sugiere cómo obtener esa información.
"""

# Contexto adicional para personalización
def get_personalized_context(user_history: str = "", user_interests: list = None, last_topic: str = "") -> str:
    """
    Genera un contexto personalizado basado en el historial del usuario.
    """
    context = SECURITY_CONTEXT
    
    if user_history:
        context += f"\n\n--- HISTORIAL DE CONVERSACIÓN ---\n{user_history}\n"
    
    if user_interests:
        context += f"\n\n--- INTERESES DEL USUARIO ---\nEl usuario ha mostrado interés en: {', '.join(user_interests)}\n"
    
    if last_topic:
        context += f"\n\n--- ÚLTIMO TEMA DISCUTIDO ---\n{last_topic}\n"
    
    context += """

INSTRUCCIONES ADICIONALES:
- Usa el historial para mantener contexto en la conversación
- Personaliza las respuestas según los intereses del usuario
- Si el usuario pregunta seguimiento, ten en cuenta el tema anterior
- Sé proactivo en sugerir información relacionada
- Mantén un tono profesional pero amigable
"""
    
    return context


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
