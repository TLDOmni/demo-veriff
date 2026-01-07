import os
import requests
from flask import Flask, request, jsonify, redirect

app = Flask(__name__)

# --- CONFIGURAÇÕES ---
VERIFF_API_URL = "https://stationapi.veriff.com/v1/sessions"
VERIFF_API_KEY = os.getenv("VERIFF_API_KEY")
VERIFF_SHARED_SECRET = os.getenv("VERIFF_SHARED_SECRET")

# Configurações Infobip
INFOBIP_BASE_URL = os.getenv("INFOBIP_BASE_URL") 
INFOBIP_API_KEY = os.getenv("INFOBIP_API_KEY")
INFOBIP_SENDER = os.getenv("INFOBIP_SENDER") 

# URL Base para o Webhook do Bot (Opção 1.1)
INFOBIP_WEBHOOK_BASE = "https://api2.infobip.com/bots/webhook"

# URL do seu Middleware no Render
MY_RENDER_URL = "https://demo-veriff.onrender.com"

# Link para voltar ao WhatsApp
WHATSAPP_LINK = f"https://wa.me/{INFOBIP_SENDER}" if INFOBIP_SENDER else "https://wa.me/"

# --- FUNÇÃO: ACIONAR O CHATBOT (WEBHOOK 1.1) ---
def trigger_infobip_webhook(session_id, status, reason=""):
    if not session_id:
        print("ERRO: SessionID não encontrado. Não é possível chamar o webhook.")
        return False

    webhook_target_url = f"{INFOBIP_WEBHOOK_BASE}/{session_id}"
    print(f"Acionando Webhook Infobip para Sessão {session_id} - Status: {status}")
    
    payload = {
        "veriff_status": status,
        "veriff_reason": reason
    }
    
    try:
        response = requests.post(webhook_target_url, json=payload)
        if response.status_code < 300:
            print("Sucesso! O Chatbot recebeu o sinal.")
            return True
        else:
            print(f"Erro Infobip Webhook ({response.status_code}): {response.text}")
            return False
    except Exception as e:
        print(f"Exceção ao chamar Infobip: {e}")
        return False

# --- FUNÇÃO: FALLBACK MENSAGEM ---
def send_whatsapp_message(to_number, text):
    if not to_number: return
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
        requests.post(url, json=payload, headers=headers)
    except:
        pass

# --- ENDPOINTS ---

@app.route('/', methods=['GET'])
def health_check():
    return "Middleware v3.1 (Key Updated: link_veriff) Online", 200

@app.route('/start-verification', methods=['POST'])
def start_verification():
    data = request.json
    
    phone = data.get('phoneNumber')
    session_id = data.get('sessionId')
    first_name = data.get('first_name', 'Usuario')
    last_name = data.get('last_name', '') 
    
    print(f"Iniciando: {first_name}, Tel: {phone}, Session: {session_id}")

    if not session_id:
        return jsonify({"error": "sessionId is required from Infobip"}), 400

    combined_data = f"{phone}::{session_id}"

    veriff_payload = {
        "verification": {
            "callback": f"{MY_RENDER_URL}/webhook/veriff", 
            "person": {
                "firstName": first_name,
                "lastName": last_name
            },
            "vendorData": combined_data, 
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
            url = response.json()['verification']['url']
            
            # --- ALTERAÇÃO AQUI: Chave agora é link_veriff ---
            return jsonify({"link_veriff": url}), 200
            
        else:
            return jsonify({"error": "Erro Veriff"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/webhook/veriff', methods=['POST', 'GET'])
def veriff_webhook():
    if request.method == 'GET':
        return redirect(WHATSAPP_LINK, code=302)

    data = request.json
    action = data.get('action')
    
    if action != 'decision':
        return jsonify({"status": "ignored"}), 200

    verification = data.get('verification', {})
    status = verification.get('status')
    reason = verification.get('reason', '')
    vendor_data_raw = verification.get('vendorData', '')

    phone = ""
    session_id = ""
    
    if "::" in vendor_data_raw:
        try:
            phone, session_id = vendor_data_raw.split("::")
        except:
            print("Erro parse vendorData")
    else:
        phone = vendor_data_raw

    print(f"Decisão: {status} | User: {phone} | Session: {session_id}")

    success = False
    if session_id:
        success = trigger_infobip_webhook(session_id, status, reason)
    
    if not success and phone:
        msg = "✅ Identidade validada!" if status == 'approved' else "❌ Falha na validação."
        send_whatsapp_message(phone, msg)

    return jsonify({"status": "received"}), 200

if __name__ == '__main__':
    app.run(debug=True)
