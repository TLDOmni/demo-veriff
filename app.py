import os
import requests
from flask import Flask, request, jsonify, redirect

app = Flask(__name__)

# --- CONFIGURAÇÕES ---
# Garanta que todas estas variáveis estejam no Environment do Render
VERIFF_API_URL = "https://stationapi.veriff.com/v1/sessions"
VERIFF_API_KEY = os.getenv("VERIFF_API_KEY")
VERIFF_SHARED_SECRET = os.getenv("VERIFF_SHARED_SECRET") # Utilizado para validação de assinatura (opcional, mas recomendado)

INFOBIP_BASE_URL = os.getenv("INFOBIP_BASE_URL") 
INFOBIP_API_KEY = os.getenv("INFOBIP_API_KEY")
INFOBIP_SENDER = os.getenv("INFOBIP_SENDER") 

# URL DO SEU BOT (Para redirecionar o usuario no final)
# Se o sender for algo como 5511999999999, a URL será https://wa.me/5511999999999
WHATSAPP_LINK = f"https://wa.me/{INFOBIP_SENDER}" if INFOBIP_SENDER else "https://wa.me/"

# SUA URL NO RENDER
MY_RENDER_URL = os.getenv("MY_RENDER_URL", "https://seu-app.onrender.com")

# --- FUNÇÃO ENVIO WHATSAPP ---
def send_whatsapp_message(to_number, text):
    if not to_number or "{" in to_number:
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
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code >= 400:
            print(f"Erro Infobip {response.status_code}: {response.text}")
        else:
            print(f"Mensagem enviada para {to_number}")
    except Exception as e:
        print(f"Erro de conexão Infobip: {e}")

@app.route('/', methods=['GET'])
def health_check():
    return "Middleware Veriff-Infobip Operacional v2.0", 200

@app.route('/start-verification', methods=['POST'])
def start_verification():
    data = request.json
    
    phone = data.get('phoneNumber')
    first_name = data.get('first_name', 'Usuario')
    last_name = data.get('last_name', '') 
    
    print(f"Iniciando: {first_name} - Tel: {phone}")

    # Payload para criar sessão na Veriff
    veriff_payload = {
        "verification": {
            # O callback notifica seu servidor (POST)
            "callback": f"{MY_RENDER_URL}/webhook/veriff", 
            "person": {
                "firstName": first_name,
                "lastName": last_name
            },
            # Passamos o telefone no vendorData para saber quem avisar depois
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
            # Retorna o link para o Chatbot (Infobip)
            return jsonify({"veriff_link": response.json()['verification']['url']}), 200
        else:
            print(f"Erro Veriff: {response.text}")
            return jsonify({"error": "Erro ao criar sessão Veriff"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/webhook/veriff', methods=['POST', 'GET'])
def veriff_webhook():
    
    # 1. GET: Usuário voltando do navegador (Redirecionamento)
    if request.method == 'GET':
        return redirect(WHATSAPP_LINK, code=302)

    # 2. POST: Veriff enviando o resultado da análise (Server-to-Server)
    data = request.json
    action = data.get('action')
    
    # Ignoramos eventos que não sejam a decisão final
    if action != 'decision':
        return jsonify({"status": "ignored"}), 200

    verification = data.get('verification', {})
    vendor_data = verification.get('vendorData') # Aqui está o telefone do usuário
    status = verification.get('status')
    reason = verification.get('reason', 'Não especificado')
    
    # Extração de dados do documento (para o resumo)
    document = verification.get('document', {})
    person = verification.get('person', {})
    
    doc_number = document.get('number', 'N/A')
    doc_type = document.get('type', 'Documento')
    doc_valid_until = document.get('validUntil', 'N/A')
    
    parsed_name = f"{person.get('firstName', '')} {person.get('lastName', '')}".strip()
    parsed_dob = person.get('dateOfBirth', 'N/A')
    parsed_gender = person.get('gender', 'N/A')

    print(f"Webhook Decision: {status} para {vendor_data}")

    # Lógica de Mensagens
    if status == 'approved':
        # Monta o resumo detalhado
        msg_text = (
            f"✅ *Identidade Validada com Sucesso!*\n\n"
            f"Recebemos a confirmação da Veriff. Segue o resumo dos dados extraídos:\n\n"
            f"👤 *Nome:* {parsed_name}\n"
            f"🎂 *Nascimento:* {parsed_dob}\n"
            f"🚻 *Gênero:* {parsed_gender}\n"
            f"📄 *Tipo Doc:* {doc_type}\n"
            f"🔢 *Número:* {doc_number}\n"
            f"📅 *Validade:* {doc_valid_until}\n\n"
            f"Seu cadastro prosseguirá automaticamente."
        )
        send_whatsapp_message(vendor_data, msg_text)
        
    elif status == 'declined':
        msg_text = (
            f"❌ *Validação Recusada*\n\n"
            f"Não conseguimos validar sua identidade.\n"
            f"⚠️ *Motivo:* {reason}\n\n"
            f"Por favor, certifique-se de que o documento está legível e tente novamente digitando 'Começar'."
        )
        send_whatsapp_message(vendor_data, msg_text)
        
    elif status == 'resubmission_requested':
        msg_text = (
            f"⚠️ *Atenção: Qualidade da Imagem*\n\n"
            f"A foto enviada não estava nítida ou o documento foi cortado.\n"
            f"Por favor, clique novamente no link anterior e reenvie as fotos com mais iluminação."
        )
        send_whatsapp_message(vendor_data, msg_text)

    return jsonify({"status": "received"}), 200

if __name__ == '__main__':
    app.run(debug=True)