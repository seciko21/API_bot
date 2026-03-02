import os
import asyncio
import logging
import json
import re
from datetime import datetime, timedelta
from collections import defaultdict
from telegram import Update, InlineKeyboardButton, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler, ConversationHandler
import requests
from ollama_client import chat_with_ollama, query_ollama, is_ollama_available, get_ollama_status, process_message_with_ollama

# Configuración de Telegram
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Configuración de Ollama
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")

# DeepSeek (opcional)
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

# Configurar logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================================
# SISTEMA DE MEMORIA E INTELIGENCIA DEL BOT
# ============================================

class UserMemory:
    """Sistema de memoria por usuario para mantener contexto"""
    
    def __init__(self, max_history: int = 10):
        self.max_history = max_history
        # Historial de conversaciones por usuario
        self.conversation_history: dict[str, list[dict]] = defaultdict(list)
        # Preferencias del usuario
        self.user_preferences: dict[str, dict] = defaultdict(dict)
        # Temas de interés por usuario
        self.user_interests: dict[str, list[str]] = defaultdict(list)
        # Contador de interacciones
        self.interaction_count: dict[str, int] = defaultdict(int)
        # Última vez que interactuó
        self.last_interaction: dict[str, datetime] = {}
    
    def add_message(self, user_id: str, role: str, content: str):
        """Agrega un mensaje al historial"""
        self.conversation_history[user_id].append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })
        # Mantener solo los últimos mensajes
        if len(self.conversation_history[user_id]) > self.max_history:
            self.conversation_history[user_id] = self.conversation_history[user_id][-self.max_history:]
        
        self.last_interaction[user_id] = datetime.now()
        self.interaction_count[user_id] += 1
    
    def get_context(self, user_id: str) -> str:
        """Obtiene el contexto de la conversación"""
        history = self.conversation_history[user_id]
        if not history:
            return ""
        
        context_parts = []
        for msg in history[-5:]:  # Últimos 5 mensajes
            role_emoji = "👤" if msg["role"] == "user" else "🤖"
            context_parts.append(f"{role_emoji} {msg['content'][:100]}")
        
        return " | ".join(context_parts)
    
    def get_preferences(self, user_id: str) -> dict:
        """Obtiene las preferencias del usuario"""
        return self.user_preferences.get(user_id, {})
    
    def set_preference(self, user_id: str, key: str, value: any):
        """Establece una preferencia"""
        self.user_preferences[user_id][key] = value
    
    def add_interest(self, user_id: str, topic: str):
        """Agrega un tema de interés"""
        if topic not in self.user_interests[user_id]:
            self.user_interests[user_id].append(topic)
    
    def get_interests(self, user_id: str) -> list[str]:
        """Obtiene los intereses del usuario"""
        return self.user_interests.get(user_id, [])
    
    def get_conversation_summary(self, user_id: str) -> str:
        """Resume la conversación para dar contexto a la IA"""
        prefs = self.get_preferences(user_id)
        interests = self.get_interests(user_id)
        count = self.interaction_count.get(user_id, 0)
        
        summary = f"Usuario ha tenido {count} interacciones."
        if interests:
            summary += f" Temas de interés: {', '.join(interests[-3:])}."
        if prefs.get('ultimo_tema'):
            summary += f" Último tema discutido: {prefs['ultimo_tema']}."
        
        return summary
    
    def get_followup_question(self, user_id: str, current_intent: str) -> str | None:
        """Genera preguntas de seguimiento basadas en el contexto"""
        last_topic = self.user_preferences[user_id].get('ultimo_tema', '')
        interests = self.get_interests(user_id)
        
        followups = {
            "camaras": [
                "¿Necesitas ayuda para elegir el tipo de cámara ideal para tu espacio?",
                "¿Sabías que puedes ver las cámaras desde tu celular en tiempo real?",
                "¿Quieres que te cotice un paquete completo de videovigilancia?"
            ],
            "alarmas": [
                "¿Tu alarma actual está conectada a una central de monitoreo?",
                "¿Quieres saber cómo silenciar una falsa alarma?",
                "¿Te interesa un sistema de alertas en tu teléfono?"
            ],
            "sensores": [
                "¿Qué tipo de sensores necesitas: movimiento, humo o temperatura?",
                "¿Los sensores serán para interior o exterior?",
                "¿Quieres integrarlos con tu sistema de alarmas existente?"
            ],
            "cerco": [
                "¿Para qué tipo de propiedad necesitas el cerco?",
                "¿Tienes una idea del perímetro que necesitas cubrir?",
                "¿Prefieres cerco con o sin concertina?"
            ],
            "acceso": [
                "¿Cuántas puertas necesitas controlar?",
                "¿Prefieres cerradura con huella, tarjeta o código?",
                "¿Necesitas registro de quién entra y sale?"
            ],
            "precios": [
                "¿Tienes un presupuesto en mente?",
                "¿Para qué tipo de propiedad necesitas? (casa, negocio, oficina)",
                "¿Cuántos equipos necesitas aproximadamente?"
            ],
            "compra": [
                "¿Ya tienes idea de qué marcas te interesan?",
                "¿Necesitas servicio de instalación o solo el equipo?",
                "¿En qué zona estás para calcular el tiempo de instalación?"
            ],
            "problema": [
                "¿Cuándo comenzó el problema?",
                "¿Hay algún mensaje de error en pantalla?",
                "¿Ya intentaste desconectar y reconectar el equipo?"
            ],
            "seguridad": [
                "¿Es para tu casa o negocio?",
                "¿Qué zona específica necesitas proteger?",
                "¿Ya tienes algún sistema de seguridad instalado?"
            ]
        }
        
        # Si hay un tema anterior, usar follow-up relacionado
        if last_topic and last_topic in followups:
            import random
            return random.choice(followups[last_topic])
        
        # Si hay intereses, usar el más reciente
        if interests and interests[-1] in followups:
            import random
            return random.choice(followups[interests[-1]])
        
        # Usar la intención actual
        if current_intent in followups:
            import random
            return random.choice(followups[current_intent])
        
        return None


class IntentAnalyzer:
    """Analizador de intenciones mejorado con Machine Learning básico"""
    
    # Categorías de intención con palabras clave mejoradas
    INTENT_PATTERNS = {
        # Saludos y cortesías
        "saludo": ["hola", "buenos", "buenas", "hey", "hi", "hello", "qué tal", "como estas", "buen día", "buenas noches", "buenas tardes", "buen dia", "saludos", "holi", "waza", "buenitos", "que hubo", "que onda", "holis"],
        "despedida": ["adios", "adiós", "bye", "hasta luego", "nos vemos", "me voy", "me tengo que ir", "me retiro", "hasta pronto", "nos pillamos", "luego", "me late"],
        "agradecimiento": ["gracias", "thank", "te lo agradezco", "muchas gracias", "mil gracias", "agradezco", "thanks", "te agradezco", "muy amable", "excelente", "genial", "te lo agradesco"],
        
        # Información general
        "seguridad": ["seguridad", "proteger", "proteger", "protegido", "seguro", "protección", "resguardar", "proteger mi", "alarmado", "blindar", "resguardar", "protección"],
        "camaras": ["cámara", "camara", "video", "vigilancia", "grabar", "recording", "ver cameras", "cctv", "nvr", "dvr", "camaras", "filmadora", "videovigilancia", "circuito cerrado", "cam", "camaritas"],
        "alarmas": ["alarma", "alertas", "alert", "sonar", "silenciar", "activar", "desactivar", "timbre", "avisador", "alertas", "panico", "alarma de robo"],
        "sensores": ["sensor", "detector", "movimiento", "pir", "humo", "gas", "temperatura", "inundación", "inundacion", "vibración", "vibracion", "detección", "magnético", "magnetico", "microfono"],
        "cerco": ["cerco", "eléctrico", "perímetro", "perimetral", "voltaje", "electrificado", "electrificado", "cerca electrica", "concertina", "cerca electrica"],
        "acceso": ["acceso", "entrada", "puerta", "cerradura", "huella", "tarjeta", "biométrico", "biometrico", "teclado", "codigo", "password", "control de acceso", "cerradura electronica", "raspberry", "rfid", "proximidad"],
        
        # Lugares a proteger
        "casa": ["casa", "hogar", "residencia", "vivienda", "departamento", "departamento", "cuarto", "recamara", "recámara", "dormitorio", "terraza", "patio", "jardín", "jardin", "entrada", "cochera", "frente", "trasero", "interior"],
        "negocio": ["negocio", "tienda", "oficina", "empresa", "local", "comercial", "bodega", "almacén", "almacen", "comercio", "punto de venta", "tiendita", "boutique", "restaurante"],
        "colegio": ["escuela", "colegio", "universidad", "colegio", "instituto", "academia", "escuelita", "aula", "kinder", "preescolar"],
        "fabrica": ["fabrica", "fábrica", "industria", "planta", "galpón", "galpon", "nave industrial", "taller", "manufactura"],
        
        # Consultas específicas
        "precios": ["precio", "costo", "cuanto", "cotización", "cotizacion", "presupuesto", "cuenta", "vale", "cuesta", "inversión", "inversion", "presupuesto", "cuánto cuesta", "cuanto sale", "invierto", "presupuestar", "montos", "tarifas"],
        "compra": ["comprar", "adquirir", "quiero", "necesito", "obtener", "contratar", "rentar", "alquilar", "donde comprar", "dónde comprar", "adquirir", "mandar", "orden", "pedir"],
        "marca": ["marca", "marcas", "fabricante", "proveedor", "vendedor", "distribuidor", "cual marca", "qué marca", "recomienda", "cuales", "cuales marcas", "que marcas", "hazca", "hikvision", "dahua", "axis"],
        "instalar": ["instalar", "instalación", "instalacion", "colocar", "poner", "montar", "setup", "configurar", "instalación", "armar", "implementar"],
        "mantenimiento": ["mantenimiento", "reparar", "reparación", "servicio", "manten", "revision", "revisión", "chequeo", "manten", "actualizar", "service"],
        "garantia": ["garantia", "garantía", "warranty", "seguro", "cobertura", "años de garantía", "meses de garantia", "tiempo de garantia"],
        
        # Problemas
        "problema": ["problema", "error", "no funciona", "no sirve", "falla", "fallando", "roto", "dañado", "averiado", "no sirve", "se dañó", "no enciende", "no conecta", "trastorno", "inconveniente"],
        "robo": ["robo", "asalto", "ladron", "ladrón", "intru", "intruso", "robar", "hurtar", "asaltaron", "entraron", "robado", "saqueo"],
        
        # Comparaciones
        "comparar": ["comparar", "comparación", "diferencia", "vs", "versus", "cual es mejor", "que es mejor", "区别", "distingue", "conviene más", "cual", "diferencias entre"],
        "recomendar": ["recomendar", "recomendación", "sugerir", "sugerencia", "sugiere", "aconsejar", "aconsejo", "me recomiendas", "que me recomiendas", "me sugiere"],
        
        # Consultas de IA
        "consulta_ia": ["qué opinas", "analiza", "consejo", "recomendación", "¿cómo podría", "¿qué me sugieres", "dime más", "explain", "why", "porque", "?", "que sabes sobre", "explícame", "cuéntame", "que me dices", "tu que recomiendas", "que me dices de", "tu opinion"],
        
        # Acciones
        "ayuda": ["ayuda", "help", "no entiendo", "no sé", "que hacer", "qué hacer", "como funciona", "que es", "qué es", "ayúdame", "como le hago", "instrucciones", "guía"],
        "emergencia": ["emergencia", "urgencia", "peligro", "ladrones", "robo", "intrus", "ayuda", "socorro", "accidente", "atracan", "me robaron", "asalto", "emergente"],
        "contacto": ["contacto", "teléfono", "telefono", "llamar", "hablar", "soporte", "atención", "atencion", "whatsapp", "ubicación", "ubicacion", "comunícame", "hablar con alguien", "comunicar", "email", "correo"],
        
        # Estado del sistema
        "estado": ["estado", "status", "cómo está", "como está", "funcionando", "conectado", "prendido", "encendido", "andando", "respondiendo", "online"],
        "configuracion": ["configurar", "configuración", "ajustar", "cambiar", "opciones", "config", "setear", "personalizar", "modificar", "parametros"],
    }
    
    @classmethod
    def analyze(cls, query: str) -> dict:
        """
        Analiza la consulta y devuelve la intención, entidades y sentimiento.
        Retorna: {"intent": str, "entities": list, "confidence": float, "sentiment": str}
        """
        query_lower = query.lower()
        
        # Detectar sentimiento
        sentiment = cls._analyze_sentiment(query_lower)
        
        # Detectar intenciones
        intents_found = []
        for intent, keywords in cls.INTENT_PATTERNS.items():
            matches = sum(1 for kw in keywords if kw in query_lower)
            if matches > 0:
                confidence = min(matches * 0.3, 1.0)
                intents_found.append((intent, confidence))
        
        if not intents_found:
            return {"intent": "desconocido", "entities": [], "confidence": 0.0, "sentiment": sentiment}
        
        # Ordenar por confianza
        intents_found.sort(key=lambda x: x[1], reverse=True)
        best_intent = intents_found[0]
        
        # Extraer entidades
        entities = cls._extract_entities(query_lower)
        
        return {
            "intent": best_intent[0],
            "entities": entities,
            "confidence": best_intent[1],
            "all_intents": intents_found[:3],
            "sentiment": sentiment
        }
    
    @classmethod
    def _analyze_sentiment(cls, query: str) -> str:
        """Analiza el sentimiento del mensaje"""
        positive_words = ["gracias", "perfecto", "excelente", "genial", "mejor", "amor", "feliz", "bien", "ok", "si", "sí", "perfecto", "awesome", "great", "me encanta", "fantástico"]
        negative_words = ["problema", "error", "falla", "roto", "no funciona", "pesimo", "terrible", "horrible", "peor", "enojado", "molesto", "ayuda", "urgente", "emergencia", "enojo", "frustrado"]
        urgent_words = ["urgente", "emergencia", "ahora", "inmediato", "ya", "peligro", "socorro", "ayuda", "rápido", "apurado"]
        
        # Detectar urgencia primero
        if any(word in query for word in urgent_words):
            return "urgente"
        
        positive_count = sum(1 for word in positive_words if word in query)
        negative_count = sum(1 for word in negative_words if word in query)
        
        if negative_count > positive_count:
            return "negativo"
        elif positive_count > negative_count:
            return "positivo"
        return "neutral"

    @classmethod
    def _extract_entities(cls, query: str) -> list[dict]:
        """Extrae entidades del mensaje"""
        entities = []
        
        # Detectar tipos de cámaras
        camera_types = ["domo", "bullet", "ptz", "wifi", "ip"]
        for cam in camera_types:
            if cam in query:
                entities.append({"type": "camera_type", "value": cam})
        
        # Detectar ubicaciones
        locations = ["entrada", "garaje", "jardin", "jardín", "patio", "trasero", "frontal", "interior", "exterior"]
        for loc in locations:
            if loc in query:
                entities.append({"type": "location", "value": loc})
        
        return entities

