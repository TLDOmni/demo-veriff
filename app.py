import os
import requests
import json
from flask import Flask, request, jsonify, redirect

app = Flask(__name__)

# --- CONFIGURAÇÕES ---
VERIFF_API_URL = "https://stationapi.veriff.com/v1/sessions"
VERIFF_API_KEY = os.getenv("VERIFF_API_KEY")
VERIFF_SHARED_SECRET = os.getenv("VERIFF_SHARED_SECRET")

INFOBIP_BASE_URL = os.getenv("INFOBIP_BASE_URL") 
INFOBIP_API_KEY = os.getenv("INFOBIP_API_KEY")
INFOBIP_SENDER = os.getenv("INFOBIP_SENDER") 

# Link para redirecionar usuario ao final (WhatsApp)
WHATSAPP_LINK = f"https://wa.me/{INFOBIP_SENDER}" if INFOBIP_SENDER else "https://wa.me/"
MY_RENDER_URL = "https://demo-veriff.onrender.com"

# --- FUNÇÕES AUXILIARES ---
def get_veriff_headers():
    return {
        "X-AUTH-CLIENT": VERIFF_API_KEY,
        "Content-Type": "application/json"
    }

def send_whatsapp_message(to_number, text):
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
        print(f"Erro Infobip: {e}")

# --- ENDPOINTS ---

@app.route('/', methods=['GET'])
def health_check():
    return "Middleware Online. Endpoints: /start-verification, /check-status, /webhook/veriff", 200

# 1. INICIAR VERIFICAÇÃO
@app.route('/start-verification', methods=['POST'])
def start_verification():
    data = request.json
    
    # --- LOG SOLICITADO ---
    phone = data.get('phoneNumber')
    first_name = data.get('first_name')
    last_name = data.get('last_name')
    
    print("\n" + "="*40)
    print("DADOS RECEBIDOS DA INFOBIP:")
    print(f"First Name : {first_name}")
    print(f"Last Name  : {last_name}")
    print(f"Phone      : {phone}")
    print("="*40 + "\n")

    if not phone or "{" in str(phone):
        return jsonify({"error": "Telefone inválido ou variável não processada"}), 400

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
    
    try:
        response = requests.post(VERIFF_API_URL, json=veriff_payload, headers=get_veriff_headers())
        
        if response.status_code == 201:
            resp_json = response.json()
            url_veriff = resp_json['verification']['url']
            session_id = resp_json['verification']['id'] # ID IMPORTANTE
            
            # Retornamos Link e ID para o Infobip salvar
            return jsonify({
                "veriff_link": url_veriff,
                "session_id": session_id 
            }), 200
        else:
            print(f"Erro Veriff Create: {response.text}")
            return jsonify({"error": "Erro ao criar sessão"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 2. CHECAR STATUS (NOVO)
@app.route('/check-status', methods=['POST'])
def check_status():
    """
    Recebe { "session_id": "..." } da Infobip e consulta a Veriff
    """
    data = request.json
    session_id = data.get('session_id')
    
    print(f"Verificando status manualmente para ID: {session_id}")

    if not session_id:
        return jsonify({"status": "error", "message": "session_id is required"}), 400

    # Endpoint da Veriff para pegar a decisão
    # Docs: https://stationapi.veriff.com/v1/sessions/{id}/decision
    url = f"{VERIFF_API_URL}/{session_id}/decision"
    
    try:
        response = requests.get(url, headers=get_veriff_headers())
        
        if response.status_code == 200:
            decision_data = response.json()
            # O objeto pode variar dependendo se já tem decisão ou não
            verification = decision_data.get('verification', {})
            status = verification.get('status', 'pending') # approved, declined, resubmission_requested, pending
            reason = verification.get('reason', None)
            
            return jsonify({
                "status": status,
                "reason": reason
            }), 200
        else:
            print(f"Erro Veriff Status: {response.text}")
            return jsonify({"status": "error", "details": response.text}), response.status_code

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 3. WEBHOOK (COM REDIRECT)
@app.route('/webhook/veriff', methods=['POST', 'GET'])
def veriff_webhook():
    # GET = Usuário no navegador
    if request.method == 'GET':
        return redirect(WHATSAPP_LINK, code=302)

    # POST = Servidor da Veriff
    data = request.json
    action = data.get('action')
    
    if action == 'decision':
        verif = data.get('verification', {})
        status = verif.get('status')
        phone = verif.get('vendorData')
        
        print(f"Webhook: Decisão recebida ({status}) para {phone}")
        
        if status == 'approved':
            send_whatsapp_message(phone, "✅ Identidade validada (Via Webhook)!")
        elif status == 'declined':
            send_whatsapp_message(phone, "❌ Validação falhou (Via Webhook).")
        elif status == 'resubmission_requested':
            send_whatsapp_message(phone, "⚠️ Tente novamente (Via Webhook).")

    return jsonify({"status": "received"}), 200

if __name__ == '__main__':
    app.run(debug=True)
