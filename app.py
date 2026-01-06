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

# URL DO SEU BOT (Para redirecionar o usuario no final)
# Se o sender for 447860099299, a URL será https://wa.me/447860099299
WHATSAPP_LINK = f"https://wa.me/{INFOBIP_SENDER}" if INFOBIP_SENDER else "https://wa.me/"

# SUA URL NO RENDER
MY_RENDER_URL = "https://demo-veriff.onrender.com"

# --- FUNÇÃO ENVIO WHATSAPP ---
def send_whatsapp_message(to_number, text):
    # Proteção contra variaveis não preenchidas
    if "{" in to_number or "}" in to_number:
        print(f"ERRO CRÍTICO: Tentativa de envio para número inválido: {to_number}. Verifique o Infobip Answers.")
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
        response = requests.post(url, json=payload, headers=headers)
        # Log detalhado em caso de erro da Infobip
        if response.status_code != 200:
            print(f"Erro Infobip {response.status_code}: {response.text}")
        else:
            print(f"Mensagem enviada para {to_number}: {text}")
    except Exception as e:
        print(f"Erro de conexão Infobip: {e}")

@app.route('/', methods=['GET'])
def health_check():
    return "Middleware Veriff-Infobip Operacional.", 200

@app.route('/start-verification', methods=['POST'])
def start_verification():
    data = request.json
    
    phone = data.get('phoneNumber')
    first_name = data.get('first_name', 'Usuario')
    last_name = data.get('last_name', '') 
    
    print(f"Iniciando verificação para: {first_name} - Tel: {phone}")

    # Validação simples para evitar erro no log
    if not phone or "{" in phone:
        print("ALERTA: O número de telefone parece ser uma variável não processada do Infobip.")

    veriff_payload = {
        "verification": {
            "callback": f"{MY_RENDER_URL}/webhook/veriff", 
            "person": {
                "firstName": first_name,
                "lastName": last_name
            },
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
            return jsonify({"veriff_link": response.json()['verification']['url']}), 200
        else:
            print(f"Erro Veriff: {response.text}")
            return jsonify({"error": "Erro Veriff"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- CORREÇÃO PRINCIPAL AQUI ---
# Agora aceitamos GET (Navegador do usuário) e POST (Servidor da Veriff)
@app.route('/webhook/veriff', methods=['POST', 'GET'])
def veriff_webhook():
    
    # 1. Se for GET, é o usuário no navegador voltando da Veriff
    if request.method == 'GET':
        # Redireciona ele de volta para a conversa no WhatsApp
        return redirect(WHATSAPP_LINK, code=302)

    # 2. Se for POST, é o servidor da Veriff enviando o status
    data = request.json
    action = data.get('action')
    
    if action != 'decision':
        return jsonify({"status": "ignored"}), 200

    vendor_data = data.get('verification', {}).get('vendorData')
    status = data.get('verification', {}).get('status')
    reason = data.get('verification', {}).get('reason', '')

    print(f"Webhook Decision: {status} para User: {vendor_data}")

    if status == 'approved':
        send_whatsapp_message(vendor_data, "✅ Identidade validada com sucesso! Aguarde um momento.")
    elif status == 'declined':
        send_whatsapp_message(vendor_data, f"❌ Falha na validação. Motivo: {reason}")
    elif status == 'resubmission_requested':
        send_whatsapp_message(vendor_data, "⚠️ Imagem ruim. Tente novamente.")

    return jsonify({"status": "received"}), 200

if __name__ == '__main__':
    app.run(debug=True)
