import os
import hashlib
import hmac
import requests
from flask import Flask, request, jsonify, redirect

app = Flask(__name__)

# --- CONFIGURAÇÕES VERIFF ---
# DOCUMENTAÇÃO: https://devdocs.veriff.com/docs/api-basics
# Esta é a URL padrão para criar sessões (tanto Sandbox quanto Produção usam a mesma URL base, 
# o que define o ambiente é a API Key utilizada).
VERIFF_API_URL = "https://stationapi.veriff.com/v1/sessions"

# API Key (Public Key) - Usada no Header X-AUTH-CLIENT para criar a sessão
VERIFF_API_KEY = os.getenv("VERIFF_API_KEY")

# API Secret (Private Key) - Usada APENAS para validar a assinatura do Webhook (Segurança)
VERIFF_SHARED_SECRET = os.getenv("VERIFF_SHARED_SECRET")

# --- CONFIGURAÇÕES INFOBIP ---
INFOBIP_BASE_URL = os.getenv("INFOBIP_BASE_URL") 
INFOBIP_API_KEY = os.getenv("INFOBIP_API_KEY")
INFOBIP_SENDER = os.getenv("INFOBIP_SENDER") 

# ... restante do código (WHATSAPP_LINK, funções, etc) ...
