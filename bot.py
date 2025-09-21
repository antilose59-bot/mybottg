# bot.py — старт 2 кнопки, покупка = 4 кнопки (укр карта / рус карта (FunPay) / звёзды / крипта)
import asyncio
import logging
import traceback
from datetime import datetime, timedelta, timezone
import os
import sys
import aiohttp

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.client.bot import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice, PreCheckoutQuery, Message
)

# === ENV ===
load_dotenv()

API_TOKEN       = os.getenv("API_TOKEN")
ADMIN_ID        = int(os.getenv("ADMIN_ID", "0") or 0)
CHANNEL_ID_ENV  = os.getenv("CHANNEL_ID", "0")
PROVIDER_TOKEN  = os.getenv("PROVIDER_TOKEN")
CRYPTOPAY_TOKEN = os.getenv("CRYPTOPAY_TOKEN")

PRICE_XTR   = int(os.getenv("PRICE_XTR", "175"))       # цена в звёздах
PRICE_USD   = float(os.getenv("PRICE_USD", "2.50"))       # цена в USD для CryptoBot
CRYPTO_ASSETS = [a.strip() for a in os.getenv("CRYPTO_ASSETS", "TON,USDT,BTC").split(",") if a.strip()]

# реквизиты для карт
UKR_CARD_1 = os.getenv("UKR_CARD_1", "5168 7520 2233 6435")  # ПриватБанк
UKR_CARD_2 = os.getenv("UKR_CARD_2", "4441 1144 3233 1898")  # МоноБанк
FUNPAY_URL = os.getenv("FUNPAY_URL", "https://funpay.com/lots/offer?id=12345678")

SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "@christopherluvtwix")

if not API_TOKEN:
    raise ValueError("❌ Укажи API_TOKEN в .env")

try:
    CHANNEL_ID = int(CHANNEL_ID_ENV)
except Exception:
    CHANNEL_ID = CHANNEL_ID_ENV

logging.basicConfig(level=logging.INFO)

bot = Bot(API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp  = Dispatcher(storage=MemoryStorage())

# === CRYPTOBOT ===
CRYPTO_BASE = "https://pay.crypt.bot/api/"

async def get_exchange_rate(asset="TON"):
    headers = {"Crypto-Pay-API-Token": CRYPTOPAY_TOKEN}
    async with aiohttp.ClientSession() as s:
        async with s.get(CRYPTO_BASE + "getExchangeRates", headers=headers, timeout=20) as r:
            data = await r.json()
    for rate in data.get("result", []):
        try:
            if rate.get("source") == "USD" and rate.get("target") == asset:
                return float(rate["rate"])
            if rate.get("source") == asset and rate.get("target") == "USD":
                return 1 / float(rate["rate"])
        except Exception:
            continue
    raise RuntimeError(f"Не удалось получить курс для {asset}")

async def create_crypto_invoice(amount_usd: float, asset="TON"):
    rate = await get_exchange_rate(asset)
    amount = round(amount_usd * rate, 4)
    headers = {"Crypto-Pay-API-Token": CRYPTOPAY_TOKEN}
    payload = {"amount": amount, "asset": asset, "description": f"Доступ ${amount_usd} ({asset})"}
    async with aiohttp.ClientSession() as s:
        async with s.post(CRYPTO_BASE + "createInvoice", headers=headers, json=payload, timeout=20) as r:
            data = await r.json()
    if "result" in data:
        return data["result"]
    raise RuntimeError(str(data.get("error") or data))

async def check_invoice(invoice_id: str):
    headers = {"Crypto-Pay-API-Token": CRYPTOPAY_TOKEN}
    async with aiohttp.ClientSession() as s:
        async with s.get(CRYPTO_BASE + f"getInvoices?invoice_ids={invoice_id}", headers=headers, timeout=20) as r:
            data = await r.json()
    try:
        items = data.get("result", {}).get("items") or []
        return items[0] if items else None
    except Exception:
        return None

async def wait_for_crypto_payment(user_id: int, invoice_id: str, timeout_min: int = 6):
    attempts = max(1, int((timeout_min * 60) / 10))
    for _ in range(attempts):
        await asyncio.sleep(10)
        inv = await check_invoice(invoice_id)
        if not inv:
            continue
        if inv.get("status") == "paid":
            await create_and_send_invite(user_id, payment_method="CryptoBot")
            return
    try:
        await bot.send_message(user_id, "⏳ Оплата криптой не подтвердилась вовремя. Если вы платили — напишите администратору.")
    except Exception:
        pass

# === одноразовая ссылка ===
async def create_and_send_invite(user_id: int, payment_method="Неизвестно"):
    try:
        invite = await bot.create_chat_invite_link(
            chat_id=CHANNEL_ID,
            expire_date=int((datetime.now(timezone.utc) + timedelta(minutes=10)).timestamp()),
            member_limit=1,
            name=f"Оплата от {user_id}"
        )
        await bot.send_message(user_id,
            "✅ Оплата прошла!\n\n"
            f"🔗 Одноразовая ссылка (10 минут):\n{invite.invite_link}"
        )
        if ADMIN_ID:
            await bot.send_message(ADMIN_ID, f"💳 {payment_method}: user={user_id}\n{invite.invite_link}")
    except Exception as e:
        logging.error(f"Ошибка создания инвайта: {e}")
        tb = traceback.format_exc()
        try:
            fallback = await bot.export_chat_invite_link(CHANNEL_ID)
            await bot.send_message(user_id, f"⚠️ Одноразовая ссылка не сработала.\nВременная ссылка: {fallback}")
        except Exception:
            await bot.send_message(user_id, "❌ Ошибка при создании ссылки. Напишите администратору.")

# === Клавиатуры ===
def main_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Покупка приватного канала", callback_data="buy")],
        [InlineKeyboardButton(text="📞 Поддержка", url=f"https://t.me/christopherluvtwix")]
    ])

