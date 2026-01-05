import os
import hashlib
import hmac
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# --- CONFIGURAÇÕES (Variáveis de Ambiente) ---
# Configure estas variáveis no painel do Render.com
VERIFF_API_URL = "https://stationapi.veriff.com/v1/sessions"
VERIFF_API_KEY = os.getenv("VERIFF_API_KEY")
VERIFF_SHARED_SECRET = os.getenv("VERIFF_SHARED_SECRET")

INFOBIP_BASE_URL = os.getenv("INFOBIP_BASE_URL") # Ex: https://k3k...api.infobip.com
INFOBIP_API_KEY = os.getenv("INFOBIP_API_KEY")
INFOBIP_SENDER = os.getenv("INFOBIP_SENDER") # Seu número sender (ex: 447860099299)

# --- FUNÇÕES AUXILIARES ---

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
        # Em produção, você pode querer logar o corpo da resposta de erro da Infobip

# --- ENDPOINTS ---

@app.route('/', methods=['GET'])
def health_check():
    return "Middleware Infobip-Veriff Online e Atualizado", 200

@app.route('/start-verification', methods=['POST'])
def start_verification():
    """
    Chamado pelo Infobip Answers.
    Espera receber JSON: { "phoneNumber": "...", "first_name": "...", "last_name": "..." }
    """
    data = request.json
    
    # --- CORREÇÃO AQUI ---
    # Capturando as variáveis exatamente como vêm do Infobip
    phone = data.get('phoneNumber')
    first_name = data.get('first_name', 'Usuario')
    last_name = data.get('last_name', '') # Pode vir vazio se o usuário não tiver sobrenome no perfil
    
    # Debug: Print para ver o que chegou no log do Render
    print(f"Iniciando verificação para: {first_name} {last_name} - Tel: {phone}")

    if not phone:
        return jsonify({"error": "phoneNumber is required"}), 400

    # Payload para Veriff
    veriff_payload = {
        "verification": {
            "callback": f"{request.url_root}webhook/veriff", # URL do webhook neste mesmo app
            "person": {
                "firstName": first_name,
                "lastName": last_name
            },
            # vendorData é fundamental: passamos o telefone aqui para recebê-lo de volta no Webhook
            "vendorData": phone, 
            "timestamp": "2024-01-01T00:00:00.000Z" 
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
            # Retorna JSON com a chave "veriff_link" para você salvar na variável do Answers
            return jsonify({"veriff_link": url_veriff}), 200
        else:
            print(f"Erro Veriff ({response.status_code}): {response.text}")
            return jsonify({"error": "Failed to create session at Veriff"}), 500
            
    except Exception as e:
        print(f"Exceção no backend: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/webhook/veriff', methods=['POST'])
def veriff_webhook():
    """
    Chamado pela Veriff quando a validação termina.
    """
    data = request.json
    action = data.get('action')
    status = data.get('status')
    
    # Tentamos recuperar o telefone que enviamos no vendorData
    try:
        vendor_data = data['verification']['vendorData']
        phone_user = vendor_data # O vendorData é o phoneNumber
    except KeyError:
        print("Webhook recebido sem vendorData (telefone), ignorando envio de mensagem.")
        return jsonify({"status": "ignored - no vendor data"}), 200

    print(f"Webhook recebido. Ação: {action}, Status: {status}, User Phone: {phone_user}")

    # Lógica de Decisão e Envio para Infobip
    if action == 'decision':
        if status == 'approved':
            send_whatsapp_message(phone_user, "✅ Identidade confirmada com sucesso! Seu cadastro foi liberado.")
        elif status == 'declined':
            reason = data['verification'].get('reason', 'Motivo não informado')
            # Traduzindo motivos comuns (opcional)
            msg_fail = "❌ Não conseguimos validar sua identidade."
            if reason == "Microphone or camera not working":
                msg_fail += " Houve um problema com a câmera."
            send_whatsapp_message(phone_user, msg_fail)
        elif status == 'resubmission_requested':
             send_whatsapp_message(phone_user, "⚠️ A imagem não ficou nítida. Por favor, clique no link novamente e refaça a foto.")

    return jsonify({"status": "received"}), 200

if __name__ == '__main__':
    # O gunicorn usará a porta definida pelo Render, mas localmente usamos 5000
    app.run(debug=True)