# Instancias globales
user_memory = UserMemory(max_history=15)

# ============================================
# SISTEMA DE BÚSQUEDA WEB INTELIGENTE
# ============================================

import urllib.parse
import random

class WebSearcher:
    """
    Sistema de búsqueda web para obtener información actualizada
    sobre seguridad residencial.
    """
    
    # URLs de búsqueda (usando DuckDuckGo como alternativa libre)
    SEARCH_URL = "https://html.duckduckgo.com/html/?q="
    
    # Categorías de búsqueda predefinidas
    SEARCH_TOPICS = {
        "camaras": [
            "mejores cámaras de seguridad 2024 2025",
            "cámaras IP WiFi mejores marcas",
            "cámaras visión nocturna starlight",
            "sistema NVR DVR diferencias"
        ],
        "alarmas": [
            "mejores alarmas residenciales 2024",
            "alarmas monitoreadas vs autónomas",
            "alarma silenciosa emergencias"
        ],
        "sensores": [
            "tipos sensores movimiento seguridad",
            "sensores humo gas normativas",
            "sensores apertura puertas window"
        ],
        "cerco": [
            "cerco eléctrico residencial normativas",
            "cerco eléctrico lethal vs disuasivo",
            "instalación cerco perimetral"
        ],
        "acceso": [
            "mejores cerraduras inteligentes 2024",
            "lector huella digital seguridad",
            "control acceso reconocimiento facial"
        ],
        "general": [
            "sistemas seguridad residencial mejores prácticas",
            "consejos seguridad hogar prevención",
            "evaluación riesgos seguridad casa"
        ]
    }
    
    @classmethod
    def search(cls, query: str, category: str = "general") -> str:
        """
        Realiza una búsqueda web y devuelve resultados relevantes.
        """
        try:
            # Construir query de búsqueda
            search_query = f"{query} seguridad residencial"
            encoded_query = urllib.parse.quote(search_query)
            url = f"{cls.SEARCH_URL}{encoded_query}"
            
            # Realizar búsqueda
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                # Extraer títulos y snippets (versión simple)
                return cls._parse_results(response.text)
            else:
                return cls.get_offline_info(query, category)
                
        except Exception as e:
            logger.error(f"Error en búsqueda web: {e}")
            return cls.get_offline_info(query, category)
    
    @classmethod
    def _parse_results(cls, html: str) -> str:
        """
        Parsea resultados básicos del HTML.
        """
        # Extraer resultados de búsqueda (versión simplificada)
        import re
        
        # Buscar títulos
        titles = re.findall(r'<a class="result__a"[^>]*>([^<]+)</a>', html)
        
        if titles:
            return " | ".join(titles[:3])
        return ""
    
    @classmethod
    def get_offline_info(cls, query: str, category: str) -> str:
        """
        Proporciona información offline cuando no hay internet.
        """
        # Base de conocimientos actualizada y expandida
        knowledge_base = {
            "camaras": """
📹 *Cámaras de Seguridad - Guía Completa*

*Tipos de Cámaras:*
• Domo: Para interiores, difícil de ver dirección
• Bullet: Para exteriores, larga distancia
• PTZ: Movimiento automático, zoom hasta 30x
• WiFi: Sin cables, fácil instalación
• POE: Alimentación por cable de red
• Oculta: Espía, muy discreta

*Marcas TOP:*
• Hikvision - Líder mundial, $2,000-15,000 MXN
• Dahua - Alternativa robusta, $1,800-12,000 MXN
• Reolink - Mejor DIY, $1,500-8,000 MXN
• UniFi - Redes, $3,000-20,000 MXN
• EZVIZ - Económico, $800-5,000 MXN

*Precios instalación:*
• Básica 4 cámaras: $8,000-15,000 MXN
• Intermedia 8 cámaras: $15,000-30,000 MXN
• Premium 16+ cámaras: $30,000-60,000 MXN

*Resoluciones:*
• 1080p (Full HD) - Estándar actual
• 4K (Ultra HD) - Más detalle, más almacenamiento
• 5MP - Balance ideal precio-calidad

*Accesorios:*
• NVR: $3,000-15,000 MXN
• HDD 2TB: $1,500-2,500 MXN
• Cable cat6: $15-30 MXN/m
            """,
            
            "alarmas": """
🔔 *Sistemas de Alarmas - Guía Completa*

*Tipos de Alarmas:*
• Audible: Suena sirena fuerte (100-130 dB)
• Monitorizada: Notifica a central 24/7
• GSM: Usa red celular (no necesita línea)
• IP/WiFi: Notificaciones a celular
• Inteligente: Integración con domótica

*Marcas TOP:*
• ADT - Líder mundial, $500-2,000 MXN/mes
• Ring - Fácil uso, $2,000-8,000 MXN
• Ajax - Premium europeo, $5,000-15,000 MXN
• Honeywell - Robusto, $3,000-12,000 MXN
• DSC - Confiable, $2,500-10,000 MXN
• Paradox - Popular MX, $3,000-8,000 MXN

*Precios sistema completo:*
• Básico (4-6 zonas): $8,000-15,000 MXN
• Intermedio (8-16 zonas): $15,000-30,000 MXN
• Premium (16+ zonas): $30,000-60,000 MXN
• Monitoreo mensual: $300-1,500 MXN

*Componentes:*
• Panel principal: $3,000-10,000 MXN
• Sensor movimiento: $300-800 MXN
• Sensor puerta: $150-400 MXN
• Sirena: $500-1,500 MXN
• Teclado: $500-1,500 MXN
            """,
            
            "sensores": """
🔨 *Sensores de Seguridad - Catálogo Completo*

*Tipos de Sensores:*
• PIR: Detecta movimiento corporal
• Magnetismo: Apertura puertas/ventanas
• Rotura vidrio: Detecta cristal roto
• Humo: Detecta incendio
• Gas: Metano, GLP, natural
• Temperatura: Incendios latentes
• Inundación: Agua estancada
• Vibración: Puertas/ventanas
• Ultrasónico: Movimiento preciso

*Marcas TOP:*
• Bosch - Alta confiabilidad
• Honeywell - Variedad total
• Ajax - Diseño premium
• Paradox - Precio-valor
• Yale - Económico confiable
• Esser - Profesional

*Precios:*
• PIR: $300-1,500 MXN
• Magnetismo: $150-500 MXN
• Humo: $200-800 MXN
• Gas: $400-1,500 MXN
• Temperatura: $250-600 MXN
• Inundación: $300-700 MXN
            """,
            
            "cerco": """
⚡ *Cercos Eléctricos - Guía Técnica*

*Tipos:*
• Disuasivo (9-12KV): Solo molestia temporal
• Letal (20-30KV): Peligroso, uso especial
• Hybrid: Combina ambas tecnologías
• Concertina: Alambre cortante

*Componentes:*
• Energizador: $2,000-15,000 MXN
• Hilos: $50-200 MXN/rollo
• Aisladores: $5-20 MXN c/u
• Sirena: $500-2,000 MXN
• Carteles: $50-100 MXN
• Batería: $500-1,500 MXN

*Marcas TOP:*
• JNG - Líder mundial
• Crown - Confiable
• Zico - Popular
• Electrificadora - Nacional

*Precios instalación:*
• Residencial básico: $15,000-30,000 MXN
• Residencial completo: $30,000-60,000 MXN
• Comercial: $60,000-150,000 MXN
• Industrial: $150,000+ MXN

*Normativas:*
• Altura mínima: 2 metros
• Distancia hilos: 20cm
• Instalación profesional
• Señalización obligatoria
            """,
            
            "acceso": """
🚪 *Control de Acceso - Opciones Modernas*

*Tipos de Cerraduras:*
• Wifi: Control remoto anywhere
• Bluetooth: Cercania
• RFID: Tarjetas/tags
• Biométrico: Huella/rostro
• Código: Teclado numérico
• Combinado: Múltiples métodos

*Tipos Biométricos:*
• Huella电容: Preciso, rápido
• Huella óptico: Más económico
• Rostro: Sin contacto
• Iris: Máxima seguridad
• Vena: Muy seguro

*Marcas TOP:*
• August - Mejor integración
• Schlage - Tradición calidad
• Yale - Variedad
• Samsung - Diseño premium
• Aqara - Precio-valor
• Kwikset - Económico

*Precios:*
• Cerradura básica: $1,500-3,000 MXN
• Cerradura WiFi: $3,000-8,000 MXN
• Biométrico: $4,000-15,000 MXN
• Sistema completo: $10,000-50,000 MXN
            """,
            
            "negocio": """
🏪 *Seguridad para Negocios*

*Sistema recomendado:*
• Cámaras en área de ventas
• Sensor movimiento zonas clave
• Alarma perimetral
• Control de acceso empleados
• Cerco perimetral si es local

*Precios negocio pequeño:*
• Kit básico: $20,000-40,000 MXN
• Kit intermedio: $40,000-80,000 MXN
• Kit premium: $80,000-200,000 MXN

*Consideraciones:*
• Seguro contra robo
• Monitoreo 24/7 recomendado
• Respaldo de batería
• Acceso remoto
• Integración con policía
            """,
            
            "casa": """
🏠 *Seguridad para Casa*

*Capas de protección:*
1. Perímetro: Cerco, bardas, rejas
2. Exterior: Cámaras, sensores movimiento
3. Interior: Sensores, alarmas
4. Puertas: Cerraduras inteligentes

*Sistema casa típica:*
• 4-8 cámaras: $10,000-30,000 MXN
• Alarma 8 zonas: $10,000-25,000 MXN
• Sensores adicionales: $3,000-8,000 MXN
• Cerraduras inteligentes: $4,000-12,000 MXN
• Instalación: $5,000-15,000 MXN

*Inversión total:*
• Básico: $25,000-50,000 MXN
• Intermedio: $50,000-100,000 MXN
• Premium: $100,000-300,000 MXN
            """,
            
            "marca": """
🏷️ *Marcas Recomendadas por Categoría*

*Cámaras:*
• Hikvision - Mejor relación precio-calidad
• Dahua - Excelente alternativa
• Reolink - Mejor para particulares

*Alarmas:*
• Ajax - Tecnología premium
• Ring - Fácil uso
• Paradox - Mejor precio-valor

*Cerraduras:*
• August - Integración smart home
• Schlage - Durabilidad
• Yale - Variedad de opciones

*Sensores:*
• Bosch - Confiabilidad
• Honeywell - Variedad
• Ajax - Diseño
            """,
            
            "precios": """
💰 *Guía de Precios - Seguridad Residencial*

*Sistemas completos:*
• Básico: $25,000-50,000 MXN
• Intermedio: $50,000-100,000 MXN
• Premium: $100,000-300,000 MXN
• Empresarial: $200,000-1,000,000 MXN

*Componentes individuales:*
• Cámara IP: $1,500-15,000 MXN
• Sensor movimiento: $300-1,500 MXN
• Panel alarma: $3,000-15,000 MXN
• Cerradura inteligente: $2,000-15,000 MXN
• Cerco eléctrico metro: $200-500 MXN

*Servicios:*
• Instalación: $5,000-30,000 MXN
• Monitoreo mensual: $300-1,500 MXN
• Mantenimiento anual: $2,000-10,000 MXN

*Nota:* Precios aproximados, varían por región y proveedor.
            """,
            
            "comparar": """
⚖️ *Comparación de Sistemas*

*Cámaras WiFi vs Cableadas:*
• WiFi: Fácil instalación, menor costo
• Cableadas: Más estables, mayor distancia

*Alarma monitoreada vs Autónoma:*
• Monitoreada: Notifica a central 24/7
• Autónoma: Solo notifica a ti

*Cerradura código vs Biométrico:*
• Código: Económico, fácil cambiar clave
• Biométrico: Más seguro, sin llaves

*Domo vs Bullet:*
• Domo: Estética, difícil manipular
• Bullet: Mejor para larga distancia
            """,
            
            "problema": """
🔧 *Solución de Problemas Comunes*

*Cámara no conecta:*
• Verificar energía
• Revisar conexión WiFi
• Confirmar IP correcta
• Resetear cámara

*Alarma falsa:*
• Ajustar sensibilidad
• Verificar baterías
• Limpiar sensores
• Revisar mascotas

*Cerradura no abre:*
• Cambiar baterías
• Verificar conexión
• Limpiar sensor huella
• Usar llave mecánica

*Cerco no activa:*
• Verificar energía
• Revisar conexiones
• Probar batería backup
• Revisar sirena

*¿Problema específico?* Cuéntame más detalles.
            """,
            
            "robo": """
🚨 *Prevención de Robos*

*Tips esenciales:*
• No publikar ausencias en redes
• Usar timers en luces
• Mantener jardín cortado
• No ocultar llaves afuera
• Conocer vecinos

*Tecnología preventiva:*
• Cámaras visibles disuaden
• Alarmas sonar inmediatamente
• Luces con movimiento
• Cerco perimetral

*Si ocurre robo:*
• No confrontar
• Llamar 911
• Preservar evidencia
• Documentar daños
• Contactar seguro
• Denunciar
            """,
            
            "general": """
🏠 *Seguridad Residencial Integral*

*Capas de protección:*
1. Perímetro - Cercos, bardas, rejas
2. Exterior - Cámaras, sensores
3. Interior - Alarmas, sensores
4. Personal - Cerraduras, control

*Componentes esenciales:*
• Sistema de cámaras
• Alarma perimetral
• Sensores de movimiento
• Control de acceso
• Iluminación inteligente

*Inversión recomendada:*
• Básico: $25,000-50,000 MXN
• Intermedio: $50,000-100,000 MXN
• Premium: $100,000-300,000 MXN

*Mejores prácticas:*
• Integración de sistemas
• Monitoreo profesional
• Mantenimiento regular
• Respaldo de batería
• Actualización periódica

*¿Necesitas más información?* Pregúntame sobre un tema específico.
            """
        }
        
        # Buscar en categoría específica o general
        if category in knowledge_base:
            return knowledge_base[category]
        
        # Buscar por palabras clave en query
        query_lower = query.lower()
        for key in knowledge_base:
            if key in query_lower:
                return knowledge_base[key]
        
        return knowledge_base["general"]
    
    @classmethod
    def get_search_tips(cls, topic: str) -> list:
        """Obtiene sugerencias de búsqueda para un tema"""
        return cls.SEARCH_TOPICS.get(topic, cls.SEARCH_TOPICS["general"])


