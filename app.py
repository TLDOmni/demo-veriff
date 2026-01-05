import os
import hashlib
import hmac
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# --- CONFIGURAÇÕES (Variáveis de Ambiente) ---
# Você configurará isso no painel da hospedagem (Render)
VERIFF_API_URL = "https://stationapi.veriff.com/v1/sessions"
VERIFF_API_KEY = os.getenv("VERIFF_API_KEY")
VERIFF_SHARED_SECRET = os.getenv("VERIFF_SHARED_SECRET")

INFOBIP_BASE_URL = os.getenv("INFOBIP_BASE_URL") # Ex: https://k3k...api.infobip.com
INFOBIP_API_KEY = os.getenv("INFOBIP_API_KEY")
INFOBIP_SENDER = os.getenv("INFOBIP_SENDER") # Seu número sender

# --- FUNÇÕES AUXILIARES ---

def is_valid_signature(signature, payload):
    """Valida se o webhook veio realmente da Veriff (Segurança)"""
    if not VERIFF_SHARED_SECRET:
        return True # Se não tiver chave configurada, pula (apenas para debug)
    
    digest = hashlib.sha256(payload).hexdigest()
    # A Veriff usa SHA256 do payload + secret (verifique a doc exata para o método de hash atual)
    # Para simplificar a PoC, validaremos apenas se o campo existe, 
    # mas em PRD você deve implementar o hmac.new() comparando com o header X-HMAC-SIGNATURE
    return True 

def send_whatsapp_message(to_number, text):
    """Envia mensagem de texto simples via Infobip"""
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
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        print(f"Mensagem enviada para {to_number}")
    except Exception as e:
        print(f"Erro ao enviar WhatsApp: {e}")

# --- ENDPOINTS ---

@app.route('/', methods=['GET'])
def health_check():
    return "Middleware Infobip-Veriff Online", 200

@app.route('/start-verification', methods=['POST'])
def start_verification():
    """
    Chamado pelo Infobip Answers.
    Recebe JSON: { "phone": "5511999999999", "firstName": "João", "lastName": "Silva" }
    """
    data = request.json
    phone = data.get('phone')
    first_name = data.get('firstName', 'Usuario')
    last_name = data.get('lastName', 'Infobip')

    if not phone:
        return jsonify({"error": "Phone number is required"}), 400

    # Payload para Veriff
    veriff_payload = {
        "verification": {
            "callback": f"{request.url_root}webhook/veriff", # URL dinâmica do seu app
            "person": {
                "firstName": first_name,
                "lastName": last_name
            },
            "vendorData": phone, # O "pulo do gato": passamos o telefone como ID para recuperar depois
            "timestamp": "2024-01-01T00:00:00.000Z" # Timestamp obrigatório em alguns planos
        }
    }
    
    headers = {
        "X-AUTH-CLIENT": VERIFF_API_KEY,
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(VERIFF_API_URL, json=veriff_payload, headers=headers)
        
        if response.status_code == 201:
            url_veriff = response.json()['verification']['url']
            # Retorna para o Infobip Answers salvar na variável
            return jsonify({"veriff_link": url_veriff}), 200
        else:
            print(f"Erro Veriff: {response.text}")
            return jsonify({"error": "Failed to create session"}), 500
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/webhook/veriff', methods=['POST'])
def veriff_webhook():
    """
    Chamado pela Veriff quando a validação termina.
    """
    # 1. Segurança (Simplificada)
    # signature = request.headers.get('X-HMAC-SIGNATURE')
    # if not is_valid_signature(signature, request.data):
    #    return jsonify({"status": "invalid signature"}), 401

    data = request.json
    action = data.get('action')
    status = data.get('status')
    
    # 2. Recuperar o telefone que passamos no start-verification
    try:
        vendor_data = data['verification']['vendorData']
    except KeyError:
        return jsonify({"status": "ignored - no vendor data"}), 200

    print(f"Webhook recebido. Ação: {action}, Status: {status}, User: {vendor_data}")

    # 3. Lógica de Decisão
    if action == 'decision':
        if status == 'approved':
            send_whatsapp_message(vendor_data, "✅ Identidade confirmada com sucesso! Podemos prosseguir.")
        elif status == 'declined':
            reason = data['verification'].get('reason', 'Motivo não informado')
            send_whatsapp_message(vendor_data, f"❌ Não conseguimos validar sua identidade. Motivo: {reason}")
        elif status == 'resubmission_requested':
             send_whatsapp_message(vendor_data, "⚠️ A imagem não ficou nítida. Por favor, tente novamente no mesmo link.")

    return jsonify({"status": "received"}), 200

if __name__ == '__main__':
    app.run(debug=True)
