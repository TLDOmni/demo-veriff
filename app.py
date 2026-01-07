import os
import requests
from flask import Flask, request, jsonify, redirect

app = Flask(__name__)

# --- CONFIGURAÇÕES ---
VERIFF_API_URL = "https://stationapi.veriff.com/v1/sessions"
VERIFF_API_KEY = os.getenv("VERIFF_API_KEY")
VERIFF_SHARED_SECRET = os.getenv("VERIFF_SHARED_SECRET")

INFOBIP_BASE_URL = os.getenv("INFOBIP_BASE_URL") 
INFOBIP_API_KEY = os.getenv("INFOBIP_API_KEY")
INFOBIP_SENDER = os.getenv("INFOBIP_SENDER") 

# URL DO RENDER
MY_RENDER_URL = "https://demo-veriff.onrender.com"
# LINK PARA VOLTAR AO WHATSAPP
WHATSAPP_LINK = f"https://wa.me/{INFOBIP_SENDER}" if INFOBIP_SENDER else "https://wa.me/"

# --- FUNÇÃO ENVIO WHATSAPP OTIMIZADA ---
def send_whatsapp_message(to_number, text):
    if "{" in to_number or "}" in to_number:
        print(f"ERRO: Número inválido: {to_number}")
        return

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
        print(f"Notificação enviada para {to_number}")
    except Exception as e:
        print(f"Erro Infobip: {e}")

@app.route('/', methods=['GET'])
def health_check():
    return "Middleware Online", 200

@app.route('/start-verification', methods=['POST'])
def start_verification():
    data = request.json
    phone = data.get('phoneNumber')
    first_name = data.get('first_name', 'Usuario')
    last_name = data.get('last_name', '') 

    if not phone or "{" in phone:
        # Retorna erro para o bot saber que falhou a captura do numero
        return jsonify({"error": "Numero invalido"}), 400

    veriff_payload = {
        "verification": {
            "callback": f"{MY_RENDER_URL}/webhook/veriff", 
            "person": {"firstName": first_name, "lastName": last_name},
            "vendorData": phone,
            "timestamp": "2024-01-01T00:00:00.000Z" 
        }
    }
    
    headers = {"X-AUTH-CLIENT": VERIFF_API_KEY, "Content-Type": "application/json"}

    try:
        response = requests.post(VERIFF_API_URL, json=veriff_payload, headers=headers)
        if response.status_code == 201:
            return jsonify({"veriff_link": response.json()['verification']['url']}), 200
        else:
            return jsonify({"error": "Erro na Veriff"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- WEBHOOK INTELIGENTE ---
@app.route('/webhook/veriff', methods=['POST', 'GET'])
def veriff_webhook():
    
    # 1. Usuário voltando do navegador
    if request.method == 'GET':
        return redirect(WHATSAPP_LINK, code=302)

    # 2. Servidor da Veriff enviando status
    data = request.json
    action = data.get('action')
    
    if action != 'decision':
        return jsonify({"status": "ignored"}), 200

    vendor_data = data.get('verification', {}).get('vendorData')
    status = data.get('verification', {}).get('status')
    
    print(f"Decisão Veriff: {status} para {vendor_data}")

    # AQUI ESTÁ A MÁGICA DA RETOMADA
    if status == 'approved':
        # Texto estratégico para induzir o usuário a digitar a palavra-chave
        msg = (
            "✅ *Identidade Confirmada!*\n\n"
            "Seu cadastro foi validado com sucesso.\n"
            "👇 Digite *CONTINUAR* para acessar o menu exclusivo."
        )
        send_whatsapp_message(vendor_data, msg)
        
    elif status == 'declined':
        msg = (
            "❌ *Validação não aprovada.*\n\n"
            "Não conseguimos confirmar sua identidade.\n"
            "Digite *SUPORTE* para falar com um atendente."
        )
        send_whatsapp_message(vendor_data, msg)
        
    elif status == 'resubmission_requested':
        send_whatsapp_message(vendor_data, "⚠️ A foto ficou embaçada. Por favor, tente novamente no link anterior.")

    return jsonify({"status": "received"}), 200

if __name__ == '__main__':
    app.run(debug=True)