def pay_options_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇺🇦 Оплата картой (Украина)", callback_data="card_ukr")],
        [InlineKeyboardButton(text="🇷🇺 Оплата картой (Россия)", callback_data="card_ru")],
        [InlineKeyboardButton(text=f"⭐ Оплатить звёздами ({PRICE_XTR})", callback_data="pay_stars")],
        [InlineKeyboardButton(text=f"💎 CryptoBot (${PRICE_USD:.2f})", callback_data="crypto_choose")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")]
    ])

def crypto_assets_kb():
    rows = [[InlineKeyboardButton(text=asset, callback_data=f"crypto_{asset}")] for asset in CRYPTO_ASSETS]
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="buy")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

# === Handlers ===
@dp.message(F.text == "/start")
async def on_start(message: types.Message):
    text = (
        "Привет! Это приватка по продаже плагинов и схем.\n\n"
        "После оплаты получите одноразовую ссылку на канал.\n\n"
        "Выберите действие:"
    )
    await message.answer(text, reply_markup=main_menu_kb())

@dp.callback_query(F.data == "back_main")
async def back_main(cb: types.CallbackQuery):
    await cb.answer()
    await cb.message.edit_text(
        "Привет! Это приватка по продаже плагинов и схем.\n\n"
        "После оплаты получите одноразовую ссылку на канал.\n\n"
        "Выберите действие:",
        reply_markup=main_menu_kb()
    )

@dp.callback_query(F.data == "buy")
async def buy(cb: types.CallbackQuery):
    await cb.answer()
    await cb.message.edit_text("*Покупка приватного канала*\n\nВыберите удобный способ оплаты:",
                               reply_markup=pay_options_kb())

# --- Украина карта ---
@dp.callback_query(F.data == "card_ukr")
async def card_ukr(cb: types.CallbackQuery):
    await cb.answer()
    text = (
        "*Оплата картой (Украина)*\n\n"
        f"💳 {UKR_CARD_1} — ПриватБанк\n"
        f"💳 {UKR_CARD_2} — МоноБанк\n\n"
        f"После перевода отправьте чек админу @christopherluvtwix."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="buy")]])
    await cb.message.edit_text(text, reply_markup=kb)

# --- Россия карта (FunPay) ---
@dp.callback_query(F.data == "card_ru")
async def card_ru(cb: types.CallbackQuery):
    await cb.answer()
    text = (
        "*Оплата картой (Россия)*\n\n"
        f"Все продажи проходят через FunPay.\n\n"
        f"👉 [Ссылка на лот]({FUNPAY_URL})\n\n"
        f"После оплаты напишите админу @{SUPPORT_USERNAME}."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="buy")]])
    await cb.message.edit_text(text, reply_markup=kb)

# --- Stars ---
@dp.callback_query(F.data == "pay_stars")
async def pay_stars(cb: types.CallbackQuery):
    await cb.answer()
    prices = [LabeledPrice(label="Доступ в приватку", amount=PRICE_XTR)]
    await cb.message.answer_invoice(
        title="Доступ в приватку",
        description="Оплата звёздами (Telegram Stars)",
        provider_token=PROVIDER_TOKEN,
        currency="XTR",
        prices=prices,
        payload="stars_payment"
    )

@dp.pre_checkout_query()
async def pre_checkout(pcq: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pcq.id, ok=True)

@dp.message(F.successful_payment)
async def on_successful_payment(message: Message):
    await create_and_send_invite(message.from_user.id, payment_method="Звёзды")

# --- Crypto ---
@dp.callback_query(F.data == "crypto_choose")
async def crypto_choose(cb: types.CallbackQuery):
    await cb.answer()
    await cb.message.edit_text(f"Выберите валюту для оплаты (${PRICE_USD:.2f}):",
                               reply_markup=crypto_assets_kb())

@dp.callback_query(F.data.startswith("crypto_"))
async def crypto_pay(cb: types.CallbackQuery):
    await cb.answer()
    asset = cb.data.split("_", 1)[1]
    try:
        invoice = await create_crypto_invoice(amount_usd=PRICE_USD, asset=asset)
        pay_url = invoice.get("pay_url")
        invoice_id = invoice.get("invoice_id") or invoice.get("id")
        await cb.message.answer(
            f"💰 Оплата ${PRICE_USD:.2f} в {asset}\n\n👉 [Оплатить]({pay_url})\n\n"
            "После подтверждения сетью доступ будет выдан автоматически.",
            disable_web_page_preview=True
        )
        asyncio.create_task(wait_for_crypto_payment(cb.from_user.id, invoice_id))
    except Exception as e:
        logging.exception(e)
        await cb.message.answer(f"❌ Ошибка при создании счёта: {e}")

# === MAIN ===
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Бот остановлен")
    finally:
        try:
            asyncio.run(bot.session.close())
        except Exception:
            pass
    sys.exit(0)
