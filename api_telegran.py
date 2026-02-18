import os
import asyncio
import logging
from telegram import Update, InlineKeyboardButton, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler, ConversationHandler
import requests
from openclaw_client import send_via_openclaw, query_agent, is_openclaw_available

# Configuración de Telegram
# Token de tu bot de Telegram (obtenido de @BotFather)
# Se puede pasar como variable de entorno BOT_TOKEN o usar valor por defecto
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Configuración de DeepSeek AI
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

# Configurar logging para mejor depuración
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

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

# Botones principales - Menú simplificado
MAIN_MENU_KEYBOARD = ReplyKeyboardMarkup([
    [KeyboardButton("🏠 Inicio"), KeyboardButton("🔒 Seguridad")],
    [KeyboardButton("📹 Cámaras"), KeyboardButton("🔔 Alarmas")],
    [KeyboardButton("🌡️ Sensores"), KeyboardButton("⚡ Cercos")],
    [KeyboardButton("🚪 Acceso"), KeyboardButton("💡 Tips")],
    [KeyboardButton("📞 Contacto"), KeyboardButton("❓ Ayuda")]
], resize_keyboard=True, one_time_keyboard=False)

# Botones inline para respuestas interactivas
def get_inline_keyboard(buttons: list) -> list:
    """Genera un keyboard inline de botones"""
    keyboard = []
    row = []
    for i, (text, callback_data) in enumerate(buttons):
        row.append(InlineKeyboardButton(text, callback_data=callback_data))
        if (i + 1) % 2 == 0:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    return keyboard

# Menú de control del sistema
SYSTEM_MENU_INLINE = [
    ("🔴 Estado", "system_status"),
    ("🟢 Reiniciar", "system_restart"),
    ("📊 Métricas", "system_metrics"),
    ("⚙️ Ajustes", "system_settings"),
]

# Menú de cámaras
CAMERA_MENU_INLINE = [
    ("📹 Ver Cámaras", "camera_view"),
    ("🔴 Grabar", "camera_record"),
    ("📸 Captura", "camera_capture"),
    ("⚙️ Configurar", "camera_config"),
]

# Menú de alarmas
ALARM_MENU_INLINE = [
    ("🔔 Activar", "alarm_activate"),
    ("🔕 Desactivar", "alarm_deactivate"),
    ("⏰ Programar", "alarm_schedule"),
    ("📋 Historial", "alarm_history"),
]

# ============================================
# FUNCIONES DE DEEPSEEK AI
# ============================================

