import asyncio
from telegram.ext import Application, CommandHandler, ConversationHandler, MessageHandler, filters
from dotenv import load_dotenv
import os
import requests
import time
import re
import stripe
from fastapi import FastAPI, Request, Response
from contextlib import asynccontextmanager
import uvicorn
import logging

# Настройка логов
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Загружаем переменные из .env
load_dotenv()
TOKEN = os.getenv('TOKEN')
GROK_API_KEY = os.getenv('GROK_API_KEY')
STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY')
PORT = int(os.getenv('PORT', 8080))
WEBHOOK_URL = os.getenv('WEBHOOK_URL')

# Настройка Stripe
if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

# FastAPI для webhook
api_app = FastAPI()

# Создаём Application
app = Application.builder().token(TOKEN).build()

# Async lifespan for init
@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    await app.initialize()  # Инициализация здесь
    yield
    await app.shutdown()  # Cleanup

api_app.lifespan = lifespan

# Состояния диалога
BUSINESS, CLARIFY, PAY, CONNECT = range(4)

async def start(update, context):
    intro = (
        "Привет! Я Manoya — революционный AI-менеджер по продажам от xAI. Я заменяю целую команду: анализирую бизнес, квалифицирую лиды, веду продажи, фиксирую сделки в CRM, и обучаюсь на твоих данных. "
        "Мои достоинства: 24/7 работа, персонализация, рост продаж на 30-50%, простота настройки. За $10/мес ты получаешь топ-менеджера! Расскажи о бизнесе: продукты, аудитория, цены, цели."
    )
    await update.message.reply_text(intro)
    return BUSINESS

async def get_business(update, context):
    business_desc = update.message.text
    context.user_data['business'] = business_desc
    analysis = analyze_business(business_desc)
    context.user_data['analysis'] = analysis
    questions = generate_questions(business_desc)
    if questions:
        await update.message.reply_text(f"Я проанализировал: {analysis}. Уточни: {questions}")
        return CLARIFY
    await update.message.reply_text(f"Анализ: {analysis}. Напиши /pay для подписки $10/мес.")
    return PAY

async def clarify(update, context):
    clarification = update.message.text
    context.user_data['business'] += " " + clarification
    analysis = analyze_business(context.user_data['business'])
    context.user_data['analysis'] = analysis
    await update.message.reply_text(f"Обновлённый анализ: {analysis}. Напиши /pay для подписки.")
    return PAY

async def pay(update, context):
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{'price_data': {'currency': 'usd', 'product_data': {'name': 'Manoya Subscription'}, 'unit_amount': 1000}, 'quantity': 1}],
            mode='payment',
            success_url='https://example.com/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url='https://example.com/cancel'
        )
        await update.message.reply_text(f"Оплати здесь: {session.url}. После оплаты напиши /connect.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка оплаты: {str(e)}.")
    return CONNECT

async def connect(update, context):
    if 'client_token' not in context.user_data:
        await update.message.reply_text("Скинь токен бота (от @BotFather) для подключения.")
        return CONNECT
    client_token = context.user_data['client_token']
    await update.message.reply_text(f"Подключено! Управляю ботом ({client_token}). Тестируй запрос клиента.")
    return ConversationHandler.END

async def handle_connect_token(update, context):
    context.user_data['client_token'] = update.message.text
    await connect(update, context)

async def cancel(update, context):
    await update.message.reply_text("Диалог завершён. /start для начала.")
    return ConversationHandler.END

def analyze_business(description):
    prompt = f"Анализируй: '{description}'. Детали: продукты, аудитория, цены, цели, стратегии, риски."
    return call_grok_api(prompt)

def generate_questions(description):
    prompt = f"На основе '{description}', задай 1-3 вопроса (продукты, цены, аудитория)."
    return call_grok_api(prompt)

def call_grok_api(prompt):
    url = "https://api.x.ai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type": "application/json"}
    data = {"model": "grok-3", "messages": [{"role": "user", "content": prompt}], "temperature": 0.7}
    backoff = 2
    for attempt in range(3):
        try:
            response = requests.post(url, headers=headers, json=data, timeout=60)
            response.raise_for_status()
            return response.json()['choices'][0]['message']['content']
        except Exception as e:
            if attempt < 2:
                time.sleep(backoff)
                backoff *= 2
                continue
            return f"Ошибка API (попытка {attempt+1}): {str(e)}. Проверь кредиты/ключ."

# Добавляем handlers
conv_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        BUSINESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_business)],
        CLARIFY: [MessageHandler(filters.TEXT & ~filters.COMMAND, clarify)],
        PAY: [CommandHandler("pay", pay)],
        CONNECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_connect_token)]
    },
    fallbacks=[CommandHandler("cancel", cancel)]
)
app.add_handler(conv_handler)

@api_app.post("/webhook")
async def webhook(request: Request):
    json_data = await request.json()
    logger.info(f"Incoming webhook: {json_data}")
    await app.process_update(json_data)
    return Response(status_code=200)

@api_app.get("/")
async def root():
    logger.info("Root hit")
    return {"message": "Manoya bot is alive!"}

if __name__ == '__main__':
    uvicorn.run("bot:api_app", host="0.0.0.0", port=PORT)