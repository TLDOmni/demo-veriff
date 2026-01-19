import os
import hashlib
import hmac
import requests
from flask import Flask, request, jsonify, redirect

app = Flask(__name__)

# --- CONFIGURAÇÕES ---
# Verifique se todas essas variáveis estão no Environment do Render
VERIFF_API_URL = "https://stationapi.veriff.com/v1/sessions"
VERIFF_API_KEY = os.getenv("VERIFF_API_KEY")
VERIFF_SHARED_SECRET = os.getenv("VERIFF_SHARED_SECRET")

INFOBIP_BASE_URL = os.getenv("INFOBIP_BASE_URL") 
INFOBIP_API_KEY = os.getenv("INFOBIP_API_KEY")
INFOBIP_SENDER = os.getenv("INFOBIP_SENDER") 

# Se o sender for numérico, monta o link, senão (ex: Alphanumeric) usa link genérico
WHATSAPP_LINK = f"https://wa.me/{INFOBIP_SENDER}" if INFOBIP_SENDER and INFOBIP_SENDER.isdigit() else "https://wa.me/"

MY_RENDER_URL = os.getenv("MY_RENDER_URL", "https://seu-app.onrender.com")

# --- SEGURANÇA: VALIDAÇÃO ASSINATURA VERIFF ---
def is_valid_signature(request_data, signature):
    """
    Verifica se o webhook veio realmente da Veriff comparando o hash SHA256.
    """
    if not VERIFF_SHARED_SECRET:
        print("ALERTA: VERIFF_SHARED_SECRET não configurado. Pulando validação (INSEGURO).")
        return True
        
    digest = hmac.new(
        key=VERIFF_SHARED_SECRET.encode('utf-8'),
        msg=request_data,
        digestmod=hashlib.sha256
    ).hexdigest()
    
    return digest.lower() == signature.lower()

# --- ENVIO WHATSAPP (INFOBIP) ---
def send_whatsapp_message(to_number, text):
    if not to_number or "{" in to_number:
        print(f"Erro: Número inválido para envio: {to_number}")
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
        if response.status_code not in [200, 201]:
            print(f"Erro Infobip {response.status_code}: {response.text}")
        else:
            print(f"Mensagem enviada para {to_number}")
    except Exception as e:
        print(f"Exception Infobip: {e}")

@app.route('/', methods=['GET'])
def health_check():
    return "API Veriff-Infobip Online v2.0", 200

@app.route('/start-verification', methods=['POST'])
def start_verification():
    data = request.json
    phone = data.get('phoneNumber')
    first_name = data.get('first_name', 'Usuario')
    last_name = data.get('last_name', '')
    
    # Validação básica
    if not phone or len(phone) < 8:
        return jsonify({"error": "Número de telefone inválido"}), 400

    print(f"Start Verification: {first_name} {last_name} ({phone})")

    veriff_payload = {
        "verification": {
            "callback": f"{MY_RENDER_URL}/webhook/veriff", 
            "person": {
                "firstName": first_name,
                "lastName": last_name
            },
            # Armazenamos o telefone no vendorData para recuperar no webhook
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
            session_url = response.json()['verification']['url']
            return jsonify({"veriff_link": session_url}), 200
        else:
            print(f"Erro ao criar sessão Veriff: {response.text}")
            return jsonify({"error": "Falha na criação da sessão"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/webhook/veriff', methods=['POST', 'GET'])
def veriff_webhook():
    # 1. Redirecionamento do Usuário (GET)
    if request.method == 'GET':
        return redirect(WHATSAPP_LINK, code=302)

    # 2. Processamento do Webhook (POST)
    
    # Verificar assinatura de segurança
    signature = request.headers.get('X-Hmac-Signature', '')
    if not is_valid_signature(request.data, signature):
        return jsonify({"error": "Assinatura inválida"}), 401

    data = request.json
    action = data.get('action')
    
    # Apenas nos importamos com a decisão final
    if action != 'decision':
        return jsonify({"status": "ignored"}), 200

    verification = data.get('verification', {})
    status = verification.get('status')
    reason = verification.get('reason', 'Não especificado')
    vendor_data = verification.get('vendorData') # Nosso número de telefone
    
    # Dados extraídos do documento (se disponíveis)
    person_data = verification.get('person', {})
    document_data = verification.get('document', {})

    print(f"Decisão Veriff: {status} para {vendor_data}")

    if status == 'approved':
        # Montar Resumo (Passo 9)
        extracted_name = f"{person_data.get('firstName', '')} {person_data.get('lastName', '')}"
        doc_number = document_data.get('number', 'N/A')
        doc_type = document_data.get('type', 'Documento')

        msg = (
            "✅ *Validação Aprovada com Sucesso!*\n\n"
            "Confira o resumo dos dados validados:\n"
            f"👤 *Nome:* {extracted_name}\n"
            f"📄 *Doc:* {doc_type}\n"
            f"🔢 *Número:* {doc_number}\n\n"
            "Seu cadastro foi liberado!"
        )
        send_whatsapp_message(vendor_data, msg)

    elif status == 'declined':
        # Motivo da rejeição (Passo 10.2)
        # Veriff pode enviar o reasonCode também, mas 'reason' costuma ser descritivo
        msg = (
            "❌ *Validação Rejeitada*\n\n"
            "Não foi possível validar sua identidade.\n"
            f"⚠️ *Motivo:* {reason}\n\n"
            "Por favor, inicie o processo novamente e atente-se à qualidade da foto."
        )
        send_whatsapp_message(vendor_data, msg)

    elif status == 'resubmission_requested':
        msg = (
            "⚠️ *Atenção: Necessário reenviar*\n\n"
            "A imagem enviada não estava nítida ou houve um erro técnico.\n"
            f"Motivo: {reason}\n"
            "Por favor, tente novamente no mesmo link ou reinicie o chat."
        )
        send_whatsapp_message(vendor_data, msg)

    return jsonify({"status": "processed"}), 200

if __name__ == '__main__':
    app.run(debug=True)
