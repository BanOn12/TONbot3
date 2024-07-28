import sys
import logging
import asyncio
import time
from base64 import urlsafe_b64encode
from pytonconnect.storage import IStorage, DefaultStorage
import pytonconnect.exceptions
from pytoniq_core import Address
from pytonconnect import TonConnect
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from pytoniq_core import begin_cell
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, Message
import sqlite3


logger = logging.getLogger(__file__)
TOKEN = ""
MANIFEST_URL = 'https://raw.githubusercontent.com/XaBbl4/pytonconnect/main/pytonconnect-manifest.json'

dp = Dispatcher()
bot = Bot(TOKEN, parse_mode=ParseMode.HTML)
storage = {}
global c
keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Подписан на тг", callback_data="check_subscription")],
    [InlineKeyboardButton(text="Подписался", callback_data="check_subscription")]])

class TcStorage(IStorage):

    def __init__(self, chat_id: int):
        self.chat_id = chat_id

    def _get_key(self, key: str):
        return str(self.chat_id) + key

    async def set_item(self, key: str, value: str):
        storage[self._get_key(key)] = value

    async def get_item(self, key: str, default_value: str = None):
        return storage.get(self._get_key(key), default_value)

    async def remove_item(self, key: str):
        storage.pop(self._get_key(key))

def get_comment_message(destination_address: str, amount: int, comment: str) -> dict:

    data = {
        'address': destination_address,
        'amount': str(amount),
        'payload': urlsafe_b64encode(
            begin_cell()
            .store_uint(0, 32)  # op code for comment message
            .store_string(comment)  # store comment
            .end_cell()  # end cell
            .to_boc()  # convert it to boc
        )
        .decode()  # encode it to urlsafe base64
    }

    return data

def get_connector(chat_id: int):
    return TonConnect(MANIFEST_URL, storage=TcStorage(chat_id))

@dp.message(CommandStart())
async def start_command(message: Message):
    await message.answer("Рыбка", reply_markup=keyboard)
    global c
    chat_id = message.chat.id
    c = chat_id
    return chat_id

async def command_start_handler(message: Message):
    connector = get_connector(message.chat.id)
    connected = await connector.restore_connection()

    mk_b = InlineKeyboardBuilder()
    if connected:
        mk_b.button(text='SОтправить транзакцию', callback_data='send_tr')
        mk_b.button(text='Отключиться', callback_data='disconnect')
        await bot.send_message(message.chat.id, text='Вы уже подключены!', reply_markup=mk_b.as_markup())
    else:
        wallets_list = TonConnect.get_wallets()
        for wallet in wallets_list:
            mk_b.button(text=wallet['name'], callback_data=f'connect:{wallet["name"]}')
        mk_b.adjust(1, )
        await message.answer(text='Выберите кошелёк для подключения', reply_markup=mk_b.as_markup())

@dp.callback_query(lambda c: c.data == "check_subscription")
async def check_subscription(callback_query: CallbackQuery):
    try:
        user_channel_status = await bot.get_chat_member(chat_id='@fdfdfdfdsssss', user_id=callback_query.from_user.id)
        if user_channel_status.status != 'left':
            await bot.send_message(chat_id=callback_query.from_user.id, text="Проверка твитера и телеграмма")
            await asyncio.sleep(5)
            # Создаем инлайн клавиатуру
            conn = sqlite3.connect('users.db')
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM buttons')
            buttons = cursor.fetchall()
            print(buttons)
            inline_keyboard = InlineKeyboardBuilder()
            for button in buttons:
                inline_keyboard.button(text=button[0], callback_data=button[1])
            # Добавляем кнопку "Успешно"
            inline_keyboard.button(text="Успешно", callback_data="start_command_handler")
            inline_keyboard.adjust(1)
            conn.close()

            # Отправляем сообщение "успешно" с инлайн клавиатурой
            await bot.send_message(chat_id=callback_query.from_user.id, text="Успешно", reply_markup=inline_keyboard.as_markup())
        else:
            await callback_query.answer('Для начала подпишитесь на наш канал')
    except Exception as e:
        await callback_query.answer('Не удалось проверить подписку. Пожалуйста, попробуйте позже.')
        print(f"Error: {e}")

@dp.message(Command('transaction'))
async def send_transaction(message: Message):
    connector = get_connector(message.chat.id)
    connected = await connector.restore_connection()
    if not connected:
        await message.answer('Сперва подключите кошелёк!')
        return

    transaction = {
        'valid_until': int(time.time() + 3600),
        'messages': [
            get_comment_message(
                destination_address='0:0000000000000000000000000000000000000000000000000000000000000000',
                amount=int(0.01 * 10 ** 9),
                comment='hello world!'
            )
        ]
    }

    await message.answer(text='Approve transaction in your wallet app!')
    try:
        await asyncio.wait_for(connector.send_transaction(
            transaction=transaction
        ), 300)
    except asyncio.TimeoutError:
        await message.answer(text='Время истекло!')
    except pytonconnect.exceptions.UserRejectsError:
        await message.answer(text='You rejected the transaction!')
    except Exception as e:
        await message.answer(text=f'Неизвестная ошибка: {e}')



async def connect_wallet(message: Message, wallet_name: str):
    connector = get_connector(message.chat.id)

    wallets_list = connector.get_wallets()
    wallet = None

    for w in wallets_list:
        if w['name'] == wallet_name:
            wallet = w

    if wallet is None:
        raise Exception(f'Неизвестный кошелёк: {wallet_name}')

    generated_url = await connector.connect(wallet)

    mk_b = InlineKeyboardBuilder()
    mk_b.button(text='Подключение', url=generated_url)

    await message.answer(text='Connect wallet within 3 minutes', reply_markup=mk_b.as_markup())

    mk_b = InlineKeyboardBuilder()
    mk_b.button(text='Start', callback_data='start')

    for i in range(1, 180):
        await asyncio.sleep(1)
        if connector.connected:
            if connector.account.address:
                wallet_address = connector.account.address
                wallet_address = Address(wallet_address).to_str(is_bounceable=False)
                await message.answer(f'You are connected with address <code>{wallet_address}</code>', reply_markup=mk_b.as_markup())
                logger.info(f'Connected with address: {wallet_address}')
            return

    await message.answer(f'Ошибка: время истекло!', reply_markup=mk_b.as_markup())

async def disconnect_wallet(message: Message):
    connector = get_connector(message.chat.id)
    await connector.restore_connection()
    await connector.disconnect()
    await message.answer('You have been successfully disconnected!')

@dp.callback_query(lambda call: True)
async def main_callback_handler(call: CallbackQuery):
    await call.answer()
    message = call.message
    data = call.data
    if data == "start":
        await command_start_handler(message)
    elif data == "send_tr":
        await send_transaction(message)
    elif data == 'disconnect':
        await disconnect_wallet(message)
    elif data == "start_command_handler":
        await command_start_handler(message)
    else:
        data = data.split(':')
        if data[0] == 'connect':
            await connect_wallet(message, data[1])

async def main() -> None:
    await bot.delete_webhook(drop_pending_updates=True)  # skip_updates = True
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())
