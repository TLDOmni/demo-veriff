import os
import hmac
import hashlib
import requests
import logging
from datetime import datetime
from flask import Flask, request, jsonify, redirect
from typing import Dict, Optional

app = Flask(__name__)

# Configuração de logging profissional
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- CONFIGURAÇÕES ---
VERIFF_API_URL = "https://stationapi.veriff.com/v1/sessions"
VERIFF_API_KEY = os.getenv("VERIFF_API_KEY")
VERIFF_SHARED_SECRET = os.getenv("VERIFF_SHARED_SECRET")

INFOBIP_BASE_URL = os.getenv("INFOBIP_BASE_URL")
INFOBIP_API_KEY = os.getenv("INFOBIP_API_KEY")
INFOBIP_SENDER = os.getenv("INFOBIP_SENDER")

WHATSAPP_LINK = f"https://wa.me/{INFOBIP_SENDER}" if INFOBIP_SENDER else "https://wa.me/"
MY_RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "https://demo-veriff.onrender.com")

# Dicionário para armazenar estados temporários (em produção, use Redis)
verification_states = {}

# --- MAPEAMENTO DE MOTIVOS DE REJEIÇÃO ---
REJECTION_REASONS = {
    "1": "Documento expirado",
    "2": "Documento de cor alterada",
    "3": "Documento preto e branco",
    "4": "Documento de má qualidade",
    "5": "Documento danificado",
    "6": "Rosto não visível",
    "7": "Rosto não corresponde ao documento",
    "8": "Menor de idade",
    "9": "Análise de vídeo falhou",
    "102": "Documentos não correspondem",
    "103": "Selfie de baixa qualidade",
    "104": "Nome não corresponde",
    "105": "Data de nascimento não corresponde",
    "106": "Documento não suportado",
    "107": "Expirado há mais de 6 meses",
    "108": "Múltiplas pessoas no vídeo",
    "109": "Foto da tela detectada",
    "201": "Possível fraude",
    "202": "Pessoa em lista de sanções",
    "203": "PEP detectado"
}

# --- FUNÇÕES AUXILIARES ---
def validate_phone_number(phone: str) -> bool:
    """Valida formato do número de telefone"""
    if not phone or "{" in phone or "}" in phone:
        return False
    # Remove caracteres não numéricos
    clean_phone = ''.join(filter(str.isdigit, phone))
    return len(clean_phone) >= 10