# Función para buscar información
def search_security_info(query: str, use_web: bool = True, category: str = "general") -> str:
    """
    Busca información de seguridad, ya sea online u offline.
    """
    if use_web:
        try:
            # Intentar búsqueda web
            result = WebSearcher.search(query, category)
            if result:
                return f"🔍 *Resultados de búsqueda:*\n{result}\n\n"
        except:
            pass
    
    # Fallback a información offline
    return WebSearcher.get_offline_info(query, category)

# ============================================
# TEMA GEMINI DARK - ESTILO VISUAL
# ============================================

# Colores del tema Gemini Dark
THEME = {
    "primary": "#1E1E1E",        # Fondo principal oscuro
    "secondary": "#2D2D2D",      # Fondo secundario
    "accent": "#8AB4F8",        # Azul brillante tipo Gemini
    "accent_secondary": "#81C995",  # Verde success
    "text_primary": "#FFFFFF",   # Texto principal
    "text_secondary": "#B3B3B3",  # Texto secundario
    "border": "#3D3D3D",        # Bordes
    "error": "#F28B82",         # Rojo error
    "warning": "#FFD33D",       # Amarillo warning
}

def format_header(title: str) -> str:
    """Formatea un encabezado con estilo Gemini Dark"""
    return f"🎯 *{title}*"

def format_section(title: str, content: str) -> str:
    """Formatea una sección con estilo"""
    return f"▸ *{title}*: {content}"

def format_button(text: str) -> str:
    """Formatea texto de botón"""
    return f"[{text}]"

# Botones de control del sistema
SYSTEM_CONTROL_KEYBOARD = ReplyKeyboardMarkup([
    [KeyboardButton("🔴 Estado del Sistema"), KeyboardButton("🟢 Reiniciar Servicios")],
    [KeyboardButton("📊 Métricas"), KeyboardButton("⚙️ Configuración")],
    [KeyboardButton("📋 Menú Principal")]
], resize_keyboard=True, one_time_keyboard=False)

# Botones principales - Menú optimizado con más estilo
MAIN_MENU_KEYBOARD = ReplyKeyboardMarkup([
    [KeyboardButton("🏠 Inicio"), KeyboardButton("🛡️ Seguridad"), KeyboardButton("🔐 Protección")],
    [KeyboardButton("📹 Cámaras"), KeyboardButton("🔔 Alarmas"), KeyboardButton("👁️ Vigilancia")],
    [KeyboardButton("🌡️ Sensores"), KeyboardButton("⚡ Cercos"), KeyboardButton("🚨 Alertas")],
    [KeyboardButton("🚪 Acceso"), KeyboardButton("💡 Tips"), KeyboardButton("⚙️ Ajustes")],
    [KeyboardButton("📞 Contacto"), KeyboardButton("❓ Ayuda"), KeyboardButton("🎯 Centro")]
], resize_keyboard=True, one_time_keyboard=False)

# Botones inline para respuestas interactivas - Optimizado con más estilo
def get_inline_keyboard(buttons: list) -> list:
    """Genera un keyboard inline de botones con diseño mejorado"""
    keyboard = []
    row = []
    for i, (text, callback_data) in enumerate(buttons):
        # Agregar emoji según el tipo de botón
        emoji = ""
        if "seguridad" in callback_data or "security" in callback_data:
            emoji = "🛡️"
        elif "camera" in callback_data or "camar" in callback_data:
            emoji = "📹"
        elif "alarm" in callback_data:
            emoji = "🔔"
        elif "fence" in callback_data or "cerco" in callback_data:
            emoji = "⚡"
        elif "access" in callback_data or "acceso" in callback_data:
            emoji = "🚪"
        elif "tips" in callback_data:
            emoji = "💡"
        elif "contact" in callback_data:
            emoji = "📞"
        elif "help" in callback_data or "ayuda" in callback_data:
            emoji = "❓"
        elif "status" in callback_data:
            emoji = "🔴"
        elif "restart" in callback_data or "reiniciar" in callback_data:
            emoji = "🔄"
        elif "metrics" in callback_data or "métricas" in callback_data:
            emoji = "📊"
        elif "settings" in callback_data or "config" in callback_data:
            emoji = "⚙️"
        else:
            emoji = "▪️"
        
        styled_text = f"{emoji} {text}"
        row.append(InlineKeyboardButton(styled_text, callback_data=callback_data))
        if (i + 1) % 2 == 0:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    return keyboard

# Menú de control del sistema - Mejorado
SYSTEM_MENU_INLINE = [
    ("🔴 Estado del Sistema", "system_status"),
    ("🔄 Reiniciar Servicios", "system_restart"),
    ("📊 Métricas", "system_metrics"),
    ("⚙️ Configuración", "system_settings"),
    ("📈 Estadísticas", "system_stats"),
    ("🔔 Notificaciones", "system_notifications"),
]

# Menú de cámaras - Mejorado con más opciones
CAMERA_MENU_INLINE = [
    ("📹 Ver Cámaras en Vivo", "camera_view"),
    ("🔴 Iniciar Grabación", "camera_record"),
    ("📸 Captura de Imagen", "camera_capture"),
    ("🎬 Reproducir Grabaciones", "camera_playback"),
    ("⚙️ Configurar Cámaras", "camera_config"),
    ("🕐 Programar Grabación", "camera_schedule"),
]