def get_deepseek_response(user_message: str, context: str = "") -> str:
    """Obtiene una respuesta de DeepSeek AI"""
    if not DEEPSEEK_API_KEY:
        return None
    
    try:
        url = f"{DEEPSEEK_BASE_URL}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        
        system_prompt = f"""Eres un asistente de seguridad residencial experto. 
Ayudas a los usuarios con información sobre sistemas de seguridad, cámaras, alarmas, sensores, cercos eléctricos, control de acceso y consejos de seguridad para el hogar.

Contexto de seguridad residencial:
{context}

Responde de manera clara, útil y concisa. Si no sabes algo, admítelo honestamente."""
        
        data = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            "max_tokens": 500,
            "temperature": 0.7
        }
        
        response = requests.post(url, headers=headers, json=data, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            return result['choices'][0]['message']['content']
        else:
            logger.error(f"Error de DeepSeek: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"Error al conectar con DeepSeek: {e}")
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
        openclaw_status = "🟢 Disponible" if is_openclaw_available() else "🔴 No disponible"
        ai_status = "🟢 Activa" if DEEPSEEK_API_KEY else "⚪ No configurada"
        
        welcome_text = (
            f"🌙 *Bienvenido a tu Asistente de Seguridad*\n\n"
            f"¡Hola {user_name}! 👋\n\n"
            f"▸ *Estado del Sistema*: 🟢 Activo\n"
            f"▸ *Conexión OpenClaw*: {openclaw_status}\n"
            f"▸ *IA DeepSeek*: {ai_status}\n\n"
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
        
        # También enviar botones inline para acceso rápido
        inline_keyboard = get_inline_keyboard([
            ("🔒 Seguridad", "menu_security"),
            ("📹 Cámaras", "menu_cameras"),
            ("🔔 Alarmas", "menu_alarms"),
            ("⚡ Cercos", "menu_fence"),
            ("🚪 Acceso", "menu_access"),
            ("💡 Tips", "menu_tips"),
            ("📞 Contacto", "menu_contact"),
            ("❓ Ayuda", "menu_help"),
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
    """Maneja el comando /ai - Muestra el estado de DeepSeek"""
    if DEEPSEEK_API_KEY:
        ai_status = (
            "🤖 *DeepSeek AI - Activado*\n\n"
            "La IA está disponible para responder preguntas más complejas.\n\n"
            "Puedes hacer preguntas como:\n"
            "• ¿Qué opinas sobre este sistema de seguridad?\n"
            "• ¿Qué me recomiendas para mi casa?\n"
            "• Analiza las opciones de cámaras\n\n"
            "La IA te ayudará con recomendaciones personalizadas."
        )
    else:
        ai_status = (
            "🤖 *DeepSeek AI - No configurado*\n\n"
            "Para habilitar la IA, configura la variable DEEPSEEK_API_KEY\n"
            "en tu archivo .env\n\n"
            "Obtén tu API key en: https://platform.deepseek.com"
        )
    await update.message.reply_text(ai_status, parse_mode='Markdown')

async def handle_openclaw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja el comando /openclaw - Muestra el estado de OpenClaw"""
    available = is_openclaw_available()
    
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
    """Procesa los mensajes recibidos - Todo pasa por OpenClaw"""
    try:
        if not update.message or not update.message.text:
            return
            
        query = update.message.text.lower()
        user_id = str(update.effective_user.id)
        user_name = update.effective_user.first_name
        
        logger.info(f"Consulta recibida de {user_name}: {query}")
        
        # Verificar si OpenClaw está disponible
        openclaw_available = is_openclaw_available()
        
        # Si OpenClaw está disponible, delegar todo al agente
        if openclaw_available:
            await update.message.reply_text("🤖 Procesando con OpenClaw...", parse_mode='Markdown')
            
            # Construir contexto del usuario
            context_info = f"Usuario: {user_name}\nID: {user_id}"
            
            # Procesar mensaje a través de OpenClaw
            response = process_message_through_openclaw(user_id, update.message.text, context_info)
            
            if response:
                await update.message.reply_text(response, parse_mode='Markdown')
            else:
                await update.message.reply_text(
                    "🤖 El agente está procesando tu solicitud. Intenta de nuevo.",
                    parse_mode='Markdown'
                )
            return
        
        # Fallback: respuestas locales si OpenClaw no está disponible
        response = ""
        
        # ============================================
        # Botones del teclado principal (nuevo menú)
        # ============================================
        if "🏠 inicio" in query:
            response = (
                "🏠 *Menú Principal*\n\n"
                "¡Bienvenido de nuevo! ¿En qué puedo ayudarte?\n\n"
                "Selecciona una opción del menú o simplemente escribe tu pregunta."
            )
        elif "🔒 seguridad" in query:
            response = get_seguridad_general()
        elif "📹 cámaras" in query:
            response = get_camaras()
        elif "🔔 alarmas" in query:
            response = get_alarmas()
        elif "🌡️ sensores" in query:
            response = get_sensores()
        elif "⚡ cercos" in query:
            response = get_cerco()
        elif "🚪 acceso" in query:
            response = get_control_acceso()
        elif "💡 tips" in query or " tips" in query:
            response = get_tips_content()
        elif "📞 contacto" in query:
            response = get_contact_content()
        elif "❓ ayuda" in query:
            response = get_help_content()
        
        # Botones de control del sistema
        elif "🔴 estado del sistema" in query:
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
        elif "⚙️ configuración" in query:
            response = get_settings()
        elif "📋 menú principal" in query:
            response = (
                "📋 *Menú Principal*\n\n"
                "¿En qué puedo ayudarte hoy?\n\n"
                "Usa los botones o simplemente pregúntame."
            )
        
        # Palabras clave en mensajes de texto
        elif "seguridad" in query:
            response = get_seguridad_general()
        elif "cámara" in query or "camara" in query:
            response = get_camaras()
        elif "sensor" in query:
            response = get_sensores()
        elif "alarma" in query:
            response = get_alarmas()
        elif "cerco" in query:
            response = get_cerco()
        elif "acceso" in query or "control" in query:
            response = get_control_acceso()
        elif "emergencia" in query:
            response = "Usa el comando /emergencia para ver qué hacer en emergencias."
        elif "help" in query or "ayuda" in query:
            response = "Usa /help para ver todos los comandos disponibles."
        elif "hola" in query or "buenos" in query:
            response = get_saludo()
        elif "gracias" in query:
            response = "¡De nada! 😊 ¿Hay algo más en lo que pueda ayudarte?"
        
        # Si DeepSeek está configurado, usar IA para consultas complejas
        elif DEEPSEEK_API_KEY and is_ai_query(update.message.text):
            await update.message.reply_text("🤔 Déjame pensar...", parse_mode='Markdown')
            ai_response = get_deepseek_response(update.message.text)
            if ai_response:
                response = ai_response
            else:
                response = get_default_response()
        else:
            response = get_default_response()
        
        await update.message.reply_text(response, parse_mode='Markdown')
        
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
    openclaw_status = "🟢 Activo" if is_openclaw_available() else "🔴 Inactivo"
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
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(SYSTEM_MENU_INLINE))
                )
            
            # Menú de control de acceso
            elif callback_data == "menu_access":
                await query.edit_message_text(
                    get_control_acceso(),
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(get_inline_keyboard(SYSTEM_MENU_INLINE))
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
