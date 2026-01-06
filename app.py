import os
import hmac
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# --- CONFIGURAÇÕES ---
# Defina estas variáveis no painel "Environment" do Render
VERIFF_API_URL = "https://stationapi.veriff.com/v1/sessions"
VERIFF_API_KEY = os.getenv("VERIFF_API_KEY")
VERIFF_SHARED_SECRET = os.getenv("VERIFF_SHARED_SECRET")

INFOBIP_BASE_URL = os.getenv("INFOBIP_BASE_URL") 
INFOBIP_API_KEY = os.getenv("INFOBIP_API_KEY")
INFOBIP_SENDER = os.getenv("INFOBIP_SENDER") 

# SUA URL NO RENDER (Para o Webhook)
MY_RENDER_URL = "https://demo-veriff.onrender.com"

# --- FUNÇÃO PARA ENVIAR WHATSAPP (INFOBIP) ---
def send_whatsapp_message(to_number, text):
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
        print(f"Mensagem enviada para {to_number}: {text}")
    except Exception as e:
        print(f"Erro ao enviar WhatsApp: {e}")

# --- ROTA DE SAÚDE (Para checar se o Render está online) ---
@app.route('/', methods=['GET'])
def health_check():
    return "Middleware Veriff-Infobip Operacional. Webhook em: /webhook/veriff", 200

# --- 1. ROTA PARA CRIAR SESSÃO (Chamada pelo Infobip Answers) ---
@app.route('/start-verification', methods=['POST'])
def start_verification():
    data = request.json
    
    # Infobip envia estas variáveis
    phone = data.get('phoneNumber')
    first_name = data.get('first_name', 'Usuario')
    last_name = data.get('last_name', '') 
    
    print(f"Iniciando verificação para: {first_name} - Tel: {phone}")

    if not phone:
        return jsonify({"error": "phoneNumber is required"}), 400

    # Payload Oficial da Veriff
    veriff_payload = {
        "verification": {
            # AQUI ESTÁ O SEGREDO: Dizemos para a Veriff onde nos avisar
            "callback": f"{MY_RENDER_URL}/webhook/veriff", 
            "person": {
                "firstName": first_name,
                "lastName": last_name
            },
            # Passamos o telefone como vendorData para recuperar depois no webhook
            "vendorData": phone, 
            "timestamp": "2024-01-01T00:00:00.000Z" 
        }
    }
    
    headers = {
        "X-AUTH-CLIENT": VERIFF_API_KEY, # Sua API Key Pública
        "Content-Type": "application/json"
    }

    try:
        # Chamada para a API da Veriff
        response = requests.post(VERIFF_API_URL, json=veriff_payload, headers=headers)
        
        if response.status_code == 201:
            url_veriff = response.json()['verification']['url']
            # Devolvemos o link para o Chatbot da Infobip
            return jsonify({"veriff_link": url_veriff}), 200
        else:
            print(f"Erro Veriff ({response.status_code}): {response.text}")
            return jsonify({"error": "Erro ao criar sessão na Veriff"}), 500
            
    except Exception as e:
        print(f"Exceção interna: {str(e)}")
        return jsonify({"error": str(e)}), 500

# --- 2. ROTA DO WEBHOOK (Chamada pela Veriff) ---
@app.route('/webhook/veriff', methods=['POST'])
def veriff_webhook():
    data = request.json
    
    # Estrutura do JSON da Veriff: { "action": "decision", "verification": { "status": "approved", ... } }
    action = data.get('action')
    
    # Só nos importamos com eventos de decisão final
    if action != 'decision':
        return jsonify({"status": "ignored event"}), 200

    try:
        verification_data = data.get('verification', {})
        status = verification_data.get('status')
        vendor_data = verification_data.get('vendorData') # Aqui recuperamos o telefone
        
        if not vendor_data:
            print("Webhook recebido sem vendorData (telefone).")
            return jsonify({"status": "no user data"}), 200

        print(f"Webhook processado. Status: {status} para {vendor_data}")

        # Lógica de mensagens para o WhatsApp
        if status == 'approved':
            send_whatsapp_message(vendor_data, "✅ Identidade validada com sucesso! Seu cadastro foi aprovado.")
            
        elif status == 'declined':
            reason = verification_data.get('reason', 'Motivo não especificado')
            # Você pode mapear 'reason' para mensagens mais amigáveis se quiser
            send_whatsapp_message(vendor_data, f"❌ A validação falhou. Motivo detectado: {reason}")
            
        elif status == 'resubmission_requested':
            send_whatsapp_message(vendor_data, "⚠️ Não conseguimos ler seus documentos com clareza. Por favor, tente novamente no mesmo link.")

    except Exception as e:
        print(f"Erro ao processar webhook: {e}")
        return jsonify({"status": "error"}), 500

    return jsonify({"status": "received"}), 200

if __name__ == '__main__':
    app.run(debug=True)
