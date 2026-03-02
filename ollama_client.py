import requests
import json
import logging
import os
from typing import Optional, Dict, Any, Callable
from threading import Thread

logger = logging.getLogger(__name__)

# Configuración de Ollama desde variables de entorno
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://ollama:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")

# Configuración optimizada para menor latencia
OLLAMA_OPTIONS = {
    "temperature": 0.6,      # Menor temperatura = más determinista, más rápido
    "top_p": 0.85,          # Limita sampling
    "top_k": 40,            # Limita vocabulario
    "num_ctx": 2048,        # Contexto reducido (máx 4096)
    "num_predict": 256,     # Límite de tokens de respuesta (reducido)
    "repeat_penalty": 1.1,  # Evita repeticiones
}

# Contexto de seguridad residencial para el agente
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


def query_ollama(prompt: str, system_context: str = None, timeout: int = 60) -> Optional[str]:
    """
    Envía una consulta a Ollama y retorna la respuesta.
    
    Args:
        prompt: La pregunta o mensaje del usuario
        system_context: Contexto adicional del sistema (opcional)
        timeout: Timeout en segundos (reducido a 60s por defecto)
        
    Returns:
        La respuesta del modelo o None si hay error
    """
    try:
        url = f"{OLLAMA_HOST}/api/generate"
        
        # Construir el prompt con contexto
        full_prompt = prompt
        if system_context:
            full_prompt = f"{system_context}\n\nUsuario: {prompt}"
        
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": full_prompt,
            "stream": False,
            "options": OLLAMA_OPTIONS
        }
        
        response = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=timeout
        )
        
        if response.status_code == 200:
            result = response.json()
            return result.get("response", "").strip()
        else:
            logger.error(f"Error de Ollama: {response.status_code} - {response.text}")
            return None
            
    except requests.exceptions.Timeout:
        logger.error(f"Timeout al conectar con Ollama ({timeout}s)")
        return None
    except requests.exceptions.ConnectionError as e:
        logger.error(f"No se pudo conectar con Ollama: {e}")
        return None
    except Exception as e:
        logger.error(f"Error al procesar mensaje con Ollama: {e}")
        return None


def chat_with_ollama_streaming(messages: list, callback: Callable[[str], None], timeout: int = 60) -> bool:
    """
    Chat conversacional con streaming - envía fragmentos al callback.
    
    Args:
        messages: Lista de mensajes [{"role": "user/assistant/system", "content": "..."}]
        callback: Función que recibe cada fragmento de respuesta
        timeout: Timeout en segundos
        
    Returns:
        True si fue exitoso, False si hay error
    """
    try:
        url = f"{OLLAMA_HOST}/api/chat"
        
        payload = {
            "model": OLLAMA_MODEL,
            "messages": messages,
            "stream": True,
            "options": OLLAMA_OPTIONS
        }
        
        response = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            stream=True,
            timeout=timeout
        )
        
        if response.status_code == 200:
            full_response = ""
            for line in response.iter_lines():
                if line:
                    data = json.loads(line)
                    if "message" in data and "content" in data["message"]:
                        chunk = data["message"]["content"]
                        full_response += chunk
                        callback(chunk)
            return True
        else:
            logger.error(f"Error de Ollama: {response.status_code}")
            return False
            
    except Exception as e:
        logger.error(f"Error en chat streaming con Ollama: {e}")
        return False


def chat_with_ollama(messages: list, timeout: int = 60) -> Optional[str]:
    """
    Chat conversacional con Ollama usando el formato de mensajes.
    Optimizado para menor latencia.
    
    Args:
        messages: Lista de mensajes [{"role": "user/assistant/system", "content": "..."}]
        timeout: Timeout en segundos
        
    Returns:
        La respuesta del modelo o None si hay error
    """
    try:
        url = f"{OLLAMA_HOST}/api/chat"
        
        payload = {
            "model": OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
            "options": OLLAMA_OPTIONS
        }
        
        response = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=timeout
        )
        
        if response.status_code == 200:
            result = response.json()
            return result.get("message", {}).get("content", "").strip()
        else:
            logger.error(f"Error de Ollama: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"Error en chat con Ollama: {e}")
        return None


def is_ollama_available() -> bool:
    """Verifica si Ollama está disponible"""
    try:
        response = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
        return response.status_code == 200
    except requests.exceptions.ConnectionError as e:
        logger.warning(f"No se pudo conectar con Ollama: {e}")
        return False
    except requests.exceptions.Timeout as e:
        logger.warning(f"Timeout al verificar Ollama: {e}")
        return False
    except Exception as e:
        logger.warning(f"Error verificando disponibilidad de Ollama: {e}")
        return False


def get_ollama_status() -> Dict[str, Any]:
    """Obtiene el estado de Ollama"""
    try:
        response = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=10)
        if response.status_code == 200:
            models = response.json().get("models", [])
            return {
                "available": True,
                "models": [m.get("name") for m in models],
                "current_model": OLLAMA_MODEL
            }
        return {"available": False, "error": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"available": False, "error": str(e)}


def process_message_with_ollama(user_id: str, message: str, context: str = "") -> Optional[str]:
    """
    Procesa un mensaje del usuario usando Ollama.
    Mantiene compatibilidad con la interfaz anterior de openclaw_client.
    
    Args:
        user_id: ID del usuario
        message: Mensaje del usuario
        context: Contexto adicional
        
    Returns:
        Respuesta del agente o None si falla
    """
    # Construir mensajes para el chat
    messages = [
        {
            "role": "system",
            "content": SECURITY_CONTEXT
        }
    ]
    
    # Agregar contexto si existe
    if context:
        messages.append({
            "role": "system",
            "content": f"Contexto adicional: {context}"
        })
    
    # Agregar mensaje del usuario
    messages.append({
        "role": "user",
        "content": message
    })
    
    response = chat_with_ollama(messages)
    
    if response:
        return response
    
    # Si falla, intentar con query simple
    full_prompt = f"{SECURITY_CONTEXT}\n\n"
    if context:
        full_prompt += f"Contexto: {context}\n\n"
    full_prompt += f"Usuario pregunta: {message}"
    
    return query_ollama(full_prompt)