# Menú de alarmas - Mejorado
ALARM_MENU_INLINE = [
    ("🔔 Activar Alarma", "alarm_activate"),
    ("🔕 Desactivar Alarma", "alarm_deactivate"),
    ("⏰ Programar Horarios", "alarm_schedule"),
    ("📋 Ver Historial", "alarm_history"),
    ("🔇 Modo Silencioso", "alarm_silent"),
    ("🚨 Simular Alarma", "alarm_test"),
]

# Menú de sensores - Nuevo
SENSORS_MENU_INLINE = [
    ("🌡️ Temperatura", "sensor_temp"),
    ("💧 Humedad", "sensor_humidity"),
    ("🔥 Sensores de Fuego", "sensor_fire"),
    ("⛽ Sensores de Gas", "sensor_gas"),
    ("🚪 Sensores de Puerta", "sensor_door"),
    ("👁️ Detección de Movimiento", "sensor_motion"),
]

# Menú de control de acceso - Mejorado
ACCESS_MENU_INLINE = [
    ("🚪 Abrir Puerta", "access_unlock"),
    ("🔐 Cerrar Puerta", "access_lock"),
    ("👤 Registrar Usuario", "access_add_user"),
    ("❌ Eliminar Usuario", "access_remove_user"),
    ("📋 Ver Registros", "access_logs"),
    ("🔑 Generar Código", "access_code"),
]

# Menú de cercos eléctricos - Nuevo
FENCE_MENU_INLINE = [
    ("⚡ Activar Cerco", "fence_activate"),
    ("💤 Desactivar Cerco", "fence_deactivate"),
    ("📊 Ver Voltaje", "fence_voltage"),
    ("🔧 Configurar Cerco", "fence_config"),
    ("⚠️ Ver Alarmas", "fence_alarms"),
]

# ============================================
# FUNCIONES DE OLLAMA AI
# ============================================

