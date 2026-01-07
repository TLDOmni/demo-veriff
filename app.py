import os
import requests
from flask import Flask, request, jsonify, redirect

app = Flask(__name__)

# --- CONFIGURAÇÕES GERAIS ---
VERIFF_API_URL = "https://stationapi.veriff.com/v1/sessions"
VERIFF_API_KEY = os.getenv("VERIFF_API_KEY")
VERIFF_SHARED_SECRET = os.getenv("VERIFF_SHARED_SECRET")

# --- CONFIGURAÇÕES INFOBIP ---
INFOBIP_BASE_URL = os.getenv("INFOBIP_BASE_URL") 
INFOBIP_API_KEY = os.getenv("INFOBIP_API_KEY")
INFOBIP_SENDER = os.getenv("INFOBIP_SENDER") 

# [NOVO] URL do Gatilho de Webhook do Infobip Answers
# Você vai gerar isso criando um fluxo que começa com "Webhook" no Infobip
INFOBIP_FLOW_URL = os.getenv("INFOBIP_FLOW_URL") 

# URL DO SEU BOT (Para redirecionar o usuario no final da UI da Veriff)
WHATSAPP_LINK = f"https://wa.me/{INFOBIP_SENDER}" if INFOBIP_SENDER else "https://wa.me/"

# SUA URL NO RENDER (Callback)
MY_RENDER_URL = "https://demo-veriff.onrender.com"

# --- FUNÇÕES AUXILIARES ---

def send_whatsapp_message(to_number, text):
    """Envia mensagem de texto simples (Fallback)"""
    if not to_number or "{" in to_number:
        print(f"ERRO: Número inválido para envio: {to_number}")
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
    except Exception as e:
        print(f"Erro fallback WhatsApp: {e}")

def trigger_infobip_flow(to_number, status, reason=""):
    """
    [NOVA FUNÇÃO]
    Chama o Webhook do Infobip Answers para continuar o fluxo do bot.
    Envia JSON: { "phone": "...", "status": "approved", "reason": "..." }
    """
    if not INFOBIP_FLOW_URL:
        print("INFOBIP_FLOW_URL não configurada. Usando envio de mensagem simples.")
        return False

    print(f"Acionando fluxo do Chatbot para {to_number} com status {status}...")
    
    payload = {
        "phone": to_number,
        "veriff_status": status, # approved / declined / resubmission_requested
        "veriff_reason": reason
    }
    
    # Dependendo da configuração do seu Webhook no Infobip, 
    # as vezes é necessário passar dados dentro de um objeto 'data' ou direto no root.
    # Vamos enviar direto no root (padrão mais comum).
    
    try:
        response = requests.post(INFOBIP_FLOW_URL, json=payload)
        print(f"Resposta do Infobip Flow: {response.status_code} - {response.text}")
        return response.status_code in [200, 201, 202]
    except Exception as e:
        print(f"Erro ao acionar fluxo Infobip: {e}")
        return False

# --- ENDPOINTS ---

@app.route('/', methods=['GET'])
def health_check():
    return "Middleware Veriff-Infobip v2 (Flow Trigger) Online.", 200

@app.route('/start-verification', methods=['POST'])
def start_verification():
    data = request.json
    
    phone = data.get('phoneNumber')
    first_name = data.get('first_name', 'Usuario')
    last_name = data.get('last_name', '') 
    
    print(f"Iniciando verificação para: {first_name} - Tel: {phone}")

    if not phone or "{" in phone:
        print("ALERTA: O número de telefone parece inválido (variável não processada).")

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

@app.route('/webhook/veriff', methods=['POST', 'GET'])
def veriff_webhook():
    
    # 1. Usuário voltando do navegador (Redirecionamento)
    if request.method == 'GET':
        return redirect(WHATSAPP_LINK, code=302)

    # 2. Webhook de Decisão da Veriff
    data = request.json
    action = data.get('action')
    
    if action != 'decision':
        return jsonify({"status": "ignored"}), 200

    vendor_data = data.get('verification', {}).get('vendorData') # Telefone
    status = data.get('verification', {}).get('status')
    reason = data.get('verification', {}).get('reason', '')

    print(f"Decisão Veriff recebida: {status} para {vendor_data}")

    # TENTA acionar o fluxo do Chatbot (Método Preferencial)
    flow_triggered = trigger_infobip_flow(vendor_data, status, reason)

    # Se não tiver URL de fluxo configurada, ou se falhar, usa o método antigo (Mensagem Texto)
    if not flow_triggered:
        if status == 'approved':
            send_whatsapp_message(vendor_data, "✅ Identidade validada com sucesso! (Mensagem via Middleware)")
        elif status == 'declined':
            send_whatsapp_message(vendor_data, f"❌ Falha na validação. Motivo: {reason}")
        elif status == 'resubmission_requested':
            send_whatsapp_message(vendor_data, "⚠️ A imagem não ficou nítida. Tente novamente.")

    return jsonify({"status": "received"}), 200

if __name__ == '__main__':
    app.run(debug=True)