def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    """Verifica assinatura HMAC do webhook da Veriff"""
    if not VERIFF_SHARED_SECRET:
        logger.warning("VERIFF_SHARED_SECRET não configurado - pulando validação")
        return True
    
    expected_signature = hmac.new(
        VERIFF_SHARED_SECRET.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(signature.lower(), expected_signature.lower())

def get_rejection_message(reason_code: str) -> str:
    """Retorna mensagem amigável para código de rejeição"""
    return REJECTION_REASONS.get(str(reason_code), f"Motivo técnico: {reason_code}")

def send_whatsapp_message(to_number: str, text: str) -> bool:
    """Envia mensagem via Infobip WhatsApp API"""
    if not validate_phone_number(to_number):
        logger.error(f"Número inválido: {to_number}")
        return False

    url = f"{INFOBIP_BASE_URL}/whatsapp/1/message/text"
    headers = {
        "Authorization": f"App {INFOBIP_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "from": INFOBIP_SENDER,
        "to": to_number,
        "content": {"text": text}
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        
        if response.status_code == 200:
            logger.info(f"Mensagem enviada para {to_number}")
            return True
        else:
            logger.error(f"Erro Infobip {response.status_code}: {response.text}")
            return False
            
    except requests.exceptions.Timeout:
        logger.error(f"Timeout ao enviar mensagem para {to_number}")
        return False
    except Exception as e:
        logger.error(f"Erro ao enviar mensagem: {e}")
        return False

def format_verification_summary(verification_data: Dict) -> str:
    """Formata resumo da verificação para o usuário"""
    person = verification_data.get('person', {})
    document = verification_data.get('document', {})
    
    summary = "📋 *RESUMO DA VERIFICAÇÃO*\n\n"
    
    # Informações pessoais
    if person.get('firstName') or person.get('lastName'):
        summary += f"👤 Nome: {person.get('firstName', '')} {person.get('lastName', '')}\n"
    
    # Tipo de documento
    if document.get('type'):
        doc_types = {
            'PASSPORT': 'Passaporte',
            'ID_CARD': 'Carteira de Identidade',
            'DRIVERS_LICENSE': 'Carteira de Motorista',
            'RESIDENCE_PERMIT': 'Autorização de Residência'
        }
        doc_type = doc_types.get(document.get('type'), document.get('type'))
        summary += f"📄 Documento: {doc_type}\n"
    
    # País do documento
    if document.get('country'):
        summary += f"🌍 País: {document.get('country')}\n"
    
    # Número do documento (parcialmente oculto)
    if document.get('number'):
        doc_number = document.get('number')
        masked = doc_number[:2] + '*' * (len(doc_number) - 4) + doc_number[-2:] if len(doc_number) > 4 else '****'
        summary += f"🔢 Número: {masked}\n"
    
    return summary

# --- ROTAS ---
@app.route('/', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "operational",
        "service": "Veriff-Infobip Middleware",
        "timestamp": datetime.utcnow().isoformat()
    }), 200

@app.route('/start-verification', methods=['POST'])
def start_verification():
    """Inicia sessão de verificação na Veriff"""
    data = request.json
    
    phone = data.get('phoneNumber', '').strip()
    first_name = data.get('first_name', 'Usuário').strip()
    last_name = data.get('last_name', '').strip()
    
    logger.info(f"Iniciando verificação - Nome: {first_name} {last_name}, Tel: {phone}")
    
    # Validações
    if not validate_phone_number(phone):
        logger.error(f"Número de telefone inválido: {phone}")
        return jsonify({
            "error": "Número de telefone inválido",
            "message": "Por favor, verifique o número fornecido"
        }), 400
    
    if not first_name:
        return jsonify({
            "error": "Nome obrigatório",
            "message": "Por favor, informe seu primeiro nome"
        }), 400
    
    # Payload para Veriff
    veriff_payload = {
        "verification": {
            "callback": f"{MY_RENDER_URL}/webhook/veriff",
            "person": {
                "firstName": first_name,
                "lastName": last_name
            },
            "vendorData": phone,
            "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
        }
    }
    
    headers = {
        "X-AUTH-CLIENT": VERIFF_API_KEY,
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(
            VERIFF_API_URL, 
            json=veriff_payload, 
            headers=headers,
            timeout=15
        )
        
        if response.status_code == 201:
            result = response.json()
            session_url = result['verification']['url']
            session_id = result['verification']['id']
            
            # Armazena estado inicial
            verification_states[phone] = {
                "session_id": session_id,
                "status": "started",
                "created_at": datetime.utcnow().isoformat(),
                "first_name": first_name,
                "last_name": last_name
            }
            
            logger.info(f"Sessão Veriff criada: {session_id} para {phone}")
            
            return jsonify({
                "success": True,
                "veriff_link": session_url,
                "session_id": session_id
            }), 200
        else:
            logger.error(f"Erro Veriff {response.status_code}: {response.text}")
            return jsonify({
                "error": "Erro ao criar sessão de verificação",
                "details": response.text
            }), 500
            
    except requests.exceptions.Timeout:
        logger.error("Timeout ao conectar com Veriff")
        return jsonify({"error": "Timeout na conexão com Veriff"}), 504
    except Exception as e:
        logger.error(f"Erro inesperado: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/webhook/veriff', methods=['POST', 'GET'])
def veriff_webhook():
    """
    Webhook da Veriff - aceita GET (redirecionamento) e POST (notificações)
    """
    
    # GET: Usuário retornando da verificação
    if request.method == 'GET':
        logger.info("Usuário retornou da Veriff via GET")
        return redirect(WHATSAPP_LINK, code=302)
    
    # POST: Webhook da Veriff com resultado
    payload = request.get_data()
    signature = request.headers.get('X-HMAC-SIGNATURE', '')
    
    # Valida assinatura
    if not verify_webhook_signature(payload, signature):
        logger.warning("Assinatura inválida do webhook")
        return jsonify({"error": "Invalid signature"}), 401
    
    data = request.json
    action = data.get('action')
    
    logger.info(f"Webhook recebido - Action: {action}")
    
    # Ignora eventos que não são decisões
    if action != 'decision':
        logger.info(f"Evento '{action}' ignorado")
        return jsonify({"status": "ignored"}), 200
    
    # Extrai dados da verificação
    verification = data.get('verification', {})
    vendor_data = verification.get('vendorData')  # Número do telefone
    status = verification.get('status')
    reason = verification.get('reason')
    code = verification.get('code')
    session_id = verification.get('id')
    
    logger.info(f"Decisão recebida - Session: {session_id}, Status: {status}, Phone: {vendor_data}")
    
    if not vendor_data or not validate_phone_number(vendor_data):
        logger.error(f"Vendor data inválido: {vendor_data}")
        return jsonify({"error": "Invalid vendor data"}), 400
    
    # Atualiza estado
    if vendor_data in verification_states:
        verification_states[vendor_data].update({
            "status": status,
            "reason": reason,
            "code": code,
            "updated_at": datetime.utcnow().isoformat()
        })
    
    # Processa resultado e envia mensagem
    if status == 'approved':
        # Verificação aprovada
        summary = format_verification_summary(verification)
        message = f"✅ *VALIDAÇÃO APROVADA*\n\n{summary}\nSua identidade foi confirmada com sucesso!"
        send_whatsapp_message(vendor_data, message)
        
    elif status == 'declined':
        # Verificação rejeitada
        rejection_msg = get_rejection_message(code) if code else reason
        message = f"❌ *VALIDAÇÃO REJEITADA*\n\n"
        message += f"Motivo: {rejection_msg}\n\n"
        message += "Por favor, tente novamente ou entre em contato com o suporte."
        send_whatsapp_message(vendor_data, message)
        
    elif status == 'resubmission_requested':
        # Reenvio solicitado
        message = "⚠️ *NOVA TENTATIVA NECESSÁRIA*\n\n"
        message += "A qualidade da imagem não foi suficiente.\n"
        message += "Por favor, tire novas fotos em um ambiente bem iluminado."
        send_whatsapp_message(vendor_data, message)
        
    elif status == 'expired':
        # Sessão expirada
        message = "⏱️ *SESSÃO EXPIRADA*\n\n"
        message += "O tempo para completar a verificação acabou.\n"
        message += "Por favor, inicie uma nova verificação."
        send_whatsapp_message(vendor_data, message)
    
    else:
        # Status desconhecido
        logger.warning(f"Status desconhecido: {status}")
        message = f"ℹ️ Status da verificação: {status}"
        send_whatsapp_message(vendor_data, message)
    
    return jsonify({"status": "processed"}), 200

@app.route('/check-status/<phone>', methods=['GET'])
def check_status(phone):
    """Endpoint para consultar status de verificação (útil para debugging)"""
    if phone in verification_states:
        return jsonify(verification_states[phone]), 200
    else:
        return jsonify({"error": "Verificação não encontrada"}), 404

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint não encontrado"}), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Erro interno: {error}")
    return jsonify({"error": "Erro interno do servidor"}), 500

if __name__ == '__main__':
    # Verifica variáveis de ambiente críticas
    required_vars = [
        'VERIFF_API_KEY', 
        'INFOBIP_BASE_URL', 
        'INFOBIP_API_KEY', 
        'INFOBIP_SENDER'
    ]
    
    missing = [var for var in required_vars if not os.getenv(var)]
    if missing:
        logger.warning(f"Variáveis faltando: {', '.join(missing)}")
    
    app.run(debug=False, host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