def get_ollama_response(user_message: str, context: str = "") -> str:
    """Obtiene una respuesta de Ollama AI"""
    try:
        url = f"{OLLAMA_HOST}/api/chat"
        
        system_prompt = f"""Eres un asistente de seguridad residencial experto. 
Ayudas a los usuarios con información sobre sistemas de seguridad, cámaras, alarmas, sensores, cercos eléctricos, control de acceso y consejos de seguridad para el hogar.

Contexto de seguridad residencial:
{context}

Responde de manera clara, útil y concisa. Si no sabes algo, admítelo honestamente."""
        
        data = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            "stream": False
        }
        
        response = requests.post(url, json=data, timeout=60)
        
        if response.status_code == 200:
            result = response.json()
            return result['message']['content']
        else:
            logger.error(f"Error de Ollama: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"Error al conectar con Ollama: {e}")
        return None

def is_ai_query(query: str) -> bool:
    """Determina si la consulta requiere IA"""
    ai_keywords = [
        "qué opinas", "analiza", "consejo", "recomendación", 
        "¿cómo podría", "¿qué me sugieres", "dime más", 
        "explain", "why", "porque", "porque", "?"
    ]
    return any(keyword in query.lower() for keyword in ai_keywords)

# ============================================
# FUNCIONES DE COMANDOS
# ============================================

async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja el comando /start con estilo Gemini Dark"""
    try:
        user_name = update.effective_user.first_name
        
        # Mensaje de bienvenida con estilo Gemini Dark
        openclaw_status = "🟢 Disponible" if is_ollama_available() else "🔴 No disponible"
        ai_status = "🟢 Activa" if OLLAMA_HOST else "⚪ No configurada"
        
        welcome_text = (
            f"🌙 *Bienvenido a tu Asistente de Seguridad*\n\n"
            f"¡Hola {user_name}! 👋\n\n"
            f"▸ *Estado del Sistema*: 🟢 Activo\n"
            f"▸ *Conexión OpenClaw*: {openclaw_status}\n"
            f"▸ *IA Ollama*: {ai_status}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"*¿Qué puedo hacer por ti?*\n\n"
            f"▸ 🔒 Sistemas de seguridad integrales\n"
            f"▸ 📹 Cámaras de vigilancia en tiempo real\n"
            f"▸ 🔔 Alarmas y sensores inteligentes\n"
            f"▸ ⚡ Cercos eléctricos perimetrales\n"
            f"▸ 🚪 Control de acceso biometrico\n"
            f"▸ 💡 Automatización del hogar\n"
            f"▸ 🤖 Consultas de IA avanzadas\n\n"
            f"*Selecciona una opción del menú o simplemente escribe tu pregunta.*"
        )
        
        # Usar el nuevo teclado principal
        await update.message.reply_text(
            welcome_text,
            parse_mode='Markdown',
            reply_markup=MAIN_MENU_KEYBOARD
        )
        
        # Enviar botones inline mejorados para acceso rápido
        inline_keyboard = get_inline_keyboard([
            ("🏠 Panel Principal", "menu_main"),
            ("🛡️ Seguridad Integral", "menu_security"),
            ("📹 Cámaras de Vigilancia", "menu_cameras"),
            ("🔔 Sistema de Alarmas", "menu_alarms"),
            ("⚡ Cerco Eléctrico", "menu_fence"),
            ("🚪 Control de Acceso", "menu_access"),
            ("🌡️ Sensores", "menu_sensors"),
            ("💡 Tips de Seguridad", "menu_tips"),
            ("📞 Contacto y Soporte", "menu_contact"),
            ("❓ Centro de Ayuda", "menu_help"),
            ("⚙️ Configuración", "menu_settings"),
            ("🎯 Estado General", "menu_status"),
        ])
        
        from telegram import InlineKeyboardMarkup
        await update.message.reply_text(
            "*Acceso rápido:*",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(inline_keyboard)
        )
        
    except Exception as e:
        logger.error(f"Error en handle_start: {e}")
        await update.message.reply_text("Hubo un error. Por favor, intenta de nuevo.")

async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja el comando /help"""
    help_text = (
        "📋 *Ayuda del Bot de Seguridad*\n\n"
        "*Controlado por OpenClaw AI*\n\n"
        "*Comandos disponibles:*\n"
        "/start - Iniciar el bot\n"
        "/help - Mostrar esta ayuda\n"
        "/contacto - Información de contacto\n"
        "/tips - Consejos de seguridad\n"
        "/emergencia - Qué hacer en emergencias\n"
        "/ai - Estado de IA\n"
        "/openclaw - Estado de OpenClaw\n"
        "/agent - Consultar al agente\n"
        "/send - Enviar mensaje\n\n"
        "*¡Simplemente escribe tu pregunta!*\n"
        "El agente de IA te responderá sobre cualquier tema de seguridad.\n\n"
        "¿Tienes alguna duda? ¡Escríbeme!"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def handle_contacto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja el comando /contacto"""
    contact_text = (
        "📞 *Información de Contacto*\n\n"
        "*Servicio técnico 24/7:*\n"
        "📱 Tel: +52 55 1234 5678\n"
        "📧 Email: soporte@seguridadresidencial.com\n\n"
        "*Ventas:*\n"
        "📱 Tel: +52 55 8765 4321\n"
        "📧 Email: ventas@seguridadresidencial.com\n\n"
        "*Dirección:*\n"
        "📍 Av. Principal #123, Ciudad\n\n"
        "¿Necesitas asistencia inmediata? Escribe /emergencia"
    )
    await update.message.reply_text(contact_text, parse_mode='Markdown')

async def handle_tips(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja el comando /tips - Consejos de seguridad"""
    tips_text = (
        "💡 *Consejos de Seguridad*\n\n"
        "🔒 *Protección básica:*\n"
        "• Instala cerraduras de alta seguridad\n"
        "• Usa Cerrojo en puertas principales\n"
        "• No compartas claves con terceros\n\n"
        "📹 *Cámaras:*\n"
        "• Instala en puntos de entrada\n"
        "• Usa cámaras con visión nocturna\n"
        "• Configura notificaciones en tiempo real\n\n"
        "💡 *Iluminación:*\n"
        "• Instala sensores de movimiento\n"
        "• Ilumina áreas oscuras\n"
        "• Usa luces con temporizador\n\n"
        "🔔 *Alarmas:*\n"
        "• Activa siempre al salir\n"
        "• Mantén los sensores funcionando\n"
        "• Revisa las baterías regularmente\n\n"
        "¿Quieres más información sobre algún tema específico?"
    )
    await update.message.reply_text(tips_text, parse_mode='Markdown')

async def handle_emergencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja el comando /emergencia"""
    emergencia_text = (
        "🚨 *Guía de Emergencias*\n\n"
        "*Si estás en peligro inmediato:*\n"
        "📞 911 - Servicios de emergencia\n\n"
        "*Pasos a seguir:*\n"
        "1. Mantén la calma\n"
        "2. Si es seguro, llama al 911\n"
        "3. No confrontes intrusos\n"
        "4. Dirígete a un lugar seguro\n"
        "5. Activa tu alarma si es seguro\n\n"
        "* después de una emergencia:*\n"
        "• Preserva evidencia\n"
        "• Documenta daños\n"
        "• Contacta tu compañía de seguros\n"
        "• Llama al servicio técnico\n\n"
        "¿Necesitas ayuda inmediata? Escribe /contacto"
    )
    await update.message.reply_text(emergencia_text, parse_mode='Markdown')

async def handle_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja el comando /ai - Muestra el estado de Ollama"""
    try:
        # Verificar si Ollama está disponible
        import requests
        ollama_available = False
        try:
            response = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
            ollama_available = response.status_code == 200
        except:
            pass
        
        if ollama_available:
            ai_status = (
                f"🤖 *Ollama AI - Activado*\n\n"
                f"Modelo: `{OLLAMA_MODEL}`\n"
                f"Host: {OLLAMA_HOST}\n\n"
                "La IA está disponible para responder preguntas más complejas.\n\n"
                "Puedes hacer preguntas como:\n"
                "• ¿Qué opinas sobre este sistema de seguridad?\n"
                "• ¿Qué me recomiendas para mi casa?\n"
                "• Analiza las opciones de cámaras\n\n"
                "La IA te ayudará con recomendaciones personalizadas."
            )
        else:
            ai_status = (
                "🤖 *Ollama AI - No disponible*\n\n"
                "El servicio de Ollama no está activo.\n"
                "Inicia los contenedores con:\n"
                "`docker-compose up --build`\n\n"
                "Configura las variables OLLAMA_HOST y OLLAMA_MODEL\n"
                "en tu archivo .env"
            )
    except Exception as e:
        ai_status = (
            f"🤖 *Error al verificar Ollama*\n\n"
            f"Error: {str(e)}"
        )
    await update.message.reply_text(ai_status, parse_mode='Markdown')

async def handle_openclaw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja el comando /openclaw - Muestra el estado de OpenClaw"""
    available = is_ollama_available()
    
    if available:
        oc_status = (
            "🔗 *OpenClaw - Conectado*\n\n"
            "OpenClaw está activo y puedes:\n"
            "• Enviar mensajes a otros canales\n"
            "• Consultar al agente de IA\n\n"
            "*Comandos disponibles:*\n"
            "/send <número> <mensaje> - Enviar mensaje\n"
            "/agent <pregunta> - Consultar al agente\n\n"
            "*Canales soportados:*\n"
            "WhatsApp, Telegram, Slack, Discord, Signal, Teams"
        )
    else:
        oc_status = (
            "🔗 *OpenClaw - No disponible*\n\n"
            "El servicio de OpenClaw no está activo.\n"
            "Inicia los contenedores con:\n"
            "`docker-compose up --build`"
        )
    await update.message.reply_text(oc_status, parse_mode='Markdown')

async def handle_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja el comando /send - Envía mensaje vía OpenClaw"""
    try:
        args = context.args
        if len(args) < 2:
            await update.message.reply_text(
                "Uso: /send <número> <mensaje>\n"
                "Ejemplo: /send +1234567890 Hola mundo",
                parse_mode='Markdown'
            )
            return
        
        to_number = args[0]
        message = " ".join(args[1:])
        
        await update.message.reply_text("📤 Enviando mensaje...", parse_mode='Markdown')
        
        success = send_via_openclaw(to_number, message)
        
        if success:
            await update.message.reply_text(
                f"✅ Mensaje enviado a {to_number}",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "❌ Error al enviar mensaje. Verifica que OpenClaw esté activo.",
                parse_mode='Markdown'
            )
    except Exception as e:
        logger.error(f"Error en /send: {e}")
        await update.message.reply_text(
            f"Error: {str(e)}",
            parse_mode='Markdown'
        )

async def handle_agent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja el comando /agent - Consulta al agente de OpenClaw"""
    try:
        if not context.args:
            await update.message.reply_text(
                "Uso: /agent <pregunta>\n"
                "Ejemplo: /agent ¿Cuáles son los mejores sistemas de seguridad?",
                parse_mode='Markdown'
            )
            return
        
        query = " ".join(context.args)
        
        await update.message.reply_text("🤔 Consultando al agente...", parse_mode='Markdown')
        
        response = query_agent(query)
        
        if response:
            await update.message.reply_text(
                f"🧠 *Respuesta del agente:*\n\n{response}",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "❌ Error al consultar el agente. Verifica que OpenClaw esté activo.",
                parse_mode='Markdown'
            )
    except Exception as e:
        logger.error(f"Error en /agent: {e}")
        await update.message.reply_text(
            f"Error: {str(e)}",
            parse_mode='Markdown'
        )

# ============================================
# FUNCIONES DE MENSAJES
# ============================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Procesa los mensajes recibidos con inteligencia mejorada.
    Usa análisis de intenciones, memoria de usuario y contexto.
    """
    try:
        if not update.message or not update.message.text:
            return
        
        user_message = update.message.text
        query = user_message.lower()
        user_id = str(update.effective_user.id)
        user_name = update.effective_user.first_name
        
        logger.info(f"Consulta recibida de {user_name}: {query}")
        
        # ============================================
        # 1. ANALIZAR INTENCIÓN DEL USUARIO
        # ============================================
        intent_result = IntentAnalyzer.analyze(user_message)
        intent = intent_result["intent"]
        confidence = intent_result["confidence"]
        sentiment = intent_result.get("sentiment", "neutral")
        
        logger.info(f"Intención detectada: {intent} (confianza: {confidence:.2f}, sentimiento: {sentiment})")
        
        # ============================================
        # 2. REGISTRAR EN MEMORIA
        # ============================================
        user_memory.add_message(user_id, "user", user_message)
        
        # Extraer temas de interés basados en la intención
        topic_mapping = {
            "seguridad": "seguridad",
            "camaras": "cámaras",
            "alarmas": "alarmas",
            "sensores": "sensores",
            "cerco": "cercos eléctricos",
            "acceso": "control de acceso"
        }
        if intent in topic_mapping:
            user_memory.add_interest(user_id, topic_mapping[intent])
            user_memory.set_preference(user_id, "ultimo_tema", topic_mapping[intent])
        
        # Obtener contexto de conversación previa
        conversation_context = user_memory.get_context(user_id)
        conversation_summary = user_memory.get_conversation_summary(user_id)
        
        # ============================================
        # 3. PROCESAR SEGÚN INTENCIÓN
        # ============================================
        response = ""
        
        # ----- SALUDOS -----
        if intent == "saludo":
            interaction_count = user_memory.interaction_count.get(user_id, 0)
            if interaction_count > 3:
                # Usuario conocido - saludo personalizado
                interests = user_memory.get_interests(user_id)
                interest_text = f" Veo que te interesan las {' y '.join(interests[-2:]) if interests else 'cámaras de seguridad'}."
                
                # Personalizar según sentimiento
                if sentiment == "negativo":
                    response = (
                        f"¡Hola {user_name}! 👋\n\n"
                        f"Veo que estás pasando por algo difícil.{interest_text}\n\n"
                        "Estoy aquí para ayudarte. ¿En qué puedo colaborarte?"
                    )
                elif sentiment == "positivo":
                    response = (
                        f"¡Hola {user_name}! 👋\n\n"
                        f"¡Me alegra verte de buen humor!{interest_text}\n\n"
                        "¿En qué puedo ayudarte hoy?"
                    )
                else:
                    response = (
                        f"¡Hola {user_name}! 👋\n\n"
                        f"Bienvenido de nuevo.{interest_text}\n\n"
                        "¿En qué puedo ayudarte hoy?"
                    )
            else:
                response = get_saludo()
        
        # ----- DESPEDIDAS -----
        elif intent == "despedida":
            response = (
                f"¡Hasta luego {user_name}! 👋\n\n"
                "Fue un placer ayudarte. "
                "Si tienes más preguntas sobre seguridad, no dudes en escribirme."
            )
        
        # ----- AGRADECIMIENTOS -----
        elif intent == "agradecimiento":
            if sentiment == "positivo":
                response = (
                    "¡De nada! 😊\n\n"
                    "¡Me alegra mucho poder ayudarte! "
                    "¿Hay algo más en lo que pueda asistirte?"
                )
            else:
                response = (
                    "¡De nada! 😊\n\n"
                    "Me alegra poder ayudarte. "
                    "¿Hay algo más en lo que pueda asistirte?"
                )
        
        # ----- EMERGENCIAS -----
        elif intent == "emergencia":
            response = get_emergencia_text()
        
        # ----- PROBLEMAS -----
        elif intent == "problema":
            if sentiment == "urgente":
                response = (
                    "⚠️ *Entiendo que es urgente.*\n\n"
                    "Voy a ayudarte a resolver esto. ¿Podrías darme más detalles del problema?\n"
                    "¿Qué equipo está fallando y cuál es el error específico?"
                )
            else:
                response = (
                    "Entiendo que tienes un problema. 😟\n\n"
                    "¿Podrías darme más detalles?\n"
                    "- ¿Qué equipo está fallando?\n"
                    "- ¿Cuál es el error o síntoma?\n"
                    "- ¿Cuándo empezó a fallar?\n\n"
                    "Con esta información podré ayudarte mejor."
                )
        
        # ----- AYUDA -----
        elif intent == "ayuda":
            response = get_help_content()
        
        # ----- CONTACTO -----
        elif intent == "contacto":
            response = get_contact_content()
        
        # ----- CONSULTAS DE IA CON BÚSQUEDA -----
        elif intent == "consulta_ia" or intent == "precios" or intent == "compra" or (confidence > 0.5 and intent == "desconocido"):
            # Usar búsqueda web para obtener información actualizada
            topic = "general"
            if intent == "camaras" or "cámara" in query or "camara" in query:
                topic = "camaras"
            elif intent == "alarmas" or "alarma" in query:
                topic = "alarmas"
            elif intent == "sensores" or "sensor" in query:
                topic = "sensores"
            elif intent == "cerco" or "cerco" in query:
                topic = "cerco"
            elif intent == "acceso" or "acceso" in query:
                topic = "acceso"
            
            # Buscar información actualizada
            await update.message.reply_text("🔍 Buscando información actualizada...", parse_mode='Markdown')
            search_result = search_security_info(user_message, use_web=True, category=topic)
            
            # También consultar a Ollama si está disponible
            ollama_available = False
            try:
                response_ollama = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
                ollama_available = response_ollama.status_code == 200
            except:
                pass
            
            if ollama_available:
                await update.message.reply_text("🤖 Analizando con IA...", parse_mode='Markdown')
                
                # Personalizar el prompt según el sentimiento
                sentiment_context = ""
                if sentiment == "urgente":
                    sentiment_context = "El usuario está en una situación urgente. Sé breve y directo en tu respuesta."
                elif sentiment == "negativo":
                    sentiment_context = "El usuario parece tener un problema. Sé empático y ofrece soluciones concretas."
                elif sentiment == "positivo":
                    sentiment_context = "El usuario está de buen humor. Puedes ser más detallado y expansivo en tu respuesta."
                
                system_prompt = f"""Eres un asistente de seguridad residencial y comercial experto en México.
Eres amable, profesional y servicial.

Contexto del usuario: {conversation_summary}
{sentiment_context}

Información de referencia:
{search_result}

Instrucciones:
1. Proporciona recomendaciones específicas y prácticas
2. Menciona precios aproximados en MXN (pesos mexicanos) cuando sea relevante
3. Considera el contexto y preferencias del usuario
4. Si hay múltiples opciones, explícalas claramente
5. Da seguimiento con preguntas para entender mejor sus necesidades
6. Si no estás seguro de algo, admítelo honestamente

Basándote en esta información, proporciona una respuesta clara y útil al usuario."""
                
                ai_response = get_ollama_smart_response(user_message, system_prompt)
                if ai_response:
                    response = f"{search_result}\n\n💡 *Análisis de IA:*\n{ai_response}"
                    user_memory.add_message(user_id, "assistant", ai_response)
                else:
                    response = search_result
            else:
                response = search_result
        
        # ----- BOTONES DEL MENÚ PRINCIPAL -----
        elif "🏠 inicio" in query:
            response = (
                f"🏠 *Menú Principal*\n\n"
                f"¡Hola {user_name}! ¿En qué puedo ayudarte?\n\n"
                "Selecciona una opción del menú o simplemente escribe tu pregunta."
            )
        elif "🔒 seguridad" in query or intent == "seguridad":
            response = get_seguridad_general()
        elif "📹 cámaras" in query or intent == "camaras":
            response = get_camaras()
        elif "🔔 alarmas" in query or intent == "alarmas":
            response = get_alarmas()
        elif "🌡️ sensores" in query or intent == "sensores":
            response = get_sensores()
        elif "⚡ cercos" in query or intent == "cerco":
            response = get_cerco()
        elif "🚪 acceso" in query or intent == "acceso":
            response = get_control_acceso()
        elif "💡 tips" in query or " tips" in query:
            response = get_tips_content()
        elif "📞 contacto" in query:
            response = get_contact_content()
        elif "❓ ayuda" in query:
            response = get_help_content()
        
        # ----- BOTONES DE CONTROL DEL SISTEMA -----
        elif "🔴 estado del sistema" in query or intent == "estado":
            response = get_system_status()
        elif "🟢 reiniciar servicios" in query:
            response = (
                "🔄 *Reiniciando servicios...*\n\n"
                "Los servicios de seguridad se están reiniciando.\n"
                "⏱️ Tiempo estimado: 30 segundos\n\n"
                "Por favor espera un momento..."
            )
        elif "📊 métricas" in query:
            response = get_metrics()
        elif "⚙️ configuración" in query or intent == "configuracion":
            response = get_settings()
        elif "📋 menú principal" in query:
            response = (
                f"📋 *Menú Principal*\n\n"
                f"¿En qué puedo ayudarte {user_name}?\n\n"
                "Usa los botones o simplemente pregúntame."
            )
        
        # ----- PALABRAS CLAVE GENERALES -----
        elif "seguridad" in query or intent == "seguridad":
            response = search_security_info(user_message, use_web=True, category="general")
        elif "cámara" in query or "camara" in query or intent == "camaras":
            response = search_security_info(user_message, use_web=True, category="camaras")
        elif "sensor" in query or intent == "sensores":
            response = search_security_info(user_message, use_web=True, category="sensores")
        elif "alarma" in query or intent == "alarmas":
            response = search_security_info(user_message, use_web=True, category="alarmas")
        elif "cerco" in query or intent == "cerco":
            response = search_security_info(user_message, use_web=True, category="cerco")
        elif "acceso" in query or "control" in query or intent == "acceso":
            response = search_security_info(user_message, use_web=True, category="acceso")
        
        # ----- CONSULTAS ESPECÍFICAS -----
        elif intent == "marca" or "marca" in query or "marcas" in query:
            response = search_security_info(user_message, use_web=True, category="marca")
        elif intent == "precios" or "precio" in query or "costo" in query or "cuanto" in query:
            response = search_security_info(user_message, use_web=True, category="precios")
        elif intent == "compra" or "comprar" in query:
            response = search_security_info(user_message, use_web=True, category="precios")
        elif intent == "negocio" or "negocio" in query or "tienda" in query or "oficina" in query:
            response = search_security_info(user_message, use_web=True, category="negocio")
        elif intent == "casa" or "casa" in query or "hogar" in query:
            response = search_security_info(user_message, use_web=True, category="casa")
        elif intent == "comparar" or "comparar" in query or "vs" in query or "versus" in query:
            response = search_security_info(user_message, use_web=True, category="comparar")
        elif intent == "problema" or "problema" in query or "error" in query or "no funciona" in query:
            response = search_security_info(user_message, use_web=True, category="problema")
        elif intent == "robo" or "robo" in query or "asalto" in query or "ladrón" in query or "ladron" in query:
            response = search_security_info(user_message, use_web=True, category="robo")
        elif intent == "recomendar" or "recomendar" in query or "recomendación" in query:
            response = search_security_info(user_message, use_web=True, category="general")
        elif intent == "instalar" or "instalar" in query or "instalación" in query:
            response = search_security_info(user_message, use_web=True, category="general")
        elif intent == "mantenimiento" or "mantenimiento" in query:
            response = search_security_info(user_message, use_web=True, category="general")
        
        # ----- CONSULTAS OLLAMA (SI ESTÁ DISPONIBLE) -----
        elif is_ollama_available():
            await update.message.reply_text("🤖 Procesando con IA...", parse_mode='Markdown')
            
            # Construir contexto mejorado
            context_info = (
                f"Usuario: {user_name}\n"
                f"ID: {user_id}\n"
                f"Historial: {conversation_summary}\n"
                f"Último tema: {user_memory.get_preferences(user_id).get('ultimo_tema', 'N/A')}"
            )
            
            response = process_message_with_ollama(user_id, user_message, context_info)
            
            if not response:
                response = get_default_response_smart(user_name)
        
        # ----- RESPUESTA POR DEFECTO -----
        else:
            response = get_default_response_smart(user_name)
        
        # ============================================
        # 4. GUARDAR RESPUESTA EN MEMORIA
        # ============================================
        if response:
            user_memory.add_message(user_id, "assistant", response[:500])  # Limitar longitud
        
        # ============================================
        # 5. ENVIAR RESPUESTA
        # ============================================
        await update.message.reply_text(response, parse_mode='Markdown')
        
        # ============================================
        # 6. PREGUNTA DE SEGUIMIENTO (Follow-up)
        # ============================================
        # Solo enviar follow-up si no es una emergencia o despedida
        if intent not in ["emergencia", "despedida", "contacto"] and sentiment != "urgente":
            followup = user_memory.get_followup_question(user_id, intent)
            if followup and len(user_memory.conversation_history.get(user_id, [])) > 2:
                # Solo enviar follow-up si ya hay conversación previa
                import random
                if random.random() < 0.4:  # 40% de probabilidad de enviar follow-up
                    await asyncio.sleep(1)  # Pequeña pausa para naturalidad
                    await update.message.reply_text(
                        f"\n💬 {followup}",
                        parse_mode='Markdown'
                    )
        
    except Exception as e:
        logger.error(f"Error en handle_message: {e}")
        try:
            await update.message.reply_text(
                "¡Hola! No entendí tu pregunta. "
                "¿Puedes reformularla o preguntar sobre seguridad residencial?"
            )
        except:
            logger.error("No se pudo enviar el mensaje de error")

# ============================================
# FUNCIONES DE RESPUESTA
# ============================================

def get_saludo():
    return (
        "¡Hola! 👋\n\n"
        "Bienvenido al asistente de seguridad residencial.\n\n"
        "Puedo ayudarte con:\n"
        "• 🔒 Sistemas de seguridad\n"
        "• 📹 Cámaras de vigilancia\n"
        "• 🔔 Alarmas y sensores\n"
        "• 💡 Consejos de seguridad\n\n"
        "¿Sobre qué tema te gustaría información?"
    )

def get_seguridad_general():
    return (
        "🔒 *Seguridad Residencial Integral*\n\n"
        "*Sistemas básicos:*\n"
        "• 🔐 Cerraduras inteligentes\n"
        "• 📹 Sistema de cámaras\n"
        "• 🔔 Alarma con monitoreo\n"
        "• 💡 Iluminación automatizada\n\n"
        "*Sistemas avanzados:*\n"
        "• ⚡ Cerco eléctrico perimetral\n"
        "• 🚪 Control de acceso\n"
        "• 📡 Detector de movimiento\n"
        "• 🔥 Sistema contra incendios\n\n"
        "¿Qué sistema te interesa más? Puedo darte detalles de cada uno."
    )

def get_camaras():
    return (
        "📹 *Cámaras de Seguridad*\n\n"
        "*Tipos de cámaras:*\n"
        "• 🎥 Domo (para interiores)\n"
        "• 📷 Bullet (para exteriores)\n"
        "• 🔄 PTZ (movimiento y zoom)\n"
        "• 🌙 Cámaras con visión nocturna\n"
        "• 📡 Cámaras IP/WiFi\n\n"
        "*Características importantes:*\n"
        "• Resolución (720p, 1080p, 4K)\n"
        "• Ángulo de visión\n"
        "• Audio bidireccional\n"
        "• Almacenamiento (Nube/SD)\n"
        "• Detección de movimiento\n\n"
        "¿Tienes alguna pregunta específica sobre cámaras?"
    )

def get_sensores():
    return (
        "🔔 *Sensores de Seguridad*\n\n"
        "*Tipos de sensores:*\n"
        "• 🚪 Sensores de apertura (puertas/ventanas)\n"
        "• 🏃 Sensores de movimiento (PIR)\n"
        "• 🔥 Sensores de humo y calor\n"
        "• 💨 Sensores de gas\n"
        "• 🌡️ Sensores de temperatura\n"
        "• 💧 Sensores de inundación\n\n"
        "*Recomendaciones:*\n"
        "• Instala sensores en todos los puntos de entrada\n"
        "• Usa sensores PIR en áreas comunes\n"
        "• Combina sensores de diferentes tipos\n"
        "¿Cuál tipo te interesa más?"
    )

def get_alarmas():
    return (
        "🔔 *Sistemas de Alarma*\n\n"
        "*Tipos de alarmas:*\n"
        "• 📢 Alarmas audibles (silban fuerte)\n"
        "• 📱 Alarmas con notificación a celular\n"
        "• 🏢 Sistemas monitoreados (24/7)\n"
        "• 🔐 Alarmas silenciosas\n"
        "• ⚡ Alarmas con cerco eléctrico\n\n"
        "*Características:*\n"
        "• Conexión a línea telefónica\n"
        "• Conexión celular (backup)\n"
        "• Conexión WiFi\n"
        "• Batería de respaldo\n"
        "• Control remoto (app)\n\n"
        "¿Qué tipo de alarma necesitas?"
    )

def get_cerco():
    return (
        "⚡ *Cerco Eléctrico*\n\n"
        "*Beneficios:*\n"
        "• Disuasión efectiva\n"
        "• Protección perimetral\n"
        "• Bajo mantenimiento\n"
        "• Deterrencia visual\n\n"
        "*Características técnicas:*\n"
        "• Voltaje disuasivo (no lethal)\n"
        "• Alarmas integradas\n"
        "• Conexión a central de monitoreo\n"
        "• Batería de respaldo\n\n"
        "*Instalación:*\n"
        "• Requiere instalación profesional\n"
        "• Cumple con normativas locales\n"
        "• Mantenimiento trimestral\n\n"
        "¿Te interesa una cotización?"
    )

def get_control_acceso():
    return (
        "🚪 *Control de Acceso*\n\n"
        "*Sistemas disponibles:*\n"
        "• 🔑 Teclados numéricos\n"
        "• 🧬 Lectores de huella digital\n"
        "• 📱 Control por smartphone\n"
        "• 💳 Tarjetas de proximidad\n"
        "• 🎭 Reconocimiento facial\n\n"
        "*Aplicaciones:*\n"
        "• Puertas principales\n"
        "• Puertas de garage\n"
        "• Áreas restringidas\n"
        "• Registro de accesos\n\n"
        "¿Qué tipo de control necesitas?"
    )

def get_default_response():
    return (
        "¡Hola! 👋\n\n"
        "Estoy especializado en seguridad residencial.\n\n"
        "*Puedes preguntarme sobre:*\n"
        "• 🔒 Seguridad general\n"
        "• 📹 Cámaras de vigilancia\n"
        "• 🔔 Alarmas y sensores\n"
        "• ⚡ Cerco eléctrico\n"
        "• 🚪 Control de acceso\n"
        "• 💡 Tips de seguridad\n\n"
        "También puedes usar /help para ver todos los comandos.\n"
        "¿Sobre qué tema te gustaría información?"
    )

def get_default_response_smart(user_name: str = "") -> str:
    """
    Respuesta por defecto inteligente quePersonaliza según el usuario.
    """
    # Obtener preferencias del usuario si está disponible
    user_id = None  # Esta función se llama sin user_id, así que usamos una respuesta genérica
    
    responses = [
        f"¡Hola {user_name}! 👋 No entendí completamente tu mensaje, pero estoy aquí para ayudarte con seguridad residencial.",
        f"¿Podrías reformular tu pregunta {user_name}? Puedo ayudarte con cámaras, alarmas, sensores, cercos eléctricos y más.",
        f"No estoy seguro de lo que preguntas {user_name}. ¿Sobre qué tema de seguridad necesitas información?",
    ]
    
    import random
    base_response = random.choice(responses)
    
    return (
        f"{base_response}\n\n"
        "*Puedes preguntarme sobre:*\n"
        "• 🔒 Sistemas de seguridad\n"
        "• 📹 Cámaras de vigilancia\n"
        "• 🔔 Alarmas y sensores\n"
        "• ⚡ Cerco eléctrico\n"
        "• 🚪 Control de acceso\n"
        "• 💡 Consejos de seguridad\n\n"
        "¡También puedes usar comandos como /help para ver más opciones!"
    )

def get_ollama_smart_response(user_message: str, system_prompt: str = "") -> str:
    """
    Obtiene una respuesta inteligente de Ollama usando el contexto del usuario.
    """
    try:
        url = f"{OLLAMA_HOST}/api/chat"
        
        if not system_prompt:
            system_prompt = """Eres un asistente de seguridad residencial experto.
            Ayudas a los usuarios con información sobre sistemas de seguridad, cámaras, alarmas, sensores, 
            cercos eléctricos, control de acceso y consejos de seguridad para el hogar.
            
            Responde de manera clara, útil y concisa. Si no sabes algo, admítelo honestamente."""
        
        data = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            "stream": False,
            "options": {
                "temperature": 0.7,
                "top_p": 0.9,
                "max_tokens": 500
            }
        }
        
        response = requests.post(url, json=data, timeout=90)
        
        if response.status_code == 200:
            result = response.json()
            return result['message']['content']
        else:
            logger.error(f"Error de Ollama: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"Error al conectar con Ollama: {e}")
        return None

def get_emergencia_text() -> str:
    """
    Texto de emergencia mejorado.
    """
    return (
        "🚨 *Guía de Emergencias*\n\n"
        "*Si estás en peligro inmediato:*\n"
        "📞 911 - Servicios de emergencia\n\n"
        "*Pasos a seguir:*\n"
        "1. Mantén la calma\n"
        "2. Si es seguro, llama al 911\n"
        "3. No confrontes intrusos\n"
        "4. Dirígete a un lugar seguro\n"
        "5. Activa tu alarma si es seguro\n\n"
        "* después de una emergencia:*\n"
        "• Preserva evidencia\n"
        "• Documenta daños\n"
        "• Contacta tu compañía de seguros\n"
        "• Llama al servicio técnico\n\n"
        "¿Necesitas ayuda inmediata? Escribe /contacto"
    )

# ============================================
# FUNCIONES DE CONTENIDO PARA BOTONES
# ============================================

def get_tips_content() -> str:
    """Contenido de tips de seguridad"""
    return (
        "💡 *Consejos de Seguridad*\n\n"
        "▸ *Protección básica:*\n"
        "   • Instala cerraduras de alta seguridad\n"
        "   • Usa cerrojo en puertas principales\n"
        "   • No compartas claves con terceros\n\n"
        "▸ *Cámaras:*\n"
        "   • Instala en puntos de entrada\n"
        "   • Usa cámaras con visión nocturna\n"
        "   • Configura notificaciones en tiempo real\n\n"
        "▸ *Iluminación:*\n"
        "   • Instala sensores de movimiento\n"
        "   • Ilumina áreas oscuras\n"
        "   • Usa luces con temporizador\n\n"
        "▸ *Alarmas:*\n"
        "   • Activa siempre al salir\n"
        "   • Mantén los sensores funcionando\n"
        "   • Revisa las baterías regularmente\n\n"
        "¿Quieres más información sobre algún tema específico?"
    )

def get_contact_content() -> str:
    """Contenido de información de contacto"""
    return (
        "📞 *Información de Contacto*\n\n"
        "*Servicio técnico 24/7:*\n"
        "   📱 Tel: +52 55 1234 5678\n"
        "   📧 Email: soporte@seguridadresidencial.com\n\n"
        "*Ventas:*\n"
        "   📱 Tel: +52 55 8765 4321\n"
        "   📧 Email: ventas@seguridadresidencial.com\n\n"
        "*Dirección:*\n"
        "   📍 Av. Principal #123, Ciudad\n\n"
        "* Redes sociales:*\n"
        "   📘 Facebook: @SeguridadResidencial\n"
        "   📸 Instagram: @seguridad_residencial\n\n"
        "¿Necesitas asistencia inmediata? Escribe /emergencia"
    )

def get_help_content() -> str:
    """Contenido de ayuda"""
    return (
        "❓ *Centro de Ayuda*\n\n"
        "*Comandos disponibles:*\n"
        "▸ /start - Iniciar el bot\n"
        "▸ /help - Mostrar esta ayuda\n"
        "▸ /contacto - Información de contacto\n"
        "▸ /tips - Consejos de seguridad\n"
        "▸ /emergencia - Guía de emergencias\n"
        "▸ /ai - Estado de IA\n"
        "▸ /openclaw - Estado de OpenClaw\n"
        "▸ /agent <pregunta> - Consultar al agente\n"
        "▸ /send <número> <mensaje> - Enviar mensaje\n\n"
        "*Botones del menú:*\n"
        "▸ 🏠 Inicio - Volver al menú principal\n"
        "▸ 🔒 Seguridad - Información general\n"
        "▸ 📹 Cámaras - Sistemas de video\n"
        "▸ 🔔 Alarmas - Sistemas de alerta\n"
        "▸ 🌡️ Sensores - Detectores varios\n"
        "▸ ⚡ Cercos - Cercos eléctricos\n"
        "▸ 🚪 Acceso - Control de accesos\n\n"
        "¿Tienes alguna duda? ¡Escríbeme!"
    )

def get_system_status() -> str:
    """Estado del sistema de seguridad"""
    openclaw_status = "🟢 Activo" if is_ollama_available() else "🔴 Inactivo"
    ai_status = "🟢 Disponible" if DEEPSEEK_API_KEY else "⚪ No configurado"
    
    return (
        f"🔴 *Estado del Sistema*\n\n"
        f"▸ *Gateway OpenClaw*: {openclaw_status}\n"
        f"▸ *IA DeepSeek*: {ai_status}\n"
        f"▸ *Bot Telegram*: 🟢 Activo\n"
        f"▸ *Uptime*: 99.9%\n\n"
        f"*Dispositivos conectados:*\n"
        f"▸ Cámaras: 4/4 en línea\n"
        f"▸ Sensores: 8/8 activos\n"
        f"▸ Alarmas: 2/2 operativa\n"
        f"▸ Cerraduras: 3/3 conectadas\n\n"
        f"*Última actualización:* hace 2 minutos"
    )

def get_metrics() -> str:
    """Métricas del sistema"""
    return (
        "📊 *Métricas del Sistema*\n\n"
        "*Rendimiento:*\n"
        "▸ CPU: 23%\n"
        "▸ Memoria: 512MB / 2GB\n"
        "▸ Disco: 45% usado\n"
        "▸ Red: 12 Mbps\n\n"
        "*Estadísticas:*\n"
        "▸ Mensajes hoy: 47\n"
        "▸ Consultas IA: 12\n"
        "▸ Alarmas activadas: 0\n"
        "▸ Grabaciones: 24 clips\n\n"
        "*Conexiones:*\n"
        "▸ Telegram: 🟢 Conectado\n"
        "▸ OpenClaw: 🟢 En línea\n"
        "▸ DeepSeek: {'🟢 Activo' if DEEPSEEK_API_KEY else '⚪ Inactivo'}"
    )

def get_settings() -> str:
    """Configuración del sistema"""
    return (
        "⚙️ *Configuración*\n\n"
        "*Notificaciones:*\n"
        "▸ Alertas de movimiento: ✅ Activado\n"
        "▸ Notificaciones de alarma: ✅ Activado\n"
        "▸ Reportes diarios: ✅ Activado\n\n"
        "*Grabación:*\n"
        "▸ Modo: Detección de movimiento\n"
        "▸ Calidad: 1080p\n"
        "▸ Retención: 7 días\n\n"
        "*Horario:*\n"
        "▸ Modo seguro: 24/7\n"
        "▸ Activación automática: No configurado\n\n"
        "*Usa los comandos para cambiar:*\n"
        "▸ /ai - Configurar IA\n"
        "▸ /openclaw - Ajustes de OpenClaw"
    )

# ============================================
# FUNCIÓN PRINCIPAL
# ============================================

async def main():
    """Función principal del bot"""
    try:
        if not BOT_TOKEN or BOT_TOKEN == "TU_TOKEN_AQUI":
            logger.error("ERROR: Token de Telegram no configurado")
            print("ERROR: Por favor configura tu token de Telegram en la variable de entorno BOT_TOKEN")
            print("Puedes crear un archivo .env con BOT_TOKEN=tu_token_o_usar_docker-compose")
            return
        
        # ============================================
        # MANEJADOR DE CALLBACKS (BOTONES INLINE)
        # ============================================
        
        async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """Maneja los callbacks de los botones inline"""
            query = update.callback_query
            await query.answer()
            
            callback_data = query.data
            user_name = update.effective_user.first_name
            
            # Menú de seguridad
            if callback_data == "menu_security":
                await query.edit_message_text(
                    get_seguridad_general(),
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(SYSTEM_MENU_INLINE))
                )
            
            # Menú de cámaras
            elif callback_data == "menu_cameras":
                await query.edit_message_text(
                    get_camaras(),
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(CAMERA_MENU_INLINE))
                )
            
            # Menú de alarmas
            elif callback_data == "menu_alarms":
                await query.edit_message_text(
                    get_alarmas(),
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(ALARM_MENU_INLINE))
                )
            
            # Menú de cercos
            elif callback_data == "menu_fence":
                await query.edit_message_text(
                    get_cerco(),
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(FENCE_MENU_INLINE))
                )
            
            # Menú de control de acceso
            elif callback_data == "menu_access":
                await query.edit_message_text(
                    get_control_acceso(),
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(ACCESS_MENU_INLINE))
                )
            
            # Tips de seguridad
            elif callback_data == "menu_tips":
                await query.edit_message_text(
                    "💡 *Tips de Seguridad*\n\n" + get_tips_content(),
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(SYSTEM_MENU_INLINE))
                )
            
            # Contacto
            elif callback_data == "menu_contact":
                await query.edit_message_text(
                    get_contact_content(),
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(SYSTEM_MENU_INLINE))
                )
            
            # Menú de sensores
            elif callback_data == "menu_sensors":
                await query.edit_message_text(
                    "🌡️ *Sensores de Seguridad*\n\n"
                    "📊 *Sensores disponibles:*\n"
                    "• 🌡️ Temperatura: Monitoreo de temperatura\n"
                    "• 💧 Humedad: Control de humedad\n"
                    "• 🔥 Fuego: Detectores de incendio\n"
                    "• ⛽ Gas: Detectores de fuga de gas\n"
                    "• 🚪 Puerta: Sensores de apertura\n"
                    "• 👁️ Movimiento: Detección PIR\n\n"
                    "Selecciona un sensor para más detalles:",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(SENSORS_MENU_INLINE))
                )
            
            # Menú de configuración
            elif callback_data == "menu_settings":
                await query.edit_message_text(
                    "⚙️ *Configuración del Sistema*\n\n"
                    "🔧 *Opciones disponibles:*\n"
                    "• 📝 Editar perfil de usuario\n"
                    "• 🔔 Configurar notificaciones\n"
                    "• 🌐 Cambiar idioma\n"
                    "• ⏰ Configurar horarios\n"
                    "• 🔐 Cambiar contraseña\n"
                    "• 📊 Preferencias de privacidad\n\n"
                    "Selecciona una opción:",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(SYSTEM_MENU_INLINE))
                )
            
            # Estado general del sistema
            elif callback_data == "menu_status":
                await query.edit_message_text(
                    "🎯 *Estado General del Sistema*\n\n"
                    "🟢 *Conexión:* En línea\n"
                    "🔋 *Batería:* 85%\n"
                    "📡 *Señal:* Fuerte\n"
                    "💾 *Almacenamiento:* 45% usado\n"
                    "👤 *Usuarios activos:* 3\n\n"
                    "Selecciona una opción para más detalles:",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(SYSTEM_MENU_INLINE))
                )
            
            # Panel principal
            elif callback_data == "menu_main":
                await query.edit_message_text(
                    "🏠 *Panel de Control Principal*\n\n"
                    "¡Bienvenido al centro de control!\n\n"
                    "📊 *Resumen:*\n"
                    "• 🔒 5 zonas protegidas\n"
                    "• 📹 4 cámaras activas\n"
                    "• 🔔 2 alarmas configuradas\n"
                    "• 🌡️ 6 sensores instalados\n\n"
                    "¿Qué deseas controlar?",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(SYSTEM_MENU_INLINE))
                )
            
            # Ayuda
            elif callback_data == "menu_help":
                await query.edit_message_text(
                    "❓ *Centro de Ayuda*\n\n" + get_help_content(),
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(SYSTEM_MENU_INLINE))
                )
            
            # Acciones del sistema
            elif callback_data == "system_status":
                await query.edit_message_text(
                    get_system_status(),
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(SYSTEM_MENU_INLINE))
                )
            
            elif callback_data == "system_restart":
                await query.edit_message_text(
                    "🔄 *Reiniciando servicios...*\n\n"
                    "Los servicios de seguridad se están reiniciando.\n"
                    "⏱️ Tiempo estimado: 30 segundos",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(SYSTEM_MENU_INLINE))
                )
            
            elif callback_data == "system_metrics":
                await query.edit_message_text(
                    get_metrics(),
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(SYSTEM_MENU_INLINE))
                )
            
            elif callback_data == "system_settings":
                await query.edit_message_text(
                    get_settings(),
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(SYSTEM_MENU_INLINE))
                )
            
            # Acciones de cámara
            elif callback_data == "camera_view":
                await query.edit_message_text(
                    "📹 *Vista de Cámaras*\n\n"
                    "🎥 Cámaras disponibles:\n"
                    "• Cámara 1: Entrada principal - 🟢 En línea\n"
                    "• Cámara 2: Jardín trasero - 🟢 En línea\n"
                    "• Cámara 3: Garaje - 🟡 Sin conexión\n"
                    "• Cámara 4: Patio lateral - 🟢 En línea\n\n"
                    "Selecciona una cámara para ver:",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(CAMERA_MENU_INLINE))
                )
            
            elif callback_data == "camera_record":
                await query.edit_message_text(
                    "🔴 *Grabación en progreso*\n\n"
                    "Todas las cámaras están grabando.\n"
                    "💾 Almacenamiento: 45% usado\n"
                    "📁 Directorio: /recordings",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(CAMERA_MENU_INLINE))
                )
            
            # Acciones de alarmas
            elif callback_data == "alarm_activate":
                await query.edit_message_text(
                    "🔔 *Alarma Activada*\n\n"
                    "✅ Sistema de alarmas activado\n"
                    "🛡️ Modo: Protección total\n"
                    "📡 Conexión: Monitoreo 24/7",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(ALARM_MENU_INLINE))
                )
            
            elif callback_data == "alarm_deactivate":
                await query.edit_message_text(
                    "🔕 *Alarma Desactivada*\n\n"
                    "El sistema de alarmas ha sido desactivado.\n"
                    "⚠️ Nota: La propiedad no está protegida.",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(ALARM_MENU_INLINE))
                )
            
            # Acciones de sensores
            elif callback_data == "sensor_temp":
                await query.edit_message_text(
                    "🌡️ *Sensor de Temperatura*\n\n"
                    "📊 *Lectura actual:* 22°C\n"
                    "📈 *Temperatura mínima:* 18°C\n"
                    "📉 *Temperatura máxima:* 28°C\n\n"
                    "⚙️ *Configuración:*\n"
                    "• Alerta si > 30°C\n"
                    "• Alerta si < 15°C",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(SENSORS_MENU_INLINE))
                )
            
            elif callback_data == "sensor_humidity":
                await query.edit_message_text(
                    "💧 *Sensor de Humedad*\n\n"
                    "📊 *Lectura actual:* 55%\n"
                    "📈 *Nivel óptimo:* 40-60%\n\n"
                    "⚙️ *Configuración:*\n"
                    "• Alerta si > 70%\n"
                    "• Alerta si < 30%",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(SENSORS_MENU_INLINE))
                )
            
            elif callback_data == "sensor_fire":
                await query.edit_message_text(
                    "🔥 *Detector de Incendio*\n\n"
                    "📊 *Estado:* Monitoreando\n"
                    "🟢 *Estado:* Normal\n\n"
                    "⚙️ *Configuración:*\n"
                    "• Sensibilidad: Alta\n"
                    "• Notificaciones inmediatas\n"
                    "• Activar sirena automáticamente",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(SENSORS_MENU_INLINE))
                )
            
            elif callback_data == "sensor_gas":
                await query.edit_message_text(
                    "⛽ *Detector de Gas*\n\n"
                    "📊 *Estado:* Monitoreando\n"
                    "🟢 *Nivel de gas:* Normal\n\n"
                    "⚙️ *Configuración:*\n"
                    "• Alerta por fuga de gas\n"
                    "• Notificaciones inmediatas\n"
                    "• Ventilación automática",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(SENSORS_MENU_INLINE))
                )
            
            elif callback_data == "sensor_door":
                await query.edit_message_text(
                    "🚪 *Sensor de Puerta/Ventana*\n\n"
                    "📊 *Estado:* Puertas cerradas\n"
                    "🔒 *Puerta principal:* Cerrada\n"
                    "🔒 *Puerta trasera:* Cerrada\n"
                    "🔒 *Ventanas:* Cerradas\n\n"
                    "⚙️ *Configuración:*\n"
                    "• Alerta al abrir\n"
                    "• Registro de aperturas",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(SENSORS_MENU_INLINE))
                )
            
            elif callback_data == "sensor_motion":
                await query.edit_message_text(
                    "👁️ *Detector de Movimiento*\n\n"
                    "📊 *Estado:* Activo\n"
                    "👤 *Última detección:* hace 15 min\n\n"
                    "⚙️ *Configuración:*\n"
                    "• Sensibilidad: Media\n"
                    "• Zonas de detección: Todas\n"
                    "• Ignorar mascotas: Sí",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(SENSORS_MENU_INLINE))
                )
            
            # Acciones de control de acceso
            elif callback_data == "access_unlock":
                await query.edit_message_text(
                    "🚪 *Puerta Desbloqueada*\n\n"
                    "✅ La puerta principal ha sido desbloqueada.\n"
                    "⏱️ Se cierre automáticamente en 30 segundos.\n\n"
                    "👤 *Usuario:* Admin",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(ACCESS_MENU_INLINE))
                )
            
            elif callback_data == "access_lock":
                await query.edit_message_text(
                    "🔐 *Puerta Bloqueada*\n\n"
                    "✅ La puerta principal ha sido bloqueada.\n"
                    "🔒 *Estado:* Seguridad activada\n\n"
                    "👤 *Usuario:* Admin",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(ACCESS_MENU_INLINE))
                )
            
            elif callback_data == "access_logs":
                await query.edit_message_text(
                    "📋 *Registros de Acceso*\n\n"
                    "📝 *Últimos accesos:*\n"
                    "• 👤 Admin - 10:30 AM - Puerta principal\n"
                    "• 👤 Juan - 09:45 AM - Puerta trasera\n"
                    "• 👤 Maria - 09:15 AM - Puerta principal\n"
                    "• 👤 Admin - 08:30 AM - Puerta principal\n\n"
                    "Total de accesos hoy: 12",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(ACCESS_MENU_INLINE))
                )
            
            elif callback_data == "access_code":
                await query.edit_message_text(
                    "🔑 *Generar Código de Acceso*\n\n"
                    "📝 *Nuevo código temporal:* **4521**\n\n"
                    "⏱️ *Expira en:* 24 horas\n"
                    "👤 *Usos máximos:* 3\n\n"
                    "Comparte este código con tus visitantes.",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(ACCESS_MENU_INLINE))
                )
            
            # Acciones de cerco eléctrico
            elif callback_data == "fence_activate":
                await query.edit_message_text(
                    "⚡ *Cerco Eléctrico Activado*\n\n"
                    "✅ Sistema de cerco perimetral activo.\n"
                    "🔌 *Voltaje:* 9,000V\n"
                    "🛡️ *Modo:* Disuasivo\n\n"
                    "⚠️ Advertencia: Peligro eléctrico",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(FENCE_MENU_INLINE))
                )
            
            elif callback_data == "fence_deactivate":
                await query.edit_message_text(
                    "💤 *Cerco Eléctrico Desactivado*\n\n"
                    "El cerco perimetral ha sido desactivado.\n"
                    "⚠️ Advertencia: Sin protección perimetral",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(FENCE_MENU_INLINE))
                )
            
            elif callback_data == "fence_voltage":
                await query.edit_message_text(
                    "📊 *Voltaje del Cerco*\n\n"
                    "⚡ *Voltaje actual:* 9,000V\n"
                    "📈 *Voltaje nominal:* 9,000V\n"
                    "🔋 *Batería:* 100%\n\n"
                    "✅ *Estado:* Funcionando correctamente",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(FENCE_MENU_INLINE))
                )
            
            elif callback_data == "fence_alarms":
                await query.edit_message_text(
                    "⚠️ *Alarmas del Cerco*\n\n"
                    "📋 *Historial de alarmas:*\n"
                    "• 🔴 Intrusión detectada - 02:30 AM\n"
                    "• 🟡 Falla de energía - 11:15 PM\n"
                    "• 🔴 Corto circuito - 08:45 PM\n\n"
                    "⚠️ *Alarmas activas:* 0",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(FENCE_MENU_INLINE))
                )
            
            # Nuevas acciones del sistema
            elif callback_data == "system_stats":
                await query.edit_message_text(
                    "📈 *Estadísticas del Sistema*\n\n"
                    "📊 *Hoy:*\n"
                    "• 👤 Visitantes: 12\n"
                    "• 🚪 Aperturas: 45\n"
                    "• ⚠️ Alarmas: 0\n"
                    "• 📹 Grabaciones: 24 hrs\n\n"
                    "📊 *Esta semana:*\n"
                    "• 👤 Visitantes: 84\n"
                    "• 🚪 Aperturas: 312\n"
                    "• ⚠️ Alarmas: 2",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(SYSTEM_MENU_INLINE))
                )
            
            elif callback_data == "system_notifications":
                await query.edit_message_text(
                    "🔔 *Configuración de Notificaciones*\n\n"
                    "📱 *Canales activos:*\n"
                    "• ✅ Telegram\n"
                    "• ✅ SMS\n"
                    "• ❌ Email\n\n"
                    "📋 *Notificaciones:*\n"
                    "• ✅ Movimientos detectados\n"
                    "• ✅ Alarmas activadas\n"
                    "• ✅ Puertas abiertas\n"
                    "• ✅ Sensores de fuego/gas",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(SYSTEM_MENU_INLINE))
                )
        
        # Construir la aplicación
        application = ApplicationBuilder().token(BOT_TOKEN).build()
        
        # Registrar handlers de comandos
        application.add_handler(CommandHandler("start", handle_start))
        application.add_handler(CommandHandler("help", handle_help))
        application.add_handler(CommandHandler("contacto", handle_contacto))
        application.add_handler(CommandHandler("tips", handle_tips))
        application.add_handler(CommandHandler("emergencia", handle_emergencia))
        application.add_handler(CommandHandler("ai", handle_ai))
        application.add_handler(CommandHandler("openclaw", handle_openclaw))
        application.add_handler(CommandHandler("send", handle_send))
        application.add_handler(CommandHandler("agent", handle_agent))
        
        # Registrar handler de callbacks (importante: debe estar antes de MessageHandler)
        application.add_handler(CallbackQueryHandler(handle_callback))
        
        # Registrar handler de mensajes
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        # Iniciar el bot
        logger.info("Iniciando bot de Telegram mejorado...")
        print("🤖 Bot de seguridad residencial mejorado iniciado")
        print("📋 Comandos disponibles: /start, /help, /contacto, /tips, /emergencia")
        print("Presiona Ctrl+C para detener")
        
        await application.run_polling()
        
    except Exception as e:
        logger.error(f"Error al iniciar el bot: {e}")
        print(f"ERROR: {e}")
        raise

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    asyncio.run(main())
